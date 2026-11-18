import SwiftUI
import WidgetKit

/// 全彩模式按 Palette 着色；StandBy 夜间等 vibrant 模式只用单色，告警靠 ⚠︎ 与粗体。
/// 字号以小号小组件为基准，按实际尺寸放大（大号 / 竖长特大号用于 Duo 展开后的长条半屏）。
struct WidgetCardView: View {
    let entry: BoardEntry
    @Environment(\.widgetRenderingMode) private var mode
    @Environment(\.showsWidgetContainerBackground) private var showsBackground
    @Environment(\.widgetContentMargins) private var margins

    private var vibrant: Bool { mode != .fullColor }

    var body: some View {
        GeometryReader { geo in
            let k = min(3, max(1, min(geo.size.width, geo.size.height) / 130))
            // 每种卡片各自一个身份、不做过渡：额度行不会渐变 / 叠到便签上。
            content(k).frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
                .id(cardID).transition(.identity)
        }
        .containerBackground(for: .widget) {
            if case .note(_, let paper, _) = entry.card { Palette.paper(paper) } else { Palette.panel }
        }
    }

    private var cardID: String {
        switch entry.card {
        case .quota: "quota"
        case .note(let note, _, _): "note-" + note.id
        case .message: "message"
        }
    }

    @ViewBuilder
    private func content(_ k: CGFloat) -> some View {
        switch entry.card {
        case .quota(let subs): quota(subs, k)
        case .note(let note, let paper, let count): noteView(note, paper: paper, count: count, k)
        case .message(let text): message(text, k)
        }
    }

    private func quota(_ subs: [Subscription], _ k: CGFloat) -> some View {
        let now = Int(entry.date.timeIntervalSince1970)
        return VStack(alignment: .leading, spacing: 6 * k) {
            if subs.isEmpty {
                Spacer()
                Text("暂无订阅").font(.system(size: 17 * k, weight: .semibold, design: .rounded)).foregroundStyle(.secondary)
                Spacer()
            }
            ForEach(Array(subs.enumerated()), id: \.offset) { i, sub in
                if i > 0 { Spacer(minLength: 0) }
                row(sub, color: i, now: now, k)
            }
            if let stale = entry.stale {
                Text(stale).font(.system(size: 11 * k, weight: .semibold, design: .rounded))
                    .foregroundStyle(vibrant ? Color.secondary : Palette.muted).lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func row(_ sub: Subscription, color: Int, now: Int, _ k: CGFloat) -> some View {
        let remaining = DisplayModel.remaining(sub.windows.first)
        let level = DisplayModel.quotaLevel(remaining)
        let bar = DisplayModel.remaining(WidgetTimeline.barWindow(sub))
        let barLevel = DisplayModel.quotaLevel(bar)
        let alert = level == .low || level == .critical
        let dim = sub.windows.first?.resetAt.map { now >= $0 } ?? false // 窗口已重置，数值作废
        return VStack(alignment: .leading, spacing: 2 * k) {
            HStack(alignment: .firstTextBaseline) {
                Text(sub.name).font(.system(size: 14 * k, weight: .semibold, design: .rounded))
                    .foregroundStyle(vibrant ? Color.secondary : Palette.card(color)).lineLimit(1)
                Spacer(minLength: 4)
                Text((vibrant && alert ? "⚠︎" : "") + (remaining.map { "\($0)%" } ?? "--"))
                    .font(.system(size: 26 * k, weight: alert ? .heavy : .bold, design: .rounded)).monospacedDigit()
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
            .frame(height: 4 * k)
        }
    }

    /// 照设备便签页：加深色抬头“便签 · i / n”、文楷常规正文、底部浅色小字。
    /// 有系统背景时铺满整个小组件；StandBy 白天去掉背景时自己画圆角便签；夜间单色模式只留文字。
    private func noteView(_ note: Note, paper: Int, count: Int, _ k: CGFloat) -> some View {
        let now = Int(entry.date.timeIntervalSince1970)
        let ownPaper = WidgetTimeline.drawsOwnPaper(showsBackground: showsBackground, vibrant: vibrant)
        let pad = 12 * k
        let card = VStack(alignment: .leading, spacing: 0) {
            Text(Format.noteHeader(index: paper, count: count))
                .font(.system(size: 12 * k, weight: .medium, design: .rounded)).lineLimit(1)
                .padding(.horizontal, pad)
                .frame(maxWidth: .infinity, minHeight: 26 * k, maxHeight: 26 * k, alignment: .leading)
                .background(vibrant ? AnyShapeStyle(Color.primary.opacity(0.15)) : AnyShapeStyle(Palette.paperHeader(paper)))
            VStack(alignment: .leading, spacing: 6 * k) {
                Text(note.text).font(NoteFont.of(size: 22 * k))
                    .minimumScaleFactor(0.5).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                Text(Format.noteMeta(note, now: now)).font(.system(size: 11 * k, design: .rounded)).lineLimit(1)
                    .foregroundStyle(vibrant ? AnyShapeStyle(.secondary) : AnyShapeStyle(Palette.noteMuted))
            }
            .padding(pad)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(ownPaper ? Palette.paper(paper) : .clear)
        }
        .foregroundStyle(vibrant ? Color.primary : Palette.noteText)
        return Group {
            if ownPaper {
                card.clipShape(RoundedRectangle(cornerRadius: 18 * k))
            } else {
                card.padding(EdgeInsets(top: -margins.top, leading: -margins.leading,
                                        bottom: -margins.bottom, trailing: -margins.trailing))
            }
        }
    }

    private func message(_ text: String, _ k: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 8 * k) {
            Image(systemName: "note.text").font(.system(size: 28 * k, weight: .semibold))
                .foregroundStyle(vibrant ? Color.primary : Palette.card(2))
            Spacer(minLength: 0)
            Text("StandIt").font(.system(size: 13 * k, weight: .semibold, design: .rounded)).foregroundStyle(.secondary)
            Text(text).font(.system(size: 18 * k, weight: .bold, design: .rounded))
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
                                            dueAt: Int(Date().timeIntervalSince1970) + 1500), paper: 0, count: 2))
}

#Preview("便签 · 大号", as: .systemLarge) {
    StandItWidget()
} timeline: {
    BoardEntry(date: .now, card: .note(Note(text: "周五下午三点交周报，记得附上额度截图。"), paper: 1, count: 2))
}

#Preview("提示", as: .systemSmall) {
    StandItWidget()
} timeline: {
    BoardEntry(date: .now, card: .message("打开 StandIt 设置接入点"))
}
