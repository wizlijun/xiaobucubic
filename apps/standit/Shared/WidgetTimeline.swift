import Foundation

/// 小组件一张卡片：剩余最少的几个额度、一张便签，或一条提示。
enum WidgetCard: Equatable {
    case quota([Subscription])
    case note(Note, paper: Int)
    case message(String)
}

enum WidgetTimeline {
    /// 每分钟一条：额度、便签1、额度、便签2…；每条按自己的时刻过滤已过期便签。
    static func entries(cached: CachedSnapshot?, error: FetchError?, start: Date, minutes: Int = 15) -> [(Date, WidgetCard)] {
        let base = start.timeIntervalSince1970.rounded(.down)
        return (0..<max(1, minutes)).map { i in
            let date = Date(timeIntervalSince1970: base + TimeInterval(i * 60))
            return (date, card(at: i, date: date, cached: cached, error: error))
        }
    }

    private static func card(at i: Int, date: Date, cached: CachedSnapshot?, error: FetchError?) -> WidgetCard {
        if error == .notConfigured { return .message(FetchError.notConfigured.message) }
        guard let cached else { return .message(error?.message ?? "打开 StandIt 同步数据") }
        let snapshot = cached.snapshot
        let now = Int(date.timeIntervalSince1970)
        let notes = snapshot.messages.enumerated().filter { $0.element.expiresAt.map { $0 > now } ?? true }
        guard i % 2 == 1, !notes.isEmpty else { return .quota(lowest(snapshot.subscriptions)) }
        let pick = notes[(i / 2) % notes.count]
        return .note(pick.element, paper: pick.offset)
    }

    /// 按各窗口中最低的剩余取最少的 3 个；没有数据的排最后，同值保持原顺序。
    static func lowest(_ subs: [Subscription], count: Int = 3) -> [Subscription] {
        let ranked = subs.enumerated().sorted { a, b in
            let ra = lowestRemaining(a.element) ?? Int.max
            let rb = lowestRemaining(b.element) ?? Int.max
            return ra != rb ? ra < rb : a.offset < b.offset
        }
        return ranked.prefix(count).map(\.element)
    }

    /// 细条显示的窗口：有次窗口用次窗口，否则主窗口。
    static func barWindow(_ sub: Subscription) -> QuotaWindow? { sub.windows.count > 1 ? sub.windows[1] : sub.windows.first }

    private static func lowestRemaining(_ sub: Subscription) -> Int? { sub.windows.compactMap(DisplayModel.remaining).min() }
}
