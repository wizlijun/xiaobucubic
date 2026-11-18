import SwiftUI

/// 一张便签铺满区域，照设备便签页：加深色抬头“便签 · i / n”，纸面正文（文楷常规），底部浅色小字。
/// 正文字号从短边 × 0.12 递减到 × 0.045，取第一个能放下全文的档位。
struct NotePageView: View {
    let note: Note
    let paper: Int
    let count: Int
    let now: Int

    var body: some View {
        GeometryReader { geo in
            let s = min(geo.size.width, geo.size.height)
            let pad = s * 0.07
            let headerH = max(32, s * 0.09)
            VStack(alignment: .leading, spacing: 0) {
                Text(Format.noteHeader(index: paper, count: count))
                    .font(.system(size: headerH * 0.48, weight: .medium, design: .rounded))
                    .foregroundStyle(Palette.noteText).lineLimit(1)
                    .padding(.horizontal, pad)
                    .frame(maxWidth: .infinity, minHeight: headerH, maxHeight: headerH, alignment: .leading)
                    .background(Palette.paperHeader(paper))
                VStack(alignment: .leading, spacing: s * 0.03) {
                    ViewThatFits(in: .vertical) {
                        ForEach(Self.scales, id: \.self) { k in
                            Text(note.text).font(NoteFont.of(size: s * k))
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Text(note.text).font(NoteFont.of(size: s * Self.scales.last!))
                            .truncationMode(.tail)
                    }
                    .foregroundStyle(Palette.noteText)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    Text(Format.noteMeta(note, now: now))
                        .font(.system(size: max(13, s * 0.04), design: .rounded))
                        .foregroundStyle(Palette.noteMuted).lineLimit(1)
                }
                .padding(pad)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Palette.paper(paper))
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .clipShape(RoundedRectangle(cornerRadius: min(28, s * 0.04)))
        }
    }

    static let scales: [CGFloat] = [0.12, 0.105, 0.09, 0.08, 0.07, 0.06, 0.052, 0.045]
}
