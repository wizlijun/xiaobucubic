import SwiftUI
import WidgetKit

/// 全彩模式按 Palette 着色；StandBy 夜间等 vibrant 模式只用单色，告警靠 ⚠︎ 与粗体。
struct WidgetCardView: View {
    let entry: BoardEntry
    @Environment(\.widgetRenderingMode) private var mode
    @Environment(\.showsWidgetContainerBackground) private var showsBackground

    private var vibrant: Bool { mode != .fullColor }

    var body: some View {
        content
            .containerBackground(for: .widget) {
                if case .note(_, let paper) = entry.card { Palette.paper(paper) } else { Palette.panel }
            }
    }

    @ViewBuilder
    private var content: some View {
        switch entry.card {
        case .quota(let subs): quota(subs)
        case .note(let note, let paper): noteView(note, paper: paper)
        case .message(let text): message(text)
        }
    }

    private func quota(_ subs: [Subscription]) -> some View {
        let now = Int(entry.date.timeIntervalSince1970)
        return VStack(alignment: .leading, spacing: 6) {
            if subs.isEmpty {
                Spacer()
                Text("暂无订阅").font(.system(.headline, design: .rounded)).foregroundStyle(.secondary)
                Spacer()
            }
            ForEach(Array(subs.enumerated()), id: \.offset) { i, sub in
                if i > 0 { Spacer(minLength: 0) }
                row(sub, color: i, now: now)
            }
            if let stale = entry.stale {
                Text(stale).font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(vibrant ? Color.secondary : Palette.muted).lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func row(_ sub: Subscription, color: Int, now: Int) -> some View {
        let remaining = DisplayModel.remaining(sub.windows.first)
        let level = DisplayModel.quotaLevel(remaining)
        let bar = DisplayModel.remaining(WidgetTimeline.barWindow(sub))
        let barLevel = DisplayModel.quotaLevel(bar)
        let alert = level == .low || level == .critical
        let dim = sub.windows.first?.resetAt.map { now >= $0 } ?? false // 窗口已重置，数值作废
        return VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline) {
                Text(sub.name).font(.system(size: 14, weight: .semibold, design: .rounded))
                    .foregroundStyle(vibrant ? Color.secondary : Palette.card(color)).lineLimit(1)
                Spacer(minLength: 4)
                Text((vibrant && alert ? "⚠︎" : "") + (remaining.map { "\($0)%" } ?? "--"))
                    .font(.system(size: 26, weight: alert ? .heavy : .bold, design: .rounded)).monospacedDigit()
                    .foregroundStyle(vibrant ? Color.primary : dim ? Palette.muted : Palette.level(level) ?? Palette.text)
                    .lineLimit(1).minimumScaleFactor(0.6)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(vibrant ? Color.primary.opacity(0.2) : Palette.background)
                    Capsule().fill(vibrant ? Color.primary : Palette.level(barLevel) ?? Palette.card(color))
                        .frame(width: geo.size.width * CGFloat(bar ?? 0) / 100)
                }
            }
            .frame(height: 4)
        }
    }

    private func noteView(_ note: Note, paper: Int) -> some View {
        let now = Int(entry.date.timeIntervalSince1970)
        let ink = vibrant ? Color.primary : Palette.widgetNoteInk(showsBackground: showsBackground)
        return VStack(alignment: .leading, spacing: 6) {
            if note.title != "提醒" && !note.title.isEmpty {
                Text(note.title).font(.system(size: 12, weight: .semibold, design: .rounded)).opacity(0.65).lineLimit(1)
            }
            Text(note.text).font(.system(size: 22, weight: .semibold, design: .rounded))
                .minimumScaleFactor(0.5).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            let tags = [note.priority == "high" ? (vibrant ? "⚠︎ 重要" : "● 重要") : nil, Format.due(note.dueAt, now: now)]
                .compactMap { $0 }
            if !tags.isEmpty {
                Text(tags.joined(separator: "  ")).font(.system(size: 11, weight: .bold, design: .rounded))
                    .opacity(0.7).lineLimit(1)
            }
        }
        .foregroundStyle(ink)
        .overlay(alignment: .topTrailing) { // 背景被去掉时用一角便签色标示
            if !showsBackground && !vibrant {
                Circle().fill(Palette.paper(paper)).frame(width: 10, height: 10)
            }
        }
    }

    private func message(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: "note.text").font(.system(size: 28, weight: .semibold))
                .foregroundStyle(vibrant ? Color.primary : Palette.card(2))
            Spacer(minLength: 0)
            Text("StandIt").font(.system(size: 13, weight: .semibold, design: .rounded)).foregroundStyle(.secondary)
            Text(text).font(.system(size: 18, weight: .bold, design: .rounded))
                .foregroundStyle(vibrant ? Color.primary : Palette.text).minimumScaleFactor(0.6)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

#Preview("额度", as: .systemSmall) {
    StandItWidget()
} timeline: {
    let now = Int(Date().timeIntervalSince1970)
    let subs = [("Claude", 62.0), ("Codex", 85.0), ("Grok", 97.0)].map { name, used in
        Subscription(id: name, name: name, source: "official", updatedAt: now,
                     windows: [QuotaWindow(label: "5小时", usedPercent: used)])
    }
    BoardEntry(date: .now, card: .quota(subs))
    BoardEntry(date: .now, card: .quota(subs), stale: "数据时间 18:23")
}

#Preview("便签", as: .systemSmall) {
    StandItWidget()
} timeline: {
    BoardEntry(date: .now, card: .note(Note(title: "出门前", text: "带伞，傍晚有雷阵雨。", priority: "high",
                                            dueAt: Int(Date().timeIntervalSince1970) + 1500), paper: 0))
}

#Preview("提示", as: .systemSmall) {
    StandItWidget()
} timeline: {
    BoardEntry(date: .now, card: .message("打开 StandIt 设置接入点"))
}
