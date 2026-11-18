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
            case .note(let n, _): n.text
            case .message(let m): "msg:" + m
            }
        }
    }

    private var start: Date { Date(timeIntervalSince1970: TimeInterval(t0)) }

    func testRotationOrder() {
        let entries = WidgetTimeline.entries(cached: cached(notes: [Note(text: "a"), Note(text: "b")]), error: nil,
                                             start: start, minutes: 6)
        XCTAssertEqual(kinds(entries), ["q", "a", "q", "b", "q", "a"])
        XCTAssertEqual(entries.map { Int($0.0.timeIntervalSince1970) - t0 }, [0, 60, 120, 180, 240, 300])
    }

    func testExpiredNotesSkipped() {
        let notes = [Note(text: "a", expiresAt: t0 + 180), Note(text: "b")]
        let entries = WidgetTimeline.entries(cached: cached(notes: notes), error: nil, start: start, minutes: 8)
        XCTAssertFalse(kinds(Array(entries.dropFirst(3))).contains("a"))
        XCTAssertEqual(kinds(entries), ["q", "a", "q", "b", "q", "b", "q", "b"])
        let gone = WidgetTimeline.entries(cached: cached(notes: [Note(text: "x", expiresAt: t0)]), error: nil,
                                          start: start, minutes: 4)
        XCTAssertEqual(kinds(gone), ["q", "q", "q", "q"])
    }

    func testNotConfiguredMessage() {
        XCTAssertEqual(kinds(WidgetTimeline.entries(cached: nil, error: .notConfigured, start: start, minutes: 2)),
                       ["msg:打开 StandIt 设置接入点", "msg:打开 StandIt 设置接入点"])
        XCTAssertEqual(kinds(WidgetTimeline.entries(cached: cached(), error: .notConfigured, start: start, minutes: 1)),
                       ["msg:打开 StandIt 设置接入点"])
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
}
