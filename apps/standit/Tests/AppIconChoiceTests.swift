import XCTest
@testable import StandIt

/// 图标颜色 = 便签的四组配色；黄色是主图标，其余三种是备用图标。
final class AppIconChoiceTests: XCTestCase {
    func testChoicesFollowNotePalette() {
        XCTAssertEqual(AppIconChoice.allCases, [.yellow, .green, .pink, .blue])
        for (i, choice) in AppIconChoice.allCases.enumerated() {
            XCTAssertEqual(choice.paperHex, Palette.paperHex(i))
            XCTAssertEqual(choice.headerHex, Palette.paperHeaderHex(i))
        }
        XCTAssertEqual(AppIconChoice.allCases.map(\.title), ["黄", "绿", "粉", "蓝"])
    }

    func testIconNamesRoundTrip() {
        XCTAssertNil(AppIconChoice.yellow.iconName)
        XCTAssertEqual(AppIconChoice.allCases.compactMap(\.iconName), ["AppIcon-Green", "AppIcon-Pink", "AppIcon-Blue"])
        for choice in AppIconChoice.allCases { XCTAssertEqual(AppIconChoice(iconName: choice.iconName), choice) }
        XCTAssertEqual(AppIconChoice(iconName: "unknown"), .yellow)
    }

    /// 备用图标必须编进 App 的 Info.plist，否则 setAlternateIconName 会失败。
    func testAlternateIconsAreBundled() {
        let icons = Bundle.main.object(forInfoDictionaryKey: "CFBundleIcons") as? [String: Any]
        let alternates = icons?["CFBundleAlternateIcons"] as? [String: Any] ?? [:]
        XCTAssertEqual(Set(alternates.keys), Set(AppIconChoice.allCases.compactMap(\.iconName)))
    }
}
