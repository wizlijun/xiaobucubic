import XCTest
@testable import StandIt

final class WidgetTimelineTests: XCTestCase {
    private let t0 = 1_792_664_580

    private func cached(_ subs: [Subscription] = [], notes: [Note] = []) -> CachedSnapshot {
        CachedSnapshot(snapshot: DisplaySnapshot(generatedAt: t0, staleAfter: 900, demo: false, subscriptions: subs,
                                                 messages: notes, weather: nil),
                       receivedAt: Date(timeIntervalSince1970: TimeInterval(t0)))
    }

    private func sub(_ id: String, used: Double?) -> Subscription {
        Subscription(id: id, name: id, source: "official", updatedAt: t0,
                     windows: used.map { [QuotaWindow(label: "5小时", usedPercent: $0)] } ?? [])
    }

    private func kinds(_ entries: [(Date, WidgetCard)]) -> [String] {
        entries.map {
            switch $0.1 {
            case .quota: "q"
            case .note(let n, _, _): n.text
            case .message(let m): "msg:" + m
            }
        }
    }

    private var start: Date { Date(timeIntervalSince1970: TimeInterval(t0)) }

    /// 余量小组件只显示额度，有便签也不轮播。
    func testQuotaWidgetNeverShowsNotes() {
        let entries = WidgetTimeline.entries(cached: cached(notes: [Note(text: "a"), Note(text: "b")]), error: nil,
                                             start: start, minutes: 4, content: .quota)
        XCTAssertEqual(kinds(entries), ["q", "q", "q", "q"])
        XCTAssertEqual(entries.map { Int($0.0.timeIntervalSince1970) - t0 }, [0, 60, 120, 180])
    }

    /// 便签小组件每分钟换一张便签，不夹额度。
    func testNotesWidgetRotatesEveryMinute() {
        let entries = WidgetTimeline.entries(cached: cached(notes: [Note(text: "a"), Note(text: "b")]), error: nil,
                                             start: start, minutes: 5, content: .notes)
        XCTAssertEqual(kinds(entries), ["a", "b", "a", "b", "a"])
        XCTAssertEqual(entries.map { Int($0.0.timeIntervalSince1970) - t0 }, [0, 60, 120, 180, 240])
    }

    func testExpiredNotesSkipped() {
        let notes = [Note(text: "a", expiresAt: t0 + 180), Note(text: "b")]
        let entries = WidgetTimeline.entries(cached: cached(notes: notes), error: nil, start: start, minutes: 6,
                                             content: .notes)
        XCTAssertEqual(kinds(entries), ["a", "b", "a", "b", "b", "b"])
    }

    /// 没有有效便签时便签小组件给出提示，而不是改显示额度。
    func testNotesWidgetWithoutNotes() {
        let gone = WidgetTimeline.entries(cached: cached([sub("a", used: 10)], notes: [Note(text: "x", expiresAt: t0)]),
                                          error: nil, start: start, minutes: 2, content: .notes)
        XCTAssertEqual(kinds(gone), ["msg:暂无便签", "msg:暂无便签"])
        XCTAssertEqual(kinds(WidgetTimeline.entries(cached: nil, error: .notConfigured, start: start, minutes: 1,
                                                    content: .notes)),
                       ["msg:打开 Stand It 设置接入点"])
    }

    /// 便签卡带上在有效便签中的序号和总数，用于抬头“便签 · 2 / 3”。
    func testNoteCardCarriesPositionAndCount() {
        let notes = [Note(text: "a", expiresAt: t0 + 120), Note(text: "b"), Note(text: "c")]
        let entries = WidgetTimeline.entries(cached: cached(notes: notes), error: nil, start: start, minutes: 4,
                                             content: .notes)
        XCTAssertEqual(entries[0].1, .note(notes[0], paper: 0, count: 3))
        XCTAssertEqual(entries[1].1, .note(notes[1], paper: 1, count: 3))
        XCTAssertEqual(entries[2].1, .note(notes[1], paper: 0, count: 2))
        XCTAssertEqual(entries[3].1, .note(notes[2], paper: 1, count: 2))
    }

