import UIKit

/// App 图标颜色：便签的四组配色。黄色是主图标（iconName = nil），其余是备用图标。
enum AppIconChoice: Int, CaseIterable, Identifiable {
    case yellow, green, pink, blue

    var id: Int { rawValue }
    var title: String { ["黄", "绿", "粉", "蓝"][rawValue] }
    var paperHex: UInt32 { Palette.paperHex(rawValue) }
    var headerHex: UInt32 { Palette.paperHeaderHex(rawValue) }
    /// 与资源目录里 AppIcon-* 图标集同名。
    var iconName: String? { self == .yellow ? nil : "AppIcon-" + ["Green", "Pink", "Blue"][rawValue - 1] }

    init(iconName: String?) {
        self = Self.allCases.first { $0.iconName == iconName } ?? .yellow
    }

    @MainActor static var current: AppIconChoice { AppIconChoice(iconName: UIApplication.shared.alternateIconName) }

    @MainActor func apply() async throws {
        guard UIApplication.shared.supportsAlternateIcons,
              UIApplication.shared.alternateIconName != iconName else { return }
        try await UIApplication.shared.setAlternateIconName(iconName)
    }
}
