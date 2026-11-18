import Foundation
import WidgetKit

@MainActor
final class DisplayStore: ObservableObject {
    @Published private(set) var cached: CachedSnapshot?
    @Published private(set) var error: FetchError?
    private(set) var failures = 0

    private let client: DisplayClient
    private let cache: SnapshotCache
    private let config: () -> EndpointConfig?

    init(client: DisplayClient = DisplayClient(), cache: SnapshotCache = .shared,
         config: @escaping () -> EndpointConfig? = { ConfigStore.shared.load() }) {
        self.client = client
        self.cache = cache
        self.config = config
        cached = cache.load()
    }

    /// 成功：写缓存、刷新小组件；失败：保留旧数据，只记录错误。
    func refresh() async {
        guard let config = config() else {
            error = .notConfigured
            return
        }
        do {
            let (snapshot, raw) = try await client.fetch(config)
            // 整秒：与缓存文件中的精度一致。
            let now = Date(timeIntervalSince1970: Date().timeIntervalSince1970.rounded(.down))
            cache.store(raw: raw, receivedAt: now)
            cached = CachedSnapshot(snapshot: snapshot, receivedAt: now)
            error = nil
            failures = 0
            WidgetCenter.shared.reloadAllTimelines()
        } catch {
            self.error = error as? FetchError ?? .network("网络错误")
            failures += 1
        }
    }

    func reloadFromCache() {
        cached = cache.load()
        error = nil
        failures = 0
    }

    var nextDelay: TimeInterval { Backoff.delay(failures: failures) }
}
