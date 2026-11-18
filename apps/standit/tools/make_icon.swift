// 生成 1024×1024 App 图标：深色底上一张略微倾斜、立在底座上的便利贴。
// 用法：swift tools/make_icon.swift <输出路径>
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let size = 1024
let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: CGFloat(hex >> 16 & 0xFF) / 255, green: CGFloat(hex >> 8 & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}
ctx.setFillColor(rgb(0x070C12)); ctx.fill(CGRect(x: 0, y: 0, width: size, height: size))
// 底座
ctx.setFillColor(rgb(0x83B6FF, 0.9))
ctx.addPath(CGPath(roundedRect: CGRect(x: 232, y: 168, width: 560, height: 56), cornerWidth: 28, cornerHeight: 28, transform: nil))
ctx.fillPath()
// 便签
ctx.saveGState()
ctx.translateBy(x: 512, y: 560); ctx.rotate(by: -0.07)
let note = CGRect(x: -270, y: -290, width: 540, height: 560)
ctx.setShadow(offset: CGSize(width: 0, height: -18), blur: 40, color: rgb(0x000000, 0.6))
let fold: CGFloat = 120
let body = CGMutablePath()
body.move(to: CGPoint(x: note.minX, y: note.minY))
body.addLine(to: CGPoint(x: note.maxX - fold, y: note.minY))
body.addLine(to: CGPoint(x: note.maxX, y: note.minY + fold))
body.addLine(to: CGPoint(x: note.maxX, y: note.maxY))
body.addLine(to: CGPoint(x: note.minX, y: note.maxY))
body.closeSubpath()
ctx.setFillColor(rgb(0xFFF2A6)); ctx.addPath(body); ctx.fillPath()
ctx.setShadow(offset: .zero, blur: 0, color: nil)
let corner = CGMutablePath()
corner.move(to: CGPoint(x: note.maxX - fold, y: note.minY))
corner.addLine(to: CGPoint(x: note.maxX - fold, y: note.minY + fold))
corner.addLine(to: CGPoint(x: note.maxX, y: note.minY + fold))
corner.closeSubpath()
ctx.setFillColor(rgb(0xE2CA65)); ctx.addPath(corner); ctx.fillPath()
// 字迹线条
ctx.setStrokeColor(rgb(0x30382D, 0.75)); ctx.setLineWidth(34); ctx.setLineCap(.round)
for (i, w) in [CGFloat(360), 300, 380].enumerated() {
    let y = note.maxY - 130 - CGFloat(i) * 100
    ctx.move(to: CGPoint(x: note.minX + 80, y: y)); ctx.addLine(to: CGPoint(x: note.minX + 80 + w, y: y))
}
ctx.strokePath()
ctx.restoreGState()
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
CGImageDestinationFinalize(dest)
