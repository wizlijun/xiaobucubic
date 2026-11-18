import Foundation

// 与 apps/xiaobucubic/package/display_model.lua 同一套规则：同样的接口文档、同样的显示结果。

struct QuotaWindow: Codable, Equatable {
    var label: String
    var usedPercent: Double?
    var resetAt: Int?
    var totalBytes: Int?
    var usedBytes: Int?
    var remainingBytes: Int?
}

struct Subscription: Codable, Equatable {
    var id: String
    var name: String
    var source: String
    var updatedAt: Int?
    var windows: [QuotaWindow]
}

struct Note: Codable, Equatable {
    var id: String = ""
    var title: String = "提醒"
    var text: String
    var priority: String = "normal"
    var dueAt: Int?
    var expiresAt: Int?
    var isBot: Bool = false
}

struct Weather: Codable, Equatable {
    var city: String = ""
    var condition: String
    var isDay: Bool?
    var temperatureC: Double?
    var lowC: Double?
    var highC: Double?
    var humidityPercent: Double?
    var pressureHpa: Double?
    var updatedAt: Int?
}

struct DisplaySnapshot: Codable, Equatable {
    var generatedAt: Int
    var staleAfter: Int
    var demo: Bool
    var subscriptions: [Subscription]
    var messages: [Note]
    var weather: Weather?
}

enum QuotaLevel: Equatable { case normal, low, critical, unknown }
enum WindowState: Equatable { case ok, stale, expired, unknown }
enum DisplayError: Error, Equatable { case unsupportedVersion, missingTime, badFormat }

enum DisplayModel {
    private static let maxEpoch = 4_102_444_800.0
    private static let maxSafeInt = 9_007_199_254_740_991.0
    private static let sources: Set<String> = ["official", "manual", "estimated", "unknown"]

    static func normalize(_ data: Data) throws -> DisplaySnapshot {
        guard let doc = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            throw DisplayError.badFormat
        }
        guard intValue(doc["schema_version"]) == 1 else { throw DisplayError.unsupportedVersion }
        guard let generatedAt = epoch(doc["generated_at"]) else { throw DisplayError.missingTime }
        guard let rawSubs = doc["subscriptions"] as? [Any], let rawMessages = doc["messages"] as? [Any] else {
            throw DisplayError.badFormat
        }

        var seen = Set<String>()
        var subscriptions: [Subscription] = []
        for case let p as [String: Any] in rawSubs {
            guard let id = p["id"] as? String, !id.isEmpty, !seen.contains(id) else { continue }
            seen.insert(id)
            var windows: [QuotaWindow] = []
            for case let w as [String: Any] in (p["windows"] as? [Any]) ?? [] where windows.count < 2 {
                var window = QuotaWindow(label: text(w["label"], fallback: "用量", max: 16),
                                         usedPercent: number(w["used_percent"], 0, 1000),
                                         resetAt: epoch(w["reset_at"]))
                if let total = number(w["total_bytes"], 1, maxSafeInt), let used = number(w["used_bytes"], 0, maxSafeInt),
                   total.rounded() == total, used.rounded() == used {
                    window.totalBytes = Int(total)
                    window.usedBytes = Int(used)
                    window.remainingBytes = max(0, Int(total) - Int(used))
                    window.usedPercent = used / total * 100
                }
                windows.append(window)
            }
            let source = p["source"] as? String ?? ""
            subscriptions.append(Subscription(id: text(id, max: 64), name: text(p["name"], fallback: id, max: 40),
                                              source: sources.contains(source) ? source : "unknown",
                                              updatedAt: epoch(p["updated_at"]), windows: windows))
        }

        var messages: [Note] = []
        for case let r as [String: Any] in rawMessages where messages.count < 12 {
            guard r["text"] is String else { continue }
            let content = text(r["text"], max: 180, multiline: true)
            guard content.contains(where: { !$0.isWhitespace }) else { continue }
            messages.append(Note(id: text(r["id"], max: 80), title: text(r["title"], fallback: "提醒", max: 40),
                                 text: content, priority: (r["priority"] as? String) == "high" ? "high" : "normal",
                                 dueAt: epoch(r["due_at"]), expiresAt: epoch(r["expires_at"]),
                                 isBot: (r["sender"] as? String) == "bot"))
        }

