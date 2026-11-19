import SwiftUI
import UIKit

/// 主界面：每 15 秒切页；前台轮询（60 秒 / 失败退避）；进入后台停止。
struct BoardView: View {
    @ObservedObject var store: DisplayStore
    var onSettings: () -> Void
    @Environment(\.scenePhase) private var scenePhase
    @State private var fold: CGRect?
    /// 设置按钮平时隐藏，点屏幕后显示 5 秒。
    @State private var showsSettings = false

    var body: some View {
        // 铺满整屏（分屏时便签纸到屏幕边），文字和额度按安全区内缩。
        GeometryReader { screen in
            TimelineView(.periodic(from: .now, by: 15)) { context in
                BoardContent(cached: store.cached, error: store.error, date: context.date, fold: fold,
                             insets: screen.safeAreaInsets, onSettings: showsSettings ? onSettings : nil)
                    .background(FoldReader(tick: context.date) { if fold != $0 { fold = $0 } })
            }
        }
        .ignoresSafeArea()
        .contentShape(Rectangle())
        .onTapGesture { showsSettings = true }
        .accessibilityAction(named: "设置", onSettings)
        .task(id: showsSettings) {
            guard showsSettings else { return }
            try? await Task.sleep(for: .seconds(5))
            if !Task.isCancelled { showsSettings = false }
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
/// 额度页照搬设备首页（天气图背景 + 顶部天气 + 额度条）；便签页只画便签，两者互斥，切页不做过渡动画。
struct BoardContent: View {
    let cached: CachedSnapshot?
    let error: FetchError?
    let date: Date
    var fold: CGRect? = nil
    /// 整屏中的安全区边距（BoardContent 铺满整屏）。
    var insets: EdgeInsets = EdgeInsets()
    var onSettings: (() -> Void)? = nil
    /// 仅用于截图：固定显示第 N 页。
    var pageOverride: Int? = nil

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            let safe = CGRect(x: insets.leading, y: insets.top,
                              width: max(0, size.width - insets.leading - insets.trailing),
                              height: max(0, size.height - insets.top - insets.bottom))
            let short = min(safe.width, safe.height)
            ZStack(alignment: .topLeading) {
                if let cached {
                    let now = Int(date.timeIntervalSince1970)
                    let snapshot = cached.snapshot
                    let notes = DisplayModel.activeNotes(snapshot, now: now)
                    let tick = pageOverride ?? Int(date.timeIntervalSince1970 / 15)
                    if let (full1, full2) = BoardLayout.halves(size, fold: fold) {
                        // 横屏 / 半折叠：一半轮播额度页，另一半轮播便签；没有便签时另一半放天气。
                        // 便签纸铺满它那一半（到屏幕边）；额度和天气留在安全区内。
                        let first = full1.intersection(safe), second = full2.intersection(safe)
                        let quotaPages = max(1, (snapshot.subscriptions.count + HomeLayout.perPage - 1) / HomeLayout.perPage)
                        page(.quota(index: tick % quotaPages), snapshot, notes: notes, now: now, size: first.size,
                             weather: !notes.isEmpty)
                            .frame(width: first.width, height: first.height).offset(x: first.minX, y: first.minY)
                        if notes.isEmpty {
                            let wu = min(second.width / 320, second.height / 80)
                            ZStack(alignment: .topLeading) {
                                HomeBackground(weather: snapshot.weather)
                                HomeWeatherLine(weather: HomeWeather.make(snapshot.weather, now: now, ttl: snapshot.staleAfter),
                                                u: wu, xs: second.width / 320)
                                    .offset(y: max(0, (second.height - 72 * wu) / 2))
                            }
                            .frame(width: second.width, height: second.height).clipped()
                            .offset(x: second.minX, y: second.minY)
                        } else {
                            let index = tick % notes.count
                            NotePageView(note: notes[index], paper: index, count: notes.count, now: now,
                                         bleed: BoardLayout.safeInsets(of: full2, safe: safe))
                                .frame(width: full2.width, height: full2.height)
                                .id(Page.note(index: index)).transition(.identity)
                                .transaction { $0.animation = nil }
                                .offset(x: full2.minX, y: full2.minY)
                        }
                    } else {
                        let pages = BoardLayout.pages(cardCount: snapshot.subscriptions.count, perPage: HomeLayout.perPage,
                                                      notes: notes.count)
                        page(pages[tick % pages.count], snapshot, notes: notes, now: now, size: safe.size, weather: true)
                            .offset(x: safe.minX, y: safe.minY)
                    }
                    // 分屏时状态字号按半屏算；右上角落在便签纸上时改用便签墨色，免得黄底上的琥珀色看不清
                    let notesHalf = notes.isEmpty ? nil : BoardLayout.halves(size, fold: fold)?.1
                    StatusIndicator(cached: cached, error: error, now: now,
                                    onPaper: notesHalf?.contains(CGPoint(x: safe.maxX - 1, y: safe.minY + 1)) ?? false,
                                    u: HomeMetrics.unit(BoardLayout.halves(size, fold: fold)?.1.intersection(safe).size ?? safe.size),
                                    onSettings: onSettings)
                        .frame(width: safe.maxX, alignment: .trailing).offset(y: safe.minY)
                } else {
                    Palette.background
                    VStack(spacing: short * 0.03) {
                        Text("Stand It").font(.system(size: short * 0.08, weight: .bold, design: .rounded))
                            .foregroundStyle(Palette.text)
                        Text(error?.message ?? "正在连接…").font(.system(size: short * 0.04, design: .rounded))
                            .foregroundStyle(error == nil ? Palette.muted : Palette.warning)
                    }
                    .frame(width: safe.width, height: safe.height).offset(x: safe.minX, y: safe.minY)
                    StatusIndicator(cached: nil, error: error, now: 0, u: HomeMetrics.unit(safe.size), onSettings: onSettings)
                        .frame(width: safe.maxX, alignment: .trailing).offset(y: safe.minY)
                }
            }
            .frame(width: size.width, height: size.height, alignment: .topLeading)
        }
    }

    /// 一页：额度页铺满（含背景）；便签页在纯底色上留边距。用 id 区分页面，避免两页叠在一起过渡。
    @ViewBuilder
    private func page(_ current: Page, _ snapshot: DisplaySnapshot, notes: [Note], now: Int,
                      size: CGSize, weather: Bool) -> some View {
        let short = min(size.width, size.height)
        let pad = max(10, short * 0.03)
        ZStack(alignment: .topLeading) {
            switch current {
            case .quota(let index):
                HomeBackground(weather: snapshot.weather)
                HomePage(snapshot: snapshot, page: index, now: now, showsWeather: weather)
            case .note(let index):
                Palette.background
                NotePageView(note: notes[index], paper: index, count: notes.count, now: now)
                    .padding(.horizontal, pad).padding(.bottom, pad)
                    .padding(.top, max(pad, 22 * HomeMetrics.unit(size)))
            }
        }
        .frame(width: size.width, height: size.height)
        .clipped()
        .id(current)
        .transition(.identity)
        .transaction { $0.animation = nil }
    }
}

/// 右上角状态，照设备 network_indicator：小字，演示 / 错误 / 数据时间，最右是设置按钮。
struct StatusIndicator: View {
    let cached: CachedSnapshot?
    let error: FetchError?
    let now: Int
    /// 叠在便签纸上：琥珀色 / 灰色换成便签墨色。
    var onPaper = false
    let u: CGFloat
    var onSettings: (() -> Void)?

