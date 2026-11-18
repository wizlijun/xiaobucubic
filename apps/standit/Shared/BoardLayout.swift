import CoreGraphics

enum Page: Equatable, Hashable {
    case quota(index: Int)
    case note(index: Int)
}

/// 纯几何计算：所有尺寸都来自实际可用区域，不假设方屏。
enum BoardLayout {
    static func pages(cardCount: Int, perPage: Int, notes: Int) -> [Page] {
        let quotaPages = max(1, (cardCount + max(1, perPage) - 1) / max(1, perPage))
        return (0..<quotaPages).map { .quota(index: $0) } + (0..<max(0, notes)).map { .note(index: $0) }
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
