// 生成 1024×1024 App 图标：深色渐变底上一张便签（加深色抬头，同 App 便签页），纸面中间一条剩余额度进度。
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
ctx.translateBy(x: 0, y: size); ctx.scaleBy(x: 1, y: -1)

// 底色：App 面板色到背景色
let bg = CGGradient(colorsSpace: nil, colors: [rgb(0x15212E), rgb(0x070C12)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(bg, start: .zero, end: CGPoint(x: 0, y: size), options: [])

// 便签：纸 FFF2A6，抬头 E2CA65（与 Palette.paper / paperHeader 第一组一致）
let note = CGRect(x: 212, y: 212, width: 600, height: 600), header: CGFloat = 150
ctx.saveGState()
ctx.addPath(CGPath(roundedRect: note, cornerWidth: 84, cornerHeight: 84, transform: nil)); ctx.clip()
ctx.setFillColor(rgb(0xFFF2A6)); ctx.fill(note)
ctx.setFillColor(rgb(0xE2CA65)); ctx.fill(CGRect(x: note.minX, y: note.minY, width: note.width, height: header))
ctx.restoreGState()

// 纸面上的额度进度：浅色轨道 + 深一点的薄荷绿
let barH: CGFloat = 72, barX = note.minX + 80, barW = note.width - 160
let barY = note.minY + header + (note.height - header - barH) / 2
fillRound(CGRect(x: barX, y: barY, width: barW, height: barH), barH / 2, rgb(0x30382D, 0.12))
fillRound(CGRect(x: barX, y: barY, width: barW * 0.62, height: barH), barH / 2, rgb(0x3FAF95))

let url = URL(fileURLWithPath: CommandLine.arguments[1])
let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
CGImageDestinationFinalize(dest)
