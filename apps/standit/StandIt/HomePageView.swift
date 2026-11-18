import SwiftUI

/// 首页，照搬设备 app_ui.c 的 subscriptions()：天气图铺满做背景，顶部一行天气，
/// 下方半透明额度条（整卡宽度的进度底色 + 底部次窗口细条）。
/// 坐标沿用设备 320 × 240 设计单位：u = 按短的一边缩放；更宽或更高的屏幕把多余空间分给列宽和行高。
enum HomeMetrics {
    static func unit(_ size: CGSize) -> CGFloat { max(0.5, min(size.width / 320, size.height / 240)) }
}

/// 背景：天气图 + 轻微压暗；没有天气图时为纯底色。
struct HomeBackground: View {
    let weather: Weather?

    var body: some View {
        // 图片放在 overlay 里：scaledToFill 不会把外层撑大（否则整页会偏移、被裁）。
        Palette.background
            .overlay {
                if let asset = DisplayModel.weatherAsset(weather) {
                    Image("weather_\(asset)").resizable().scaledToFill()
                    Palette.background.opacity(40.0 / 255)
                }
            }
            .clipped()
    }
}

struct HomePage: View {
    let snapshot: DisplaySnapshot
    let page: Int
    let now: Int
    /// 半折叠时天气在另一半，额度条从顶部开始。
    var showsWeather = true

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            let u = HomeMetrics.unit(size)
            let xs = size.width / 320
            let translucent = DisplayModel.weatherAsset(snapshot.weather) != nil
            ZStack(alignment: .topLeading) {
                if showsWeather {
                    HomeWeatherLine(weather: HomeWeather.make(snapshot.weather, now: now, ttl: snapshot.staleAfter), u: u, xs: xs)
                }
                let pages = max(1, (snapshot.subscriptions.count + HomeLayout.perPage - 1) / HomeLayout.perPage)
                if pages > 1 {
                    Text("\(page % pages + 1)/\(pages)").font(.system(size: 9 * u)).foregroundStyle(Palette.muted)
                        .frame(width: 34 * xs, alignment: .trailing).offset(x: 211 * xs, y: 23 * u)
                }
                if snapshot.subscriptions.isEmpty {
                    VStack(alignment: .leading, spacing: 10 * u) {
                        Text("等待额度数据").foregroundStyle(Palette.text)
                        Text("接口接通后，这里显示服务端提供的剩余额度。").foregroundStyle(Palette.muted)
                    }
                    .font(.system(size: 12 * u)).padding(.horizontal, 18 * xs).offset(y: 113 * u)
                } else {
                    rows(size: size, u: u, translucent: translucent)
                }
            }
            .frame(width: size.width, height: size.height, alignment: .topLeading)
        }
    }

    private func rows(size: CGSize, u: CGFloat, translucent: Bool) -> some View {
        let first = (page % max(1, (snapshot.subscriptions.count + HomeLayout.perPage - 1) / HomeLayout.perPage)) * HomeLayout.perPage
        let visible = Array(snapshot.subscriptions.indices.dropFirst(first).prefix(HomeLayout.perPage))
        let columns = HomeLayout.columns(visible: visible.count)
        let rowCount = (visible.count + columns - 1) / columns
        let top = (showsWeather ? 72 : 26) * u, gap = 3 * u
        let avail = size.height - top - 8 * u
        let rowH = max(20 * u, min((avail - gap * CGFloat(rowCount - 1)) / CGFloat(rowCount), 52 * u * 1.6))
        let cardW = (size.width - 24 * u - 4 * u * CGFloat(columns - 1)) / CGFloat(columns)
        return ForEach(Array(visible.enumerated()), id: \.offset) { slot, i in
            HomeRowView(row: HomeRow.make(snapshot.subscriptions[i], now: now, ttl: snapshot.staleAfter,
                                          grid: columns > 1, tall: rowH >= 45 * u),
                        accent: Palette.cardHex(i), grid: columns > 1, translucent: translucent,
                        u: u * min(1.6, max(1, rowH / (52 * u))), baseTall: rowH >= 45 * u)
                .frame(width: cardW, height: rowH)
                .offset(x: 12 * u + CGFloat(slot % columns) * (cardW + 4 * u), y: top + CGFloat(slot / columns) * (rowH + gap))
        }
    }
}

/// 顶部天气：左侧温度与温度范围，中间城市、湿度、气压，右侧状态与天气现象。
struct HomeWeatherLine: View {
    let weather: HomeWeather
    let u: CGFloat
    let xs: CGFloat