        var weather: Weather?
        if let w = doc["weather"] as? [String: Any] {
            weather = Weather(city: text(w["city"], max: 30), condition: text(w["condition"], max: 30),
                              isDay: boolValue(w["is_day"]),
                              temperatureC: number(w["temperature_c"], -100, 100),
                              lowC: number(w["low_c"], -100, 100), highC: number(w["high_c"], -100, 100),
                              humidityPercent: number(w["humidity_percent"], 0, 100),
                              pressureHpa: number(w["pressure_hpa"], 0, 2000), updatedAt: epoch(w["updated_at"]))
        }

        let staleAfter = number(doc["stale_after_seconds"], 30, 86400).map { Int($0) } ?? 900
        return DisplaySnapshot(generatedAt: generatedAt, staleAfter: staleAfter, demo: boolValue(doc["demo"]) == true,
                               subscriptions: subscriptions, messages: messages, weather: weather)
    }

    static func remaining(_ window: QuotaWindow?) -> Int? {
        guard let used = window?.usedPercent else { return nil }
        return Int(max(0, 100 - used).rounded(.down))
    }

    static func quotaLevel(_ remaining: Int?) -> QuotaLevel {
        guard let remaining else { return .unknown }
        if remaining < 5 { return .critical }
        if remaining < 20 { return .low }
        return .normal
    }

    static func isStale(_ updatedAt: Int?, now: Int, ttl: Int) -> Bool {
        guard let updatedAt else { return true }
        return now - updatedAt > ttl || updatedAt - now > 300
    }

    static func windowState(_ sub: Subscription, _ window: QuotaWindow?, now: Int, ttl: Int) -> WindowState {
        guard let window, window.usedPercent != nil else { return .unknown }
        if isStale(sub.updatedAt, now: now, ttl: ttl) { return .stale }
        if let reset = window.resetAt, now >= reset { return .expired }
        return .ok
    }

    /// 已过期（expires_at <= now）的便签不显示。
    static func activeNotes(_ snapshot: DisplaySnapshot, now: Int) -> [Note] {
        snapshot.messages.filter { note in note.expiresAt.map { $0 > now } ?? true }
    }

    static func weatherAsset(_ weather: Weather?) -> String? {
        guard let weather else { return nil }
        let c = weather.condition.lowercased()
        func has(_ keys: String...) -> Bool { keys.contains { c.contains($0) } }
        if has("雨", "冰雹", "rain", "drizzle", "thunder", "hail") { return "rain" }
        if has("雪", "snow", "sleet") { return "snow" }
        if has("雾", "霧", "霾", "fog", "mist", "haze") { return "overcast" }
        if has("阴", "陰", "overcast") { return "overcast" }
        if has("云", "雲", "cloud") { return "partly_cloudy" }
        if has("晴", "clear", "sun") {
            return weather.isDay == false || has("夜", "night") ? "clear_night" : "sunny"
        }
        return "overcast"
    }

    // MARK: 字段清洗

    private static func isBool(_ v: Any?) -> Bool {
        guard let n = v as? NSNumber else { return false }
        return CFGetTypeID(n) == CFBooleanGetTypeID()
    }

    private static func boolValue(_ v: Any?) -> Bool? { isBool(v) ? (v as? Bool) : nil }

    private static func number(_ v: Any?, _ lo: Double, _ hi: Double) -> Double? {
        guard !isBool(v), let n = v as? NSNumber else { return nil }
        let d = n.doubleValue
        guard d.isFinite, d >= lo, d <= hi else { return nil }
        return d
    }

    private static func intValue(_ v: Any?) -> Int? {
        guard let d = number(v, -maxSafeInt, maxSafeInt), d.rounded() == d else { return nil }
        return Int(d)
    }

    private static func epoch(_ v: Any?) -> Int? {
        number(v, 1, maxEpoch).map { Int($0.rounded(.down)) }
    }

    /// 截断到 max 个字符，去掉控制字符；multiline 时统一换行、制表符换成 4 个空格。
    private static func text(_ v: Any?, fallback: String = "", max: Int, multiline: Bool = false) -> String {
        guard var s = v as? String else { return fallback }
        if multiline {
            s = s.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
                .replacingOccurrences(of: "\t", with: "    ")
        }
        var out = ""
        var count = 0
        for ch in s where count < max {
            let isControl = ch.unicodeScalars.allSatisfy { $0.value < 32 || $0.value == 127 }
            if isControl && !(multiline && ch == "\n") { continue }
            out.append(ch)
            count += 1
        }
        return out
    }
}

