import XCTest
@testable import StandIt

/// 拦截 URLSession 请求，返回预设响应，并记录最后一次请求。
final class StubProtocol: URLProtocol {
    static var handler: ((URLRequest) -> (Int, Data))?
    static var lastRequest: URLRequest?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lastRequest = request
        let (status, body) = Self.handler?(request) ?? (500, Data())
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

final class ClientTests: XCTestCase {
    private var session: URLSession!
    private var dir: URL!
    private let config = EndpointConfig(url: URL(string: "http://h:8007/v1/display")!, token: "")

    private var demo: Data {
        get throws {
            try Data(contentsOf: XCTUnwrap(Bundle(for: Self.self).url(forResource: "display", withExtension: "json")))
        }
    }

    override func setUpWithError() throws {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [StubProtocol.self]
        session = URLSession(configuration: cfg)
        dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        StubProtocol.handler = nil
        StubProtocol.lastRequest = nil
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: dir)
    }

    func testEndpointNormalization() {
        XCTAssertEqual(Endpoint.normalize(" http://h:8007/ ")?.absoluteString, "http://h:8007/v1/display")
        XCTAssertEqual(Endpoint.normalize("http://h:8007")?.absoluteString, "http://h:8007/v1/display")
        XCTAssertEqual(Endpoint.normalize("http://h/v1/display")?.absoluteString, "http://h/v1/display")
        XCTAssertEqual(Endpoint.normalize("https://h/api/")?.absoluteString, "https://h/api/v1/display")
        XCTAssertNil(Endpoint.normalize("ftp://x"))
        XCTAssertNil(Endpoint.normalize(""))
        XCTAssertNil(Endpoint.normalize("h:8007"))
    }

    func testBearerHeaderOnlyWithToken() async throws {
        let body = try demo
        StubProtocol.handler = { _ in (200, body) }
        let client = DisplayClient(session: session)
        _ = try await client.fetch(config)
        XCTAssertNil(StubProtocol.lastRequest?.value(forHTTPHeaderField: "Authorization"))
        _ = try await client.fetch(EndpointConfig(url: config.url, token: "  abc  "))
        XCTAssertEqual(StubProtocol.lastRequest?.value(forHTTPHeaderField: "Authorization"), "Bearer abc")
        XCTAssertEqual(StubProtocol.lastRequest?.timeoutInterval, 10)
    }

    func testUnauthorizedMapped() async {
        let client = DisplayClient(session: session)
        for status in [401, 403] {
            StubProtocol.handler = { _ in (status, Data()) }
            do {
                _ = try await client.fetch(config)
                XCTFail("expected unauthorized")
            } catch {
                XCTAssertEqual(error as? FetchError, .unauthorized)
            }
        }
        StubProtocol.handler = { _ in (500, Data()) }
        do { _ = try await client.fetch(config); XCTFail() } catch { XCTAssertEqual(error as? FetchError, .http(500)) }
        StubProtocol.handler = { _ in (200, Data("{}".utf8)) }
        do { _ = try await client.fetch(config); XCTFail() } catch {
            guard case .invalid = error as? FetchError else { return XCTFail("\(error)") }
        }
    }

    func testCacheRoundTrip() throws {
        let cache = SnapshotCache(directory: dir)
        XCTAssertNil(cache.load())
        let at = Date(timeIntervalSince1970: 1_792_659_700)
        cache.store(raw: try demo, receivedAt: at)
        let loaded = try XCTUnwrap(SnapshotCache(directory: dir).load())
        XCTAssertEqual(loaded.receivedAt, at)
        XCTAssertEqual(loaded.snapshot, try DisplayModel.normalize(demo))
    }

    @MainActor
    func testFailureKeepsCache() async throws {
        let body = try demo
        let cache = SnapshotCache(directory: dir)
        let store = DisplayStore(client: DisplayClient(session: session), cache: cache, config: { self.config })
        StubProtocol.handler = { _ in (200, body) }
        await store.refresh()
        XCTAssertNil(store.error)
        let first = try XCTUnwrap(store.cached)

        StubProtocol.handler = { _ in (500, Data()) }
        await store.refresh()
        XCTAssertEqual(store.error, .http(500))
        XCTAssertEqual(store.cached?.receivedAt, first.receivedAt)

        StubProtocol.handler = { _ in (200, Data("not json".utf8)) }
        await store.refresh()
        XCTAssertEqual(cache.load()?.receivedAt, first.receivedAt)
        XCTAssertEqual(cache.load()?.snapshot, first.snapshot)

        StubProtocol.handler = { _ in (200, body) }
        await store.refresh()
        XCTAssertNil(store.error)
    }

    @MainActor
    func testRefreshWithoutConfig() async {
        let store = DisplayStore(client: DisplayClient(session: session), cache: SnapshotCache(directory: dir),
                                 config: { nil })
        await store.refresh()
        XCTAssertEqual(store.error, .notConfigured)
    }

    func testBackoffSequence() {
        XCTAssertEqual((0...9).map { Backoff.delay(failures: $0) }, [60, 5, 10, 20, 40, 80, 160, 300, 300, 300])
    }

    func testConfigStoreRoundTrip() throws {
        let store = ConfigStore(accessGroup: nil, account: "test-\(UUID().uuidString)")
        defer { store.clear() }
        XCTAssertNil(store.load())
        let cfg = EndpointConfig(url: URL(string: "http://h:8007/v1/display")!, token: "secret")
        try store.save(cfg)
        XCTAssertEqual(store.load(), cfg)
        store.clear()
        XCTAssertNil(store.load())
    }
}
