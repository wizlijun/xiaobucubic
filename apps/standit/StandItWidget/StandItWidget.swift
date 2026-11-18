import SwiftUI
import WidgetKit

@main
struct StandItWidgetBundle: WidgetBundle {
    var body: some Widget { StandItWidget() }
}

/// StandBy 左右两半之一：方形用 systemSmall；Duo 展开后的长条半屏试用 systemLarge / systemExtraLargePortrait。
struct StandItWidget: Widget {
    static var families: [WidgetFamily] {
        var families: [WidgetFamily] = [.systemSmall, .systemLarge]
        if #available(iOS 27.0, *) { families.append(.systemExtraLargePortrait) }
        return families
    }

    /// 尺寸越大，额度卡一次显示越多订阅。
    nonisolated static func quotaCount(_ family: WidgetFamily) -> Int {
        switch family {
        case .systemSmall: 3
        case .systemLarge: 5
        default: 8
        }
    }

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "StandItBoard", provider: BoardProvider()) { entry in
            WidgetCardView(entry: entry)
        }
        .configurationDisplayName("StandIt")
        .description("额度与便签轮播，适合放在待机的一半。")
        .supportedFamilies(Self.families)
    }
}

struct BoardEntry: TimelineEntry {
    let date: Date
    let card: WidgetCard
    /// 数据过期时的“数据时间 HH:MM”。
    var stale: String?
}

struct BoardProvider: TimelineProvider {
    func placeholder(in context: Context) -> BoardEntry {
        BoardEntry(date: .now, card: .quota([]))
    }

    func getSnapshot(in context: Context, completion: @escaping (BoardEntry) -> Void) {
        let cached = SnapshotCache.shared.load()
        let entry = WidgetTimeline.entries(cached: cached, error: nil, start: .now, minutes: 1,
                                           quotaCount: StandItWidget.quotaCount(context.family))[0]
        completion(BoardEntry(date: entry.0, card: entry.1, stale: nil))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<BoardEntry>) -> Void) {
        Task {
            let start = Date()
            let (cached, error) = await Self.load(now: start)
            let entries = WidgetTimeline.entries(cached: cached, error: error, start: start,
                                                quotaCount: StandItWidget.quotaCount(context.family)).map { date, card in
                BoardEntry(date: date, card: card, stale: Self.staleLabel(cached, error: error, at: date))
            }
            completion(Timeline(entries: entries, policy: .after(start.addingTimeInterval(15 * 60))))
        }
    }

    /// 先联网取最新；失败时退回 App Group 中的最后一次成功数据。
    private static func load(now: Date) async -> (CachedSnapshot?, FetchError?) {
        let cache = SnapshotCache.shared
        guard let config = ConfigStore.shared.load() else { return (cache.load(), .notConfigured) }
        do {
            let (_, raw) = try await DisplayClient().fetch(config)
            cache.store(raw: raw, receivedAt: Date(timeIntervalSince1970: now.timeIntervalSince1970.rounded(.down)))
            return (cache.load(), nil)
        } catch {
            return (cache.load(), error as? FetchError ?? .network("\(error)"))
        }
    }

    private static func staleLabel(_ cached: CachedSnapshot?, error: FetchError?, at date: Date) -> String? {
        guard let cached else { return nil }
        let received = Int(cached.receivedAt.timeIntervalSince1970)
        guard error != nil || Int(date.timeIntervalSince1970) - received > cached.snapshot.staleAfter else { return nil }
        return "数据时间 \(Format.clock(received))"
    }
}