enum Format {
    static func bytes(_ n: Int?) -> String {
        guard let n, n >= 0 else { return "--" }
        let units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
        var value = Double(n)
        var unit = 0
        while value >= 1024, unit < units.count - 1 { value /= 1024; unit += 1 }
        let floored = (value * 10).rounded(.down) / 10
        let digits = floored.truncatingRemainder(dividingBy: 1) == 0 ? "%.0f" : "%.1f"
        return String(format: digits, floored) + units[unit]
    }

    /// 与设备一致：当天只显示时间，本周（周一至周日）显示“周X”，否则显示日期，跨年带年份。
    static func resetDate(_ ts: Int?, now: Int?, offsetMinutes: Int = 480) -> String {
        guard let ts, ts >= 1, ts <= 4_102_444_800 else { return "" }
        let offset = offsetMinutes * 60
        let local = ts + offset
        let day = floorDiv(local, 86400)
        let hour = (local - day * 86400) / 3600
        let minute = (local % 3600 + 3600) % 3600 / 60
        let today = now.map { floorDiv($0 + offset, 86400) }
        var prefix: String
        if let today, day == today {
            prefix = ""
        } else if let today, day >= today - mod(today + 3, 7), day < today - mod(today + 3, 7) + 7 {
            prefix = "周" + ["一", "二", "三", "四", "五", "六", "日"][mod(day + 3, 7)]
        } else {
            let (y, m, d) = civil(day)
            let currentYear = today.map { civil($0).0 }
            prefix = (currentYear != nil && currentYear != y ? "\(y)/" : "") + String(format: "%02d/%02d ", m, d)
        }
        return prefix + String(format: "%02d:%02d重置", hour, minute)
    }

    /// 固定时区（默认 UTC+8）的 HH:MM。
    static func clock(_ ts: Int, offsetMinutes: Int = 480) -> String {
        let seconds = mod(ts + offsetMinutes * 60, 86400)
        return String(format: "%02d:%02d", seconds / 3600, seconds % 3600 / 60)
    }

    static func due(_ dueAt: Int?, now: Int) -> String? {
        guard let dueAt else { return nil }
        let left = dueAt - now
        if left <= 0 { return "已到期" }
        if left < 60 { return "1分钟内到期" }
        if left < 3600 { return "\(left / 60)分钟后到期" }
        if left < 86400 { return "\(left / 3600)小时后到期" }
        return "\(left / 86400)天后到期"
    }

    static func windowLabel(_ window: QuotaWindow?) -> String {
        guard let window else { return "暂无用量" }
        return window.label == "7天" ? "周限" : window.label
    }

    private static func floorDiv(_ a: Int, _ b: Int) -> Int { Int((Double(a) / Double(b)).rounded(.down)) }
    private static func mod(_ a: Int, _ b: Int) -> Int { (a % b + b) % b }

    /// Unix 日数 → 公历年月日（Howard Hinnant 算法）。
    private static func civil(_ day: Int) -> (Int, Int, Int) {
        let z = day + 719_468
        let era = floorDiv(z, 146_097)
        let doe = z - era * 146_097
        let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365
        var year = yoe + era * 400
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
        let mp = (5 * doy + 2) / 153
        let date = doy - (153 * mp + 2) / 5 + 1
        let month = mp < 10 ? mp + 3 : mp - 9
        if month <= 2 { year += 1 }
        return (year, month, date)
    }
}
