import SwiftUI
import UIKit

/// 主界面：每 15 秒切页；前台轮询（60 秒 / 失败退避）；进入后台停止。
struct BoardView: View {
    @ObservedObject var store: DisplayStore
    var onSettings: () -> Void
    @Environment(\.scenePhase) private var scenePhase
    @State private var fold: CGRect?

    var body: some View {
        TimelineView(.periodic(from: .now, by: 15)) { context in
            BoardContent(cached: store.cached, error: store.error, date: context.date, fold: fold,
                         onSettings: onSettings)
                .background(FoldReader(tick: context.date) { if fold != $0 { fold = $0 } })
        }
        .background(Palette.background.ignoresSafeArea())
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await store.refresh()
                try? await Task.sleep(for: .seconds(store.nextDelay))
            }
        }
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
    }
}

/// 纯展示：给定数据、时间、尺寸（来自 GeometryReader）和折痕，画出当前页。可直接用于预览和截图。
struct BoardContent: View {
    let cached: CachedSnapshot?
    let error: FetchError?
    let date: Date
    var fold: CGRect? = nil
    var onSettings: (() -> Void)? = nil
    /// 仅用于截图：固定显示第 N 页。
    var pageOverride: Int? = nil

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            let short = min(size.width, size.height)
            let pad = max(10, short * 0.03)
            let statusH = max(28, short * 0.05)
            ZStack(alignment: .topLeading) {
                Palette.background
                if let cached {
                    if let (first, second) = BoardLayout.split(size, around: fold) {
                        page(cached, in: first.insetBy(dx: pad, dy: pad), statusH: statusH, pad: pad, weather: false)
                        WeatherPanel(weather: cached.snapshot.weather)
                            .frame(width: second.width - pad * 2, height: second.height - pad * 2)
                            .offset(x: second.minX + pad, y: second.minY + pad)
                    } else {
                        page(cached, in: CGRect(origin: .zero, size: size).insetBy(dx: pad, dy: pad),
                             statusH: statusH, pad: pad, weather: true)
                    }
                } else {
                    VStack(spacing: short * 0.03) {
                        Text("StandIt").font(.system(size: short * 0.08, weight: .bold, design: .rounded))
                            .foregroundStyle(Palette.text)
                        Text(error?.message ?? "正在连接…").font(.system(size: short * 0.04, design: .rounded))
                            .foregroundStyle(error == nil ? Palette.muted : Palette.warning)
                    }
                    .frame(width: size.width, height: size.height)
                    statusRow(nil, width: size.width - pad * 2, height: statusH)
                        .offset(x: pad, y: pad)
                }
            }
        }
    }

    @ViewBuilder
    private func page(_ cached: CachedSnapshot, in rect: CGRect, statusH: CGFloat, pad: CGFloat, weather: Bool) -> some View {
        let now = Int(date.timeIntervalSince1970)
        let snapshot = cached.snapshot
        let notes = DisplayModel.activeNotes(snapshot, now: now)
        let main = CGRect(x: rect.minX, y: rect.minY + statusH + pad * 0.6, width: rect.width,
                          height: max(0, rect.height - statusH - pad * 0.6))
        let areas = Self.quotaAreas(main, gap: pad, weather: weather)
        let perPage = BoardLayout.grid(count: snapshot.subscriptions.count, in: areas.grid.size).perPage
        let pages = BoardLayout.pages(cardCount: snapshot.subscriptions.count, perPage: perPage, notes: notes.count)
        let current = pages[(pageOverride ?? Int(date.timeIntervalSince1970 / 15)) % pages.count]

        statusRow(cached, width: rect.width, height: statusH).offset(x: rect.minX, y: rect.minY)
        switch current {
        case .quota(let index):
            if let w = areas.weather {
                WeatherPanel(weather: snapshot.weather).frame(width: w.width, height: w.height).offset(x: w.minX, y: w.minY)
            }
            QuotaGrid(subscriptions: snapshot.subscriptions, page: index, snapshot: snapshot, now: now)
                .frame(width: areas.grid.width, height: areas.grid.height).offset(x: areas.grid.minX, y: areas.grid.minY)
        case .note(let index):
            NotePageView(note: notes[index], paper: index, now: now)
                .frame(width: main.width, height: main.height).offset(x: main.minX, y: main.minY)
        }
    }

    /// 横向：天气在左侧一栏；竖向：天气在顶部。
    static func quotaAreas(_ main: CGRect, gap: CGFloat, weather: Bool) -> (weather: CGRect?, grid: CGRect) {
        guard weather else { return (nil, main) }
        switch BoardLayout.weatherPlacement(main.size) {
        case .leading:
            let w = (main.width * 0.32).rounded()
            return (CGRect(x: main.minX, y: main.minY, width: w, height: main.height),
                    CGRect(x: main.minX + w + gap, y: main.minY, width: main.width - w - gap, height: main.height))
        case .top:
            let h = (main.height * 0.3).rounded()
            return (CGRect(x: main.minX, y: main.minY, width: main.width, height: h),
                    CGRect(x: main.minX, y: main.minY + h + gap, width: main.width, height: main.height - h - gap))
        }
    }

    private func statusRow(_ cached: CachedSnapshot?, width: CGFloat, height: CGFloat) -> some View {
        let now = Int(date.timeIntervalSince1970)
        var badges: [(String, Color)] = []
        if cached?.snapshot.demo == true { badges.append(("演示", Palette.card(2))) }
        if let cached {
            let received = Int(cached.receivedAt.timeIntervalSince1970)
            if let error { badges.append((error.message, Palette.warning)) }
            if error != nil || now - received > cached.snapshot.staleAfter {
                badges.append(("数据时间 \(Format.clock(received))", Palette.muted))
            }
        }
        let font = Font.system(size: height * 0.5, weight: .semibold, design: .rounded)
        return HStack(spacing: height * 0.4) {
            ForEach(badges, id: \.0) { text, color in
                Text(text).font(font).foregroundStyle(color).lineLimit(1)
            }
            Spacer(minLength: 0)
            if let onSettings {
                Button(action: onSettings) {
                    Image(systemName: "gearshape").font(.system(size: height * 0.55))
                        .foregroundStyle(Palette.muted.opacity(0.7))
                        .frame(width: max(44, height), height: max(44, height))
                }
                .accessibilityLabel("设置")
            }
        }
        .frame(width: width, height: height)
    }
}

/// 读取 Duo 半折叠时的折痕区域（iOS 27.1 reservedRegions(kind: .division)），坐标与内容区域一致。
struct FoldReader: UIViewRepresentable {
    var tick: Date
    var onChange: (CGRect?) -> Void

    func makeUIView(context: Context) -> Probe {
        let view = Probe()
        view.isUserInteractionEnabled = false
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ view: Probe, context: Context) {
        view.onChange = onChange
        view.report()
    }

    final class Probe: UIView {
        var onChange: ((CGRect?) -> Void)?
        private var last: CGRect??

        override func layoutSubviews() {
            super.layoutSubviews()
            report()
        }

        func report() {
            var rect: CGRect?
            if #available(iOS 27.1, *) {
                rect = reservedRegions(kind: .division).first(where: \.isActive)?.frame
                    .intersection(bounds).nonEmpty
            }
            guard last != .some(rect) else { return }
            last = .some(rect)
            let callback = onChange
            DispatchQueue.main.async { callback?(rect) }
        }
    }
}

private extension CGRect {
    var nonEmpty: CGRect? { isNull || isEmpty ? nil : self }
}
