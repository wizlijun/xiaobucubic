import SwiftUI

/// 一张便签铺满区域，照设备便签页：加深色抬头“便签 · i / n”，纸面正文（文楷常规），底部浅色小字。
/// 正文字号固定为短边的 7%，不随内容多少变化；放不下时末尾省略。
/// bleed 非空时便签纸铺满整块区域（分屏的那一半，含安全区外），直角；文字按 bleed 内缩到安全区内。
struct NotePageView: View {
    let note: Note
    let paper: Int
    let count: Int
    let now: Int
    var bleed: EdgeInsets? = nil

    var body: some View {
        GeometryReader { geo in
            let b = bleed ?? EdgeInsets()
            let s = min(geo.size.width - b.leading - b.trailing, geo.size.height - b.top - b.bottom)
            let pad = s * 0.07
            let headerH = max(32, s * 0.09)
            VStack(alignment: .leading, spacing: 0) {
                Text(Format.noteHeader(index: paper, count: count))
                    .font(.system(size: headerH * 0.48, weight: .medium, design: .rounded))
                    .foregroundStyle(Palette.noteText).lineLimit(1)
                    .padding(.leading, pad + b.leading).padding(.trailing, pad + b.trailing).padding(.top, b.top)
                    .frame(maxWidth: .infinity, minHeight: headerH + b.top, maxHeight: headerH + b.top, alignment: .leading)
                    .background(Palette.paperHeader(paper))
                VStack(alignment: .leading, spacing: s * 0.03) {
                    Text(note.text).font(NoteFont.of(size: NoteFont.bodySize(shortSide: s))).truncationMode(.tail)
                    .foregroundStyle(Palette.noteText)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    Text(Format.noteMeta(note, now: now))
                        .font(.system(size: max(13, s * 0.04), design: .rounded))
                        .foregroundStyle(Palette.noteMuted).lineLimit(1)
                }
                .padding(pad)
                .padding(EdgeInsets(top: 0, leading: b.leading, bottom: b.bottom, trailing: b.trailing))
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Palette.paper(paper))
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .clipShape(RoundedRectangle(cornerRadius: bleed == nil ? min(28, s * 0.04) : 0))
        }
    }

}
