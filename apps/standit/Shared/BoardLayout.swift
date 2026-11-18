import CoreGraphics

enum Page: Equatable, Hashable {
    case quota(index: Int)
    case note(index: Int)
}

enum WeatherPlacement: Equatable { case leading, top }

/// 纯几何计算：所有尺寸都来自实际可用区域，不假设方屏。
enum BoardLayout {
    /// perPage = 最小可读卡片尺寸下区域能容纳的最多卡片；columns/rows 为本页实际卡片数下让卡片最“饱满”的排法。
    static func grid(count: Int, in size: CGSize,
                     minCard: CGSize = CGSize(width: 220, height: 120)) -> (columns: Int, rows: Int, perPage: Int) {
        let maxColumns = max(1, Int(size.width / minCard.width))
        let maxRows = max(1, Int(size.height / minCard.height))
        let perPage = maxColumns * maxRows
        let visible = max(1, min(count, perPage))
        var best = (columns: 1, rows: 1, score: -1.0, empty: Int.max)
        for columns in 1...min(visible, maxColumns) {
            let rows = (visible + columns - 1) / columns
            guard rows <= maxRows else { continue }
            let score = Double(min(size.width / CGFloat(columns) / minCard.width,
                                   size.height / CGFloat(rows) / minCard.height))
            let empty = columns * rows - visible
            if score > best.score + 1e-9 || (abs(score - best.score) < 1e-9 && empty < best.empty) {
                best = (columns, rows, score, empty)
            }
        }
        return (best.columns, best.rows, perPage)
    }

    static func pages(cardCount: Int, perPage: Int, notes: Int) -> [Page] {
        let quotaPages = max(1, (cardCount + max(1, perPage) - 1) / max(1, perPage))
        return (0..<quotaPages).map { .quota(index: $0) } + (0..<max(0, notes)).map { .note(index: $0) }
    }

    static func weatherPlacement(_ size: CGSize) -> WeatherPlacement {
        size.width > size.height ? .leading : .top
    }

    /// 折痕把区域分成两块（不含折痕本身）；无折痕返回 nil。
    static func split(_ size: CGSize, around fold: CGRect?) -> (CGRect, CGRect)? {
        guard let fold, !fold.isEmpty else { return nil }
        if fold.width >= fold.height {
            return (CGRect(x: 0, y: 0, width: size.width, height: max(0, fold.minY)),
                    CGRect(x: 0, y: fold.maxY, width: size.width, height: max(0, size.height - fold.maxY)))
        }
        return (CGRect(x: 0, y: 0, width: max(0, fold.minX), height: size.height),
                CGRect(x: fold.maxX, y: 0, width: max(0, size.width - fold.maxX), height: size.height))
    }
}