    func testNotConfiguredMessage() {
        XCTAssertEqual(kinds(WidgetTimeline.entries(cached: nil, error: .notConfigured, start: start, minutes: 2)),
                       ["msg:打开 Stand It 设置接入点", "msg:打开 Stand It 设置接入点"])
        XCTAssertEqual(kinds(WidgetTimeline.entries(cached: cached(), error: .notConfigured, start: start, minutes: 1)),
                       ["msg:打开 Stand It 设置接入点"])
        XCTAssertEqual(kinds(WidgetTimeline.entries(cached: nil, error: .unauthorized, start: start, minutes: 1)),
                       ["msg:鉴权失败"])
        XCTAssertEqual(kinds(WidgetTimeline.entries(cached: cached(), error: .unauthorized, start: start, minutes: 1)),
                       ["q"])
    }

    func testLowestThreeQuotas() {
        let subs = [sub("a", used: 10), sub("none", used: nil), sub("b", used: 90), sub("c", used: 50), sub("d", used: 70)]
        guard case .quota(let shown) = WidgetTimeline.entries(cached: cached(subs), error: nil, start: start, minutes: 1)[0].1
        else { return XCTFail() }
        XCTAssertEqual(shown.map(\.id), ["b", "d", "c"])
        guard case .quota(let few) = WidgetTimeline.entries(cached: cached([sub("none", used: nil), sub("a", used: 10)]),
                                                            error: nil, start: start, minutes: 1)[0].1
        else { return XCTFail() }
        XCTAssertEqual(few.map(\.id), ["a", "none"])
    }

    /// 按各窗口中最低的剩余排序：5 小时剩 80%、周限剩 3% 的订阅应排第一。
    func testLowestUsesLowestWindow() {
        func sub(_ id: String, _ used: [Double]) -> Subscription {
            Subscription(id: id, name: id, source: "official", updatedAt: 0,
                         windows: used.map { QuotaWindow(label: "w", usedPercent: $0) })
        }
        let subs = [sub("a", [50]), sub("b", [40]), sub("c", [30]), sub("claude", [20, 97])]
        XCTAssertEqual(WidgetTimeline.lowest(subs).map(\.id), ["claude", "a", "b"])
        XCTAssertEqual(WidgetTimeline.barWindow(sub("claude", [20, 97]))?.usedPercent, 97)
        XCTAssertEqual(WidgetTimeline.barWindow(sub("a", [50]))?.usedPercent, 50)
        XCTAssertNil(WidgetTimeline.barWindow(sub("none", [])))
    }

    /// StandBy 白天会去掉小组件背景、铺黑底：全彩时便签纸由小组件自己画；夜间单色不画，免得刺眼。
    func testWidgetDrawsOwnPaperWhenBackgroundRemoved() {
        XCTAssertTrue(WidgetTimeline.drawsOwnPaper(showsBackground: false, vibrant: false))
        XCTAssertFalse(WidgetTimeline.drawsOwnPaper(showsBackground: true, vibrant: false))
        XCTAssertFalse(WidgetTimeline.drawsOwnPaper(showsBackground: false, vibrant: true))
    }

    /// 大尺寸（长条半屏）一次显示更多额度。
    func testQuotaCountForLargerWidgets() {
        let subs = (0..<8).map { sub("s\($0)", used: Double($0 * 10)) }
        guard case .quota(let shown) = WidgetTimeline.entries(cached: cached(subs), error: nil, start: start,
                                                              minutes: 1, quotaCount: 6)[0].1
        else { return XCTFail() }
        XCTAssertEqual(shown.map(\.id), ["s7", "s6", "s5", "s4", "s3", "s2"])
    }

    func testWidgetNoteChromeIsSmall() {
        // StandBy 半屏 k≈3：抬头 24pt（高度按设备 29:12），底部小字 21pt
        let c = WidgetTimeline.noteChrome(k: 3)
        XCTAssertEqual(c.header, 24)
        XCTAssertEqual(c.headerHeight, 58)
        XCTAssertEqual(c.meta, 21)
    }
}
