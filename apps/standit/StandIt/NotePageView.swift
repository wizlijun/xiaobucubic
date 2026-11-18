import SwiftUI

/// 一张便签铺满区域；字号从短边 × 0.12 递减到 × 0.045，取第一个能放下全文的档位。
struct NotePageView: View {
    let note: Note
    let paper: Int
    let now: Int

    var body: some View {
        GeometryReader { geo in
            let s = min(geo.size.width, geo.size.height)
            let pad = s * 0.08
            VStack(alignment: .leading, spacing: s * 0.03) {
                if note.title != "提醒" && !note.title.isEmpty {
                    Text(note.title).font(.system(size: s * 0.045, weight: .semibold, design: .rounded))
                        .opacity(0.6).lineLimit(1)
                }
                ViewThatFits(in: .vertical) {
                    ForEach(Self.scales, id: \.self) { k in
                        Text(note.text).font(NoteFont.of(size: s * k))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Text(note.text).font(NoteFont.of(size: s * Self.scales.last!))
                        .truncationMode(.tail)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                let tags = footer
                if !tags.isEmpty {
                    HStack(spacing: s * 0.03) {
                        ForEach(tags, id: \.self) { Text($0) }
                    }
                    .font(.system(size: s * 0.04, weight: .semibold, design: .rounded)).opacity(0.65).lineLimit(1)
                }
            }
            .foregroundStyle(Palette.noteText)
            .padding(pad)
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
            .background(Palette.paper(paper), in: RoundedRectangle(cornerRadius: min(28, s * 0.04)))
        }
    }

    static let scales: [CGFloat] = [0.12, 0.105, 0.09, 0.08, 0.07, 0.06, 0.052, 0.045]

    private var footer: [String] {
        var tags: [String] = []
        if note.priority == "high" { tags.append("● 重要") }
        if note.isBot { tags.append("Bot") }
        if let due = Format.due(note.dueAt, now: now) { tags.append(due) }
        return tags
    }
}
