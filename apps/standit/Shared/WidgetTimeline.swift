import Foundation

/// 小组件一张卡片：剩余最少的几个额度、一张便签，或一条提示。
enum WidgetCard: Equatable {
    case quota([Subscription])
    case note(Note, paper: Int, count: Int)
    case message(String)
}

/// 两个小组件各管一样：余量只显示额度，便签只轮播便签；StandBy 里由用户自己切换。
enum WidgetContent {
    case quota, notes
}

enum WidgetTimeline {
    /// 每分钟一条；便签小组件逐条轮播，每条按自己的时刻过滤已过期便签。
    static func entries(cached: CachedSnapshot?, error: FetchError?, start: Date, minutes: Int = 15,
                        quotaCount: Int = 3, content: WidgetContent = .quota) -> [(Date, WidgetCard)] {
        let base = start.timeIntervalSince1970.rounded(.down)
        return (0..<max(1, minutes)).map { i in
            let date = Date(timeIntervalSince1970: base + TimeInterval(i * 60))
            return (date, card(at: i, date: date, cached: cached, error: error, quotaCount: quotaCount, content: content))
        }
    }

    private static func card(at i: Int, date: Date, cached: CachedSnapshot?, error: FetchError?, quotaCount: Int,
                             content: WidgetContent) -> WidgetCard {
        if error == .notConfigured { return .message(FetchError.notConfigured.message) }
        guard let cached else { return .message(error?.message ?? "打开 Stand It 同步数据") }
        let snapshot = cached.snapshot
        switch content {
        case .quota:
            return .quota(lowest(snapshot.subscriptions, count: quotaCount))
        case .notes:
            let notes = DisplayModel.activeNotes(snapshot, now: Int(date.timeIntervalSince1970))
            guard !notes.isEmpty else { return .message("暂无便签") }
            let index = i % notes.count
            return .note(notes[index], paper: index, count: notes.count)
        }
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

    /// 小组件便签的抬头字号、抬头高度（设备 29:12）、底部小字字号和正文字号；k 为小组件缩放（1…3）。
    /// 正文字号固定，不随内容多少缩放。
    static func noteChrome(k: CGFloat) -> (header: CGFloat, headerHeight: CGFloat, meta: CGFloat, body: CGFloat) {
        (8 * k, (8 * k * 29 / 12).rounded(), 7 * k, 16 * k)
    }

    /// 背景被系统去掉时是否由小组件自己画便签纸。
    static func drawsOwnPaper(showsBackground: Bool, vibrant: Bool) -> Bool { !showsBackground && !vibrant }
}