    var body: some View {
        // 设备在右上角先显示连接状态，下一行“演示”；这里同样竖排，避免压到中间的城市名。
        HStack(alignment: .top, spacing: 4 * u) {
            VStack(alignment: .trailing, spacing: 3 * u) {
                ForEach(Self.badges(cached, error: error, now: now), id: \.0) { text, color in
                    Text(text).font(.system(size: 9 * u))
                        .foregroundStyle(onPaper && color != Palette.warning ? Palette.noteMuted : color).lineLimit(1)
                }
            }
            .padding(.top, 5 * u)
            if let onSettings {
                Button(action: onSettings) {
                    Image(systemName: "gearshape").font(.system(size: 10 * u))
                        .foregroundStyle((onPaper ? Palette.noteMuted : Palette.muted).opacity(0.7))
                        .frame(width: max(44, 16 * u), height: max(44, 16 * u))
                }
                .accessibilityLabel("设置")
            }
        }
        .padding(.trailing, 4 * u)
    }

    static func badges(_ cached: CachedSnapshot?, error: FetchError?, now: Int) -> [(String, Color)] {
        var badges: [(String, Color)] = []
        if cached?.snapshot.demo == true { badges.append(("演示", Palette.amber)) }
        if let error { badges.append((error.message, Palette.warning)) }
        if let cached {
            let received = Int(cached.receivedAt.timeIntervalSince1970)
            if error != nil || now - received > cached.snapshot.staleAfter {
                badges.append(("数据时间 \(Format.clock(received))", Palette.muted))
            }
        }
        return badges
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
