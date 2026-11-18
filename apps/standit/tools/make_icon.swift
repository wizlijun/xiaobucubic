// 生成 1024×1024 App 图标：整张图标就是一张便签（顶部加深色抬头，同 App 便签页），纸面中间一条剩余额度进度。
// 用法：swift tools/make_icon.swift <输出路径>
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let size: CGFloat = 1024
let ctx = CGContext(data: nil, width: Int(size), height: Int(size), bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: CGFloat(hex >> 16 & 0xFF) / 255, green: CGFloat(hex >> 8 & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}
func fillRound(_ r: CGRect, _ radius: CGFloat, _ c: CGColor) {
    ctx.setFillColor(c)
    ctx.addPath(CGPath(roundedRect: r, cornerWidth: radius, cornerHeight: radius, transform: nil))
    ctx.fillPath()
}
// 以左上角为原点
ctx.translateBy(x: 0, y: size); ctx.scaleBy(x: 1, y: -1)// 便签铺满：纸 FFF2A6，抬头 E2CA65（与 Palette.paper / paperHeader 第一组一致）；圆角由系统遮罩
let header: CGFloat = 256
ctx.setFillColor(rgb(0xFFF2A6)); ctx.fill(CGRect(x: 0, y: 0, width: size, height: size))
ctx.setFillColor(rgb(0xE2CA65)); ctx.fill(CGRect(x: 0, y: 0, width: size, height: header))

// 纸面上的额度进度：浅色轨道 + 便签字色
let barH: CGFloat = 116, barX: CGFloat = 176, barW = size - 2 * barX
let barY = header + (size - header - barH) / 2
fillRound(CGRect(x: barX, y: barY, width: barW, height: barH), barH / 2, rgb(0x30382D, 0.12))
fillRound(CGRect(x: barX, y: barY, width: barW * 0.62, height: barH), barH / 2, rgb(0x30382D))



let url = URL(fileURLWithPath: CommandLine.arguments[1])
let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
CGImageDestinationFinalize(dest)
