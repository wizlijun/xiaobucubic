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
    static let panel = Color(hex: 0x111C28)
    static let text = Color(hex: 0xF0F5FC)
    static let muted = Color(hex: 0x8497AC)
    static let warning = Color(hex: 0xFFD166)
    static let critical = Color(hex: 0xFF5F6D)
    static let noteText = Color(hex: 0x30382D)

    private static let cards: [UInt32] = [0x6DE1C2, 0x83B6FF, 0xFFC078]
    private static let papers: [UInt32] = [0xFFF2A6, 0xDDEEB4, 0xF7B6B2, 0xB9DFF2]

    static func cardHex(_ i: Int) -> UInt32 { cards[((i % cards.count) + cards.count) % cards.count] }
    static func paperHex(_ i: Int) -> UInt32 { papers[((i % papers.count) + papers.count) % papers.count] }
    static func card(_ i: Int) -> Color { Color(hex: cardHex(i)) }
    static func paper(_ i: Int) -> Color { Color(hex: paperHex(i)) }

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
