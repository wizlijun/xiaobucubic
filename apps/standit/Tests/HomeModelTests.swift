import XCTest
@testable import StandIt

/// 首页文字与配色规则照搬设备 server/wifirouter/main/app_ui.c 的 subscriptions() / weather_inline()。
final class HomeModelTests: XCTestCase {
    private let now = 1_792_664_580 // 2026-10-20 周二 13:43（UTC+8）

    private func sub(_ windows: [QuotaWindow], source: String = "official", updatedAt: Int? = nil) -> Subscription {
        Subscription(id: "c", name: "Claude", source: source, updatedAt: updatedAt ?? now, windows: windows)
    }

    func testSingleWindowRowShowsSourceAndReset() {
        let w = QuotaWindow(label: "5小时", usedPercent: 62, resetAt: now + 3600)
        let row = HomeRow.make(sub([w]), now: now, ttl: 900, grid: false, tall: true)
        XCTAssertEqual(row.name, "Claude")
        XCTAssertEqual(row.value, "38%")
        XCTAssertEqual(row.tone, .accent)
        XCTAssertEqual(row.fill, 0.38, accuracy: 0.001)
        XCTAssertTrue(row.ok)
        XCTAssertEqual(row.detail, "5小时 · 官方 " + Format.resetDate(now + 3600, now: now))
        XCTAssertNil(row.companion)
    }

    func testEnergyRowOmitsSource() {
        let w = QuotaWindow(label: "睡前约34% · 宜放松", usedPercent: 57, resetAt: nil)
        let hp = Subscription(id: "energy", name: "HP", source: "estimated", updatedAt: now, windows: [w])
        XCTAssertEqual(HomeRow.make(hp, now: now, ttl: 900, grid: false, tall: true).detail, "睡前约34% · 宜放松")
    }

    func testCompanionRowDropsOfficialSourceAndWeekLabel() {
        let row = HomeRow.make(sub([QuotaWindow(label: "5小时", usedPercent: 85),
                                    QuotaWindow(label: "7天", usedPercent: 41)]),
                               now: now, ttl: 900, grid: false, tall: true)
        XCTAssertEqual(row.value, "15%")
        XCTAssertEqual(row.tone, .low)
        XCTAssertEqual(row.detail, "5小时")
        XCTAssertEqual(row.companion, HomeRow.Companion(text: "59%", tone: .accent, fill: 0.59, ok: true))
    }

    func testToneThresholdsAndStaleState() {
        let critical = HomeRow.make(sub([QuotaWindow(label: "5小时", usedPercent: 96)]), now: now, ttl: 900, grid: false, tall: true)
        XCTAssertEqual(critical.tone, .critical)
        let stale = HomeRow.make(sub([QuotaWindow(label: "5小时", usedPercent: 10)], updatedAt: now - 1000),
                                 now: now, ttl: 900, grid: false, tall: true)
        XCTAssertEqual(stale.tone, .muted)
        XCTAssertFalse(stale.ok)
        XCTAssertEqual(stale.detail, "5小时 · 官方 · 已过期")
        let empty = HomeRow.make(sub([]), now: now, ttl: 900, grid: false, tall: true)
        XCTAssertEqual(empty.value, "--")
        XCTAssertEqual(empty.tone, .muted)
        XCTAssertEqual(empty.detail, "暂无用量 · 官方")
    }

    func testBalanceShownInsteadOfPercentOutsideGrid() {
        let w = QuotaWindow(label: "月流量", usedPercent: 75, totalBytes: 1 << 30, remainingBytes: 1 << 28)
        let wide = HomeRow.make(sub([w], source: "manual"), now: now, ttl: 900, grid: false, tall: true)
        XCTAssertEqual(wide.value, "256MiB/1GiB")
        XCTAssertEqual(wide.detail, "月流量 · 25%")
        let grid = HomeRow.make(sub([w], source: "manual"), now: now, ttl: 900, grid: true, tall: true)
        XCTAssertEqual(grid.value, "25%")
        XCTAssertEqual(grid.detail, "256MiB/1GiB")
        XCTAssertEqual(grid.extra, "月流量 · 25%")
    }

    func testColumnsAndPaging() {
        XCTAssertEqual(HomeLayout.perPage, 6)
        for visible in 1...6 {
            XCTAssertEqual(HomeLayout.columns(visible: visible), 1)
        }
    }

    func testAccentOrderMatchesDevice() {
        XCTAssertEqual((0..<3).map(Palette.cardHex), [0xFFC078, 0x6DE1C2, 0x83B6FF])
    }

    func testMixAndToneColorsMatchDevice() {
        XCTAssertEqual(Palette.mixHex(0x111C28, 0x6DE1C2, 0.16), 0x203C41)
        XCTAssertEqual(Palette.mixHex(0x000000, 0xFFFFFF, 0.5), 0x808080)
        XCTAssertEqual(Palette.toneHex(.accent, accent: 0x83B6FF), 0x83B6FF)
        XCTAssertEqual(Palette.toneHex(.critical, accent: 0x83B6FF), 0xFF5F6D)
        XCTAssertEqual(Palette.toneHex(.low, accent: 0x83B6FF), 0xFFD166)
        XCTAssertEqual(Palette.toneHex(.muted, accent: 0x83B6FF), 0x8497AC)
    }

    func testWeatherLine() {
        let w = Weather(city: "深圳", condition: "多云", temperatureC: 27.6, lowC: 23, highC: 29,
                        humidityPercent: 68, pressureHpa: 1008, updatedAt: now)
        XCTAssertEqual(HomeWeather.make(w, now: now, ttl: 900),
                       HomeWeather(temperature: "28°C", city: "深圳", humidity: "68%", range: "23–29°C",
                                   pressure: "1008 hPa", condition: "多云", status: "", stale: false))
        let old = HomeWeather.make(w, now: now + 1000, ttl: 900)
        XCTAssertEqual(old.status, "已过期")
        XCTAssertTrue(old.stale)
        XCTAssertEqual(HomeWeather.make(nil, now: now, ttl: 900),
                       HomeWeather(temperature: "--°C", city: "天气待同步", humidity: "", range: "",
                                   pressure: "", condition: "", status: "", stale: true))
    }
}
