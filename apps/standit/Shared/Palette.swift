import SwiftUI

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB, red: Double(hex >> 16 & 0xFF) / 255, green: Double(hex >> 8 & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255, opacity: 1)
    }
}

/// 与 server/wifirouter/main/app_ui.c 一致的配色。
enum Palette {
    static let background = Color(hex: 0x070C12)
    static let panelHex: UInt32 = 0x111C28
    static let panel = Color(hex: panelHex)
    static let mint = Color(hex: 0x6DE1C2)
    static let amber = Color(hex: 0xFFC078)
    static let text = Color(hex: 0xF0F5FC)
    static let muted = Color(hex: 0x8497AC)
    static let warning = Color(hex: 0xFFD166)
    static let critical = Color(hex: 0xFF5F6D)
    static let noteText = Color(hex: 0x30382D)
    static let noteMuted = Color(hex: 0x626B50)

    private static let cards: [UInt32] = [0xFFC078, 0x6DE1C2, 0x83B6FF] // 与设备一致：琥珀、薄荷、蓝
    private static let papers: [UInt32] = [0xFFF2A6, 0xDDEEB4, 0xF7B6B2, 0xB9DFF2]
    /// 便签抬头：同色系加深。
    private static let headers: [UInt32] = [0xE2CA65, 0xAEC87C, 0xDE8580, 0x83BBD7]

    static func cardHex(_ i: Int) -> UInt32 { cards[((i % cards.count) + cards.count) % cards.count] }
    static func paperHex(_ i: Int) -> UInt32 { papers[((i % papers.count) + papers.count) % papers.count] }
    static func card(_ i: Int) -> Color { Color(hex: cardHex(i)) }
    static func paper(_ i: Int) -> Color { Color(hex: paperHex(i)) }
    static func paperHeaderHex(_ i: Int) -> UInt32 { headers[((i % headers.count) + headers.count) % headers.count] }
    static func paperHeader(_ i: Int) -> Color { Color(hex: paperHeaderHex(i)) }

    /// 设备 mix()：逐通道线性混合，四舍五入。
    static func mixHex(_ a: UInt32, _ b: UInt32, _ weight: Double) -> UInt32 {
        stride(from: 0, through: 16, by: 8).reduce(UInt32(0)) { color, shift in
            let x = Double(a >> UInt32(shift) & 0xFF), y = Double(b >> UInt32(shift) & 0xFF)
            return color | UInt32((x + (y - x) * weight + 0.5).rounded(.down)) << UInt32(shift)
        }
    }

    /// 设备 tone()：余量 < 5 红、< 20 黄、正常用卡片强调色，否则灰。
    static func toneHex(_ tone: Tone, accent: UInt32) -> UInt32 {
        switch tone {
        case .critical: 0xFF5F6D
        case .low: 0xFFD166
        case .accent: accent
        case .muted: 0x8497AC
        }
    }

    static func level(_ level: QuotaLevel) -> Color? {
        switch level {
        case .low: warning
        case .critical: critical
        default: nil
        }
    }
}

/// 便签正文字体：霞鹜文楷 v1.530 的 GB2312 子集（见 tools/make_note_font.py），缺字由系统字体补。
enum NoteFont {
    static let postScriptName = "StandItNote-Regular"

    /// 固定字号（布局已按屏幕计算字号，不再跟随动态字体）。
    static func of(size: CGFloat) -> Font { .custom(postScriptName, fixedSize: size) }
}
