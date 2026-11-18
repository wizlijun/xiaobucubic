import XCTest
@testable import StandIt

final class DisplayModelTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "json"))
        return try Data(contentsOf: url)
    }

    private func json(_ object: [String: Any]) -> Data {
        try! JSONSerialization.data(withJSONObject: object)
    }

    private func doc(subscriptions: [[String: Any]] = [], messages: [[String: Any]] = [], weather: Any = NSNull(),
                     version: Int = 1) -> Data {
        json(["schema_version": version, "generated_at": 1792664580, "subscriptions": subscriptions,
              "messages": messages, "weather": weather])
    }

    // MARK: remaining / level

    func testRemainingMatchesLua() {
        func r(_ used: Double?) -> Int? { DisplayModel.remaining(QuotaWindow(label: "x", usedPercent: used)) }
        XCTAssertEqual(r(62), 38)
        XCTAssertEqual(r(33.5), 66)
        XCTAssertEqual(r(99.6), 0)
        XCTAssertEqual(r(0), 100)
        XCTAssertEqual(r(150), 0)
        XCTAssertNil(r(nil))
        XCTAssertNil(DisplayModel.remaining(nil))
    }

    func testQuotaLevelThresholds() {
        XCTAssertEqual(DisplayModel.quotaLevel(20), .normal)
        XCTAssertEqual(DisplayModel.quotaLevel(19), .low)
        XCTAssertEqual(DisplayModel.quotaLevel(5), .low)
        XCTAssertEqual(DisplayModel.quotaLevel(4), .critical)
        XCTAssertEqual(DisplayModel.quotaLevel(nil), .unknown)
    }

    // MARK: Format

    func testBytes() {
        XCTAssertEqual(Format.bytes(805_306_368_000), "750GiB")
        XCTAssertEqual(Format.bytes(1536), "1.5KiB")
        XCTAssertEqual(Format.bytes(1023), "1023B")
        XCTAssertEqual(Format.bytes(nil), "--")
    }

    func testResetDate() {
        let now = 1792664580 // 2026-10-22 周四 18:23 UTC+8
        XCTAssertEqual(Format.resetDate(1792669799, now: now), "19:49重置")
        XCTAssertEqual(Format.resetDate(1792846800, now: now), "周六21:00重置")
        XCTAssertEqual(Format.resetDate(1793199840, now: now), "10/28 23:04重置")
        XCTAssertEqual(Format.resetDate(1799112600, now: now), "2027/01/05 09:30重置")
        XCTAssertEqual(Format.resetDate(nil, now: now), "")
    }

    func testWindowLabel() {
        XCTAssertEqual(Format.windowLabel(QuotaWindow(label: "7天", usedPercent: 1)), "周限")
        XCTAssertEqual(Format.windowLabel(QuotaWindow(label: "5小时", usedPercent: 1)), "5小时")
        XCTAssertEqual(Format.windowLabel(nil), "暂无用量")
    }

    // MARK: normalize

    func testDemoFixture() throws {
        let s = try DisplayModel.normalize(fixture("display"))
        XCTAssertTrue(s.demo)
        XCTAssertEqual(s.staleAfter, 900)
        XCTAssertEqual(s.subscriptions.map(\.id), ["claude", "codex", "grok"])
        XCTAssertEqual(s.subscriptions[0].windows.count, 2)
        XCTAssertEqual(s.subscriptions[2].windows.count, 0)
        XCTAssertEqual(s.messages.count, 2)
        XCTAssertEqual(s.messages[1].priority, "high")
        XCTAssertEqual(s.weather?.city, "深圳")
        XCTAssertEqual(s.weather?.temperatureC, 27.8)
    }

    func testExtendedFixture() throws {
        let s = try DisplayModel.normalize(fixture("display-v1-extended"))
        XCTAssertFalse(s.demo)
        XCTAssertEqual(s.messages.first?.isBot, true)
        XCTAssertEqual(s.messages.first?.expiresAt, 1792664640)
        XCTAssertEqual(s.weather?.condition, "晴间多云")
    }

    func testMinimalDocument() throws {
        let s = try DisplayModel.normalize(doc())
        XCTAssertTrue(s.subscriptions.isEmpty)
        XCTAssertTrue(s.messages.isEmpty)
        XCTAssertNil(s.weather)
    }

    func testRejectsUnsupportedVersion() {
        XCTAssertThrowsError(try DisplayModel.normalize(doc(version: 2))) {
            XCTAssertEqual($0 as? DisplayError, .unsupportedVersion)
        }
        XCTAssertThrowsError(try DisplayModel.normalize(Data("nope".utf8))) {
            XCTAssertEqual($0 as? DisplayError, .badFormat)
        }
        XCTAssertThrowsError(try DisplayModel.normalize(json(["schema_version": 1, "subscriptions": [], "messages": []]))) {
            XCTAssertEqual($0 as? DisplayError, .missingTime)
        }
    }

    func testDuplicateIdsAndWindowLimit() throws {
        let w: [String: Any] = ["label": "a", "used_percent": 10]
        let s = try DisplayModel.normalize(doc(subscriptions: [
            ["id": "x", "name": "First", "windows": [w, w, w]],
            ["id": "x", "name": "Second", "windows": []],
            ["name": "no id"],
        ]))
        XCTAssertEqual(s.subscriptions.map(\.name), ["First"])
        XCTAssertEqual(s.subscriptions[0].windows.count, 2)
    }

    func testNameFallsBackToId() throws {
        let s = try DisplayModel.normalize(doc(subscriptions: [["id": "codex", "windows": []]]))
        XCTAssertEqual(s.subscriptions[0].name, "codex")
    }

    func testTrafficWindowComputesPercent() throws {
        let s = try DisplayModel.normalize(doc(subscriptions: [["id": "b", "windows": [
            ["label": "月度", "used_percent": 99, "total_bytes": 1_073_741_824_000, "used_bytes": 268_435_456_000],
        ]]]))
        let w = s.subscriptions[0].windows[0]
        XCTAssertEqual(w.usedPercent, 25)
        XCTAssertEqual(w.remainingBytes, 805_306_368_000)
    }

    func testMessagesFilteredAndCapped() throws {
        var messages: [[String: Any]] = [["text": "   "], ["title": "no text"], ["text": "a\r\nb"]]
        for i in 0..<20 { messages.append(["text": "m\(i)"]) }
        let s = try DisplayModel.normalize(doc(messages: messages))
        XCTAssertEqual(s.messages.count, 12)
        XCTAssertEqual(s.messages[0].text, "a\nb")
        let long = try DisplayModel.normalize(doc(messages: [["text": String(repeating: "字", count: 300)]]))
        XCTAssertEqual(long.messages[0].text.count, 180)
    }

    // MARK: weather / staleness / notes

    func testWeatherAsset() {
        func a(_ c: String, day: Bool? = nil) -> String? { DisplayModel.weatherAsset(Weather(condition: c, isDay: day)) }
        XCTAssertEqual(a("晴间多云"), "partly_cloudy")
        XCTAssertEqual(a("雷阵雨"), "rain")
        XCTAssertEqual(a("小雪"), "snow")
        XCTAssertEqual(a("阴"), "overcast")
        XCTAssertEqual(a("雾"), "overcast")
        XCTAssertEqual(a("晴"), "sunny")
        XCTAssertEqual(a("晴", day: false), "clear_night")
        XCTAssertEqual(a("??"), "overcast")
        XCTAssertNil(DisplayModel.weatherAsset(nil))
    }

    func testStaleness() {
        XCTAssertFalse(DisplayModel.isStale(1000, now: 1500, ttl: 900))
        XCTAssertTrue(DisplayModel.isStale(1000, now: 2000, ttl: 900))
        XCTAssertTrue(DisplayModel.isStale(nil, now: 1000, ttl: 900))
        XCTAssertTrue(DisplayModel.isStale(2000, now: 1000, ttl: 900)) // 来自未来 >300 秒
    }

    func testWindowState() {
        let sub = Subscription(id: "a", name: "A", source: "official", updatedAt: 1000, windows: [])
        XCTAssertEqual(DisplayModel.windowState(sub, QuotaWindow(label: "x", usedPercent: 1, resetAt: 2000), now: 1100, ttl: 900), .ok)
        XCTAssertEqual(DisplayModel.windowState(sub, QuotaWindow(label: "x", usedPercent: 1, resetAt: 1050), now: 1100, ttl: 900), .expired)
        XCTAssertEqual(DisplayModel.windowState(sub, QuotaWindow(label: "x", usedPercent: 1), now: 5000, ttl: 900), .stale)
        XCTAssertEqual(DisplayModel.windowState(sub, QuotaWindow(label: "x", usedPercent: nil), now: 1100, ttl: 900), .unknown)
    }

    func testActiveNotesDropExpired() throws {
        let s = try DisplayModel.normalize(doc(messages: [
            ["text": "keep"], ["text": "gone", "expires_at": 1792664000], ["text": "later", "expires_at": 1792669000],
        ]))
        XCTAssertEqual(DisplayModel.activeNotes(s, now: 1792664580).map(\.text), ["keep", "later"])
    }

    func testSnapshotCodableRoundTrip() throws {
        let s = try DisplayModel.normalize(fixture("display"))
        let back = try JSONDecoder().decode(DisplaySnapshot.self, from: JSONEncoder().encode(s))
        XCTAssertEqual(back, s)
    }
}