    var body: some View {
        let medium = Font.system(size: 12 * u)
        ZStack(alignment: .topLeading) {
            Text(weather.temperature).font(.system(size: 26 * u, weight: .medium)).monospacedDigit()
                .foregroundStyle(weather.stale ? Palette.muted : Palette.text).lineLimit(1).minimumScaleFactor(0.5)
                .frame(width: 100 * xs, height: 35 * u, alignment: .leading).offset(x: 12 * xs, y: 12 * u)
            Text(weather.range).font(medium).foregroundStyle(Palette.muted).lineLimit(1)
                .frame(width: 105 * xs, alignment: .leading).offset(x: 12 * xs, y: 51 * u)
            centered(weather.city, y: 10, color: weather.stale ? Palette.muted : Palette.mint, font: medium)
            centered(weather.humidity, y: 30, color: Palette.muted, font: medium)
            centered(weather.pressure, y: 51, color: Palette.muted, font: medium)
            Text(weather.status).font(.system(size: 9 * u)).foregroundStyle(Palette.amber).lineLimit(1)
                .frame(width: 98 * xs, alignment: .trailing).offset(x: 210 * xs, y: 37 * u)
            Text(weather.condition).font(medium).foregroundStyle(Palette.muted).lineLimit(1)
                .frame(width: 98 * xs, alignment: .trailing).offset(x: 210 * xs, y: 51 * u)
        }
    }

    private func centered(_ text: String, y: CGFloat, color: Color, font: Font) -> some View {
        Text(text).font(font).foregroundStyle(color).lineLimit(1).minimumScaleFactor(0.6)
            .frame(width: 89 * xs, alignment: .center).offset(x: 119 * xs, y: y * u)
    }
}

/// 一张额度条。u 为卡内设计单位（行被拉高时随之放大）。
struct HomeRowView: View {
    let row: HomeRow
    let accent: UInt32
    let grid: Bool
    let translucent: Bool
    let u: CGFloat
    let baseTall: Bool

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            let compact = !baseTall || grid
            let x0 = (grid ? 6 : 10) * u
            let hex = Palette.toneHex(row.tone, accent: accent)
            let color = Color(hex: hex)
            ZStack(alignment: .topLeading) {
                Palette.panel.opacity(translucent ? 52.0 / 255 : 1)
                if row.fill > 0 {
                    LinearGradient(colors: [color, Color(hex: Palette.mixHex(Palette.panelHex, hex, 0.16))],
                                   startPoint: .top, endPoint: .bottom)
                        .opacity(row.ok ? 64.0 / 255 : 35.0 / 255)
                        .frame(width: max(1, w * row.fill), height: h)
                }
                HStack(alignment: .firstTextBaseline, spacing: (grid ? 10 : 16) * u) {
                    Text(row.name).foregroundStyle(Palette.text)
                    Spacer(minLength: 0)
                    Text(row.value).foregroundStyle(color).monospacedDigit()
                }
                .font(.system(size: 12 * u)).lineLimit(1)
                .padding(.leading, x0).padding(.trailing, 12 * u).offset(y: (compact ? 2 : 5) * u)
                .frame(width: w, alignment: .leading)
                small(row.detail, color: Palette.muted)
                    .frame(width: w - x0 - 12 * u, alignment: .leading).offset(x: x0, y: (compact ? 21 : 28) * u)
                if let extra = row.extra {
                    small(extra, color: Palette.muted).frame(width: w - x0 - 12 * u, alignment: .leading).offset(x: x0, y: 35 * u)
                }
                if let c = row.companion {
                    let chex = Palette.toneHex(c.tone, accent: accent)
                    let cc = Color(hex: chex)
                    small(c.text, color: cc)
                        .frame(width: grid ? w - 12 * u : 152 * u, alignment: grid ? .leading : .trailing)
                        .offset(x: grid ? x0 : w - 164 * u, y: (grid ? 35 : compact ? 21 : 28) * u)
                    let thick = !grid && baseTall
                    let railH = (thick ? 4 : 2) * u
                    let railW = w - 22 * u
                    ZStack(alignment: .leading) {
                        Capsule().fill(Palette.muted.opacity(24.0 / 255))
                        if c.fill > 0 {
                            Capsule().fill(LinearGradient(colors: [cc, Color(hex: Palette.mixHex(Palette.panelHex, chex, 0.35))],
                                                          startPoint: .top, endPoint: .bottom))
                                .opacity(c.ok ? 112.0 / 255 : 55.0 / 255)
                                .frame(width: max(1, railW * c.fill))
                        }
                    }
                    .frame(width: railW, height: railH)
                    .offset(x: 10 * u, y: h - (thick ? 6 : 3) * u)
                }
            }
            .frame(width: w, height: h, alignment: .topLeading)
            .clipShape(RoundedRectangle(cornerRadius: 7 * u))
        }
    }

    private func small(_ text: String, color: Color) -> some View {
        Text(text).font(.system(size: 9 * u)).foregroundStyle(color).lineLimit(1).truncationMode(.tail)
    }
}
