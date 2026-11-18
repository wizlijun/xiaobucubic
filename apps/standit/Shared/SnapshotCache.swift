import Foundation

struct CachedSnapshot: Equatable {
    var snapshot: DisplaySnapshot
    var receivedAt: Date
}

/// App Group 中的最后一次成功数据：原始 JSON + 接收时间，App 与小组件共用。
final class SnapshotCache {
    private let file: URL

    init(directory: URL) {
        file = directory.appendingPathComponent("last-display.json")
    }

    static var shared: SnapshotCache {
        let dir = SharedConfig.appGroup.flatMap {
            FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: $0)
        } ?? FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        return SnapshotCache(directory: dir)
    }

    func load() -> CachedSnapshot? {
        guard let data = try? Data(contentsOf: file),
              let envelope = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let received = envelope["received_at"] as? Int,
              let document = envelope["document"],
              let raw = try? JSONSerialization.data(withJSONObject: document),
              let snapshot = try? DisplayModel.normalize(raw) else { return nil }
        return CachedSnapshot(snapshot: snapshot, receivedAt: Date(timeIntervalSince1970: TimeInterval(received)))
    }

    func store(raw: Data, receivedAt: Date) {
        guard let document = try? JSONSerialization.jsonObject(with: raw),
              let data = try? JSONSerialization.data(withJSONObject: ["received_at": Int(receivedAt.timeIntervalSince1970.rounded(.down)),
                                                                      "document": document]) else { return }
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        // 锁屏（StandBy）时小组件也要能读。
        try? data.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }
}
