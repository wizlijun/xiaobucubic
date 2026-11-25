import Foundation

/// 首页（额度页）的文字与配色，照搬设备 server/wifirouter/main/app_ui.c 的 subscriptions()。
enum Tone: Equatable { case critical, low, accent, muted }

enum HomeLayout {
    /// 与设备一致：每页最多 6 张，始终单列显示。
    static let perPage = 6
    static func columns(visible: Int) -> Int { 1 }
}

struct HomeRow: Equatable {
    struct Companion: Equatable {
        var text: String
        var tone: Tone
        var fill: Double
        var ok: Bool
    }

    var name: String
    /// 右上角数值：剩余百分比；非网格且有流量余额时显示“剩余/总量”。
    var value: String
    var tone: Tone
    /// 背景进度条宽度（剩余比例）。
    var fill: Double
    /// 状态正常时进度色更实。
    var ok: Bool
    var detail: String
    /// 网格模式下有余额又没有次窗口时，第三行显示的说明。
    var extra: String?
    var companion: Companion?

    /// grid：两列窄卡片；tall：卡片高度 ≥ 45 个设计单位。
    static func make(_ sub: Subscription, now: Int, ttl: Int, grid: Bool, tall: Bool) -> HomeRow {
        let w = sub.windows.first
        let second = sub.windows.count > 1 ? sub.windows[1] : nil
        let state = DisplayModel.windowState(sub, w, now: now, ttl: ttl)
        let remaining = DisplayModel.remaining(w)
        let percent = remaining.map { "\($0)%" } ?? "--"
        let balance = w?.totalBytes.map { "\(Format.bytes(w?.remainingBytes))/\(Format.bytes($0))" }
        // HP 的说明行是一整句数值 + 建议，不再追加来源。
        let showSource = sub.id != "energy" && ((second == nil && !grid && tall) || sub.source != "official")
        var detail = Format.windowLabel(w)
        if let balance, !balance.isEmpty { detail += " · " + percent }
        else if showSource { detail += " · " + sourceName(sub.source) }
        detail += suffix(state, reset: w?.resetAt, now: now)

        var companion: Companion?
        if let second {
            let s = DisplayModel.windowState(sub, second, now: now, ttl: ttl)
            let r = DisplayModel.remaining(second)
            let label = second.label == "7天" ? "" : Format.windowLabel(second) + " "
            companion = Companion(text: label + (r.map { "\($0)%" } ?? "--") + suffix(s, reset: second.resetAt, now: now),
                                  tone: tone(r, s), fill: Double(r ?? 0) / 100, ok: s == .ok)
        }
        return HomeRow(name: sub.name, value: !grid && balance != nil ? balance! : percent, tone: tone(remaining, state),
                       fill: Double(remaining ?? 0) / 100, ok: state == .ok,
                       detail: grid && balance != nil ? balance! : detail,
                       extra: grid && balance != nil && second == nil ? detail : nil, companion: companion)
    }

    static func tone(_ remaining: Int?, _ state: WindowState) -> Tone {
        guard let remaining else { return .muted }
        if remaining < 5 { return .critical }
        if remaining < 20 { return .low }
        return state == .ok ? .accent : .muted
    }

    private static func suffix(_ state: WindowState, reset: Int?, now: Int) -> String {
        switch state {
        case .stale: return " · 已过期"
        case .expired: return " · 待刷新"
        default:
            let text = Format.resetDate(reset, now: now)
            return text.isEmpty ? "" : " " + text
        }
    }

    private static func sourceName(_ source: String) -> String {
        switch source {
        case "official": "官方"
        case "manual": "手动"
        case "estimated": "估算"
        default: "待接入"
        }
    }
}

/// 首页顶部一行天气，照搬 weather_inline()。
struct HomeWeather: Equatable {
    var temperature: String
    var city: String
    var humidity: String
    var range: String
    var pressure: String
    var condition: String
    var status: String
    var stale: Bool

    static func make(_ w: Weather?, now: Int, ttl: Int) -> HomeWeather {
        guard let w, let t = w.temperatureC else {
            return HomeWeather(temperature: "--°C", city: "天气待同步", humidity: "", range: "", pressure: "",
                               condition: "", status: "", stale: true)
        }
        let stale = DisplayModel.isStale(w.updatedAt, now: now, ttl: ttl)
        return HomeWeather(temperature: num(t) + "°C", city: String(w.city.prefix(7)), humidity: num(w.humidityPercent) + "%",
                           range: "\(num(w.lowC))–\(num(w.highC))°C", pressure: num(w.pressureHpa) + " hPa",
                           condition: w.condition, status: stale ? "已过期" : "", stale: stale)
    }

    private static func num(_ v: Double?) -> String { v.map { String(Int($0.rounded())) } ?? "--" }
}
