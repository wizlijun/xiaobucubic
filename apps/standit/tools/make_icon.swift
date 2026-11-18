// 生成 1024×1024 App 图标：整张图标就是一张便签（顶部加深色抬头，同 App 便签页），纸面中间一条剩余额度进度。
// 便签的四组配色各出一套：AppIcon（黄，主图标）、AppIcon-Green / -Pink / -Blue（设置里可换的备用图标）。
// 用法：swift tools/make_icon.swift StandIt/Assets.xcassets
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let size: CGFloat = 1024
func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: CGFloat(hex >> 16 & 0xFF) / 255, green: CGFloat(hex >> 8 & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}

/// 与 Palette.paper / paperHeader 同序：黄、绿、粉、蓝
let sets: [(name: String, paper: UInt32, header: UInt32)] = [
    ("AppIcon", 0xFFF2A6, 0xE2CA65), ("AppIcon-Green", 0xDDEEB4, 0xAEC87C),
    ("AppIcon-Pink", 0xF7B6B2, 0xDE8580), ("AppIcon-Blue", 0xB9DFF2, 0x83BBD7),
]

func draw(paper: UInt32, headerColor: UInt32) -> CGImage {
    let ctx = CGContext(data: nil, width: Int(size), height: Int(size), bitsPerComponent: 8, bytesPerRow: 0,
                        space: CGColorSpace(name: CGColorSpace.sRGB)!,
                        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    func fillRound(_ r: CGRect, _ radius: CGFloat, _ c: CGColor) {
        ctx.setFillColor(c)
        ctx.addPath(CGPath(roundedRect: r, cornerWidth: radius, cornerHeight: radius, transform: nil))
        ctx.fillPath()
    }
    // 以左上角为原点
    ctx.translateBy(x: 0, y: size); ctx.scaleBy(x: 1, y: -1)
    // 便签铺满；圆角由系统遮罩
    let header: CGFloat = 256
    ctx.setFillColor(rgb(paper)); ctx.fill(CGRect(x: 0, y: 0, width: size, height: size))
    ctx.setFillColor(rgb(headerColor)); ctx.fill(CGRect(x: 0, y: 0, width: size, height: header))

    // 纸面上的额度进度：浅色轨道 + 便签字色
    let barH: CGFloat = 116, barX: CGFloat = 176, barW = size - 2 * barX
    let barY = header + (size - header - barH) / 2
    fillRound(CGRect(x: barX, y: barY, width: barW, height: barH), barH / 2, rgb(0x30382D, 0.12))
    fillRound(CGRect(x: barX, y: barY, width: barW * 0.62, height: barH), barH / 2, rgb(0x30382D))
    return ctx.makeImage()!
}

let catalog = URL(fileURLWithPath: CommandLine.arguments[1])
for set in sets {
    let dir = catalog.appendingPathComponent(set.name + ".appiconset")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let dest = CGImageDestinationCreateWithURL(dir.appendingPathComponent("icon.png") as CFURL,
                                               UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, draw(paper: set.paper, headerColor: set.header), nil)
    CGImageDestinationFinalize(dest)
    let contents = #"{"images":[{"filename":"icon.png","idiom":"universal","platform":"ios","size":"1024x1024"}],"info":{"author":"xcode","version":1}}"#
    try contents.write(to: dir.appendingPathComponent("Contents.json"), atomically: true, encoding: .utf8)
}
