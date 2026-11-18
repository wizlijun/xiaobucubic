import SwiftUI

/// 一页额度卡片，按 BoardLayout.grid 排列。
struct QuotaGrid: View {
    let subscriptions: [Subscription]
    let page: Int
    let snapshot: DisplaySnapshot
    let now: Int

    var body: some View {
        GeometryReader { geo in
            let spacing = max(8, min(geo.size.width, geo.size.height) * 0.025)
            let g = BoardLayout.grid(count: subscriptions.count, in: geo.size)
            let first = page * g.perPage
            let visible = Array(subscriptions.indices.dropFirst(first).prefix(g.perPage))
            let cardW = (geo.size.width - spacing * CGFloat(g.columns - 1)) / CGFloat(g.columns)
            let cardH = (geo.size.height - spacing * CGFloat(g.rows - 1)) / CGFloat(g.rows)
            if visible.isEmpty {
                EmptyCard().frame(width: geo.size.width, height: geo.size.height)
            } else {
                VStack(alignment: .leading, spacing: spacing) {
                    ForEach(0..<g.rows, id: \.self) { row in
                        HStack(spacing: spacing) {
                            ForEach(0..<g.columns, id: \.self) { col in
                                let slot = row * g.columns + col
                                if slot < visible.count {
                                    let i = visible[slot]
                                    QuotaCard(sub: subscriptions[i], colorIndex: i, ttl: snapshot.staleAfter, now: now)
                                        .frame(width: cardW, height: cardH)
                                } else {
                                    Color.clear.frame(width: cardW, height: cardH)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

struct QuotaCard: View {
    let sub: Subscription
    let colorIndex: Int
    let ttl: Int
    let now: Int

    var body: some View {
        GeometryReader { geo in
            let s = min(geo.size.width, geo.size.height * 1.3)
            let primary = sub.windows.first
            let secondary = sub.windows.count > 1 ? sub.windows[1] : nil
            let remaining = DisplayModel.remaining(primary)
            let state = DisplayModel.windowState(sub, primary, now: now, ttl: ttl)
            let accent = Palette.card(colorIndex)
            let pad = s * 0.06
            VStack(alignment: .leading, spacing: s * 0.02) {
                HStack(alignment: .firstTextBaseline, spacing: s * 0.03) {
                    Text(sub.name).font(.system(size: max(14, s * 0.085), weight: .semibold, design: .rounded))
                        .foregroundStyle(accent).lineLimit(1)
                    Spacer(minLength: 0)
                    if let badge = badge(state) {
                        Text(badge).font(.system(size: s * 0.055, weight: .semibold, design: .rounded))
                            .foregroundStyle(Palette.warning)
                    }
                }
                Spacer(minLength: 0)
                Text(remaining.map { "\($0)%" } ?? "--")
                    .font(.system(size: s * 0.22, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(state == .stale || state == .expired ? Palette.muted
                                     : Palette.level(DisplayModel.quotaLevel(remaining)) ?? Palette.text)
                    .lineLimit(1).minimumScaleFactor(0.4)
                Text(detail(primary)).font(.system(size: max(11, s * 0.055), design: .rounded))
                    .foregroundStyle(Palette.muted).lineLimit(1).minimumScaleFactor(0.6)
                if let secondary {
                    SecondaryBar(window: secondary, accent: accent, size: s)
                        .padding(.top, s * 0.02)
                }
            }
            .padding(pad)
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
            .background(alignment: .leading) {
                RoundedRectangle(cornerRadius: s * 0.06).fill(Palette.panel)
                    .overlay(alignment: .leading) {
                        Rectangle().fill(accent).frame(width: max(3, s * 0.018))
                    }
                    .clipShape(RoundedRectangle(cornerRadius: s * 0.06))
            }
        }
    }

    private func badge(_ state: WindowState) -> String? {
        switch state {
        case .stale: return "过期"
        case .expired: return "已重置"
        default:
            switch sub.source {
            case "estimated": return "估算"
            case "manual": return "手动"
            default: return nil
            }
        }
    }

    private func detail(_ w: QuotaWindow?) -> String {
        guard let w else { return "暂无用量" }
        var parts = [Format.windowLabel(w)]
        if let total = w.totalBytes {
            parts.append("剩 \(Format.bytes(w.remainingBytes)) / \(Format.bytes(total))")
        }
        let reset = Format.resetDate(w.resetAt, now: now)
        if !reset.isEmpty { parts.append(reset) }
        return parts.joined(separator: " · ")
    }
}

private struct SecondaryBar: View {
    let window: QuotaWindow
    let accent: Color
    let size: CGFloat

    var body: some View {
        let remaining = DisplayModel.remaining(window)
        HStack(spacing: size * 0.03) {
            Text(Format.windowLabel(window)).font(.system(size: max(10, size * 0.05), design: .rounded))
                .foregroundStyle(Palette.muted).lineLimit(1).fixedSize()
            GeometryReader { bar in
                ZStack(alignment: .leading) {
                    Capsule().fill(Palette.background)
                    Capsule().fill(Palette.level(DisplayModel.quotaLevel(remaining)) ?? accent)
                        .frame(width: bar.size.width * CGFloat(remaining ?? 0) / 100)
                }
            }
            .frame(height: max(4, size * 0.025))
            Text(remaining.map { "\($0)%" } ?? "--").font(.system(size: max(10, size * 0.05), weight: .semibold, design: .rounded))
                .monospacedDigit().foregroundStyle(Palette.text).lineLimit(1).fixedSize()
        }
    }
}

private struct EmptyCard: View {
    var body: some View {
        RoundedRectangle(cornerRadius: 16).fill(Palette.panel)
            .overlay(Text("暂无订阅").font(.system(.title2, design: .rounded)).foregroundStyle(Palette.muted))
    }
}
