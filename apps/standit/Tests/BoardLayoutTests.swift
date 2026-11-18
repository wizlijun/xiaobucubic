import XCTest
@testable import StandIt

final class BoardLayoutTests: XCTestCase {
    private let minCard = CGSize(width: 220, height: 120)

    private func assertFits(_ size: CGSize, count: Int, file: StaticString = #filePath, line: UInt = #line) {
        let g = BoardLayout.grid(count: count, in: size)
        XCTAssertGreaterThanOrEqual(g.perPage, 1, file: file, line: line)
        XCTAssertGreaterThanOrEqual(g.columns * g.rows, min(count, g.perPage), file: file, line: line)
        XCTAssertGreaterThanOrEqual(size.width / CGFloat(g.columns), minCard.width, file: file, line: line)
        XCTAssertGreaterThanOrEqual(size.height / CGFloat(g.rows), minCard.height, file: file, line: line)
    }

    func testGridOnDuoScreens() {
        for size in [CGSize(width: 1335, height: 939), CGSize(width: 939, height: 1335),
                     CGSize(width: 466, height: 678), CGSize(width: 678, height: 466)] {
            for count in [1, 2, 3, 6, 7] { assertFits(size, count: count) }
        }
    }

    func testGridUsesWholeAreaForFewCards() {
        let g = BoardLayout.grid(count: 2, in: CGSize(width: 1000, height: 400))
        XCTAssertEqual(g.columns * g.rows, 2)
        XCTAssertEqual(g.columns, 2) // 宽区域并排而不是上下压扁
    }

    func testGridPerPageIsCapacity() {
        // 1335/220 = 6 列，939/120 = 7 行
        XCTAssertEqual(BoardLayout.grid(count: 99, in: CGSize(width: 1335, height: 939)).perPage, 42)
        // 区域比最小卡片还小时仍至少一张
        let tiny = BoardLayout.grid(count: 3, in: CGSize(width: 100, height: 50))
        XCTAssertEqual(tiny.perPage, 1)
        XCTAssertEqual(tiny.columns * tiny.rows, 1)
    }

    func testGridEmpty() {
        let g = BoardLayout.grid(count: 0, in: CGSize(width: 466, height: 678))
        XCTAssertEqual(g.columns, 1)
        XCTAssertEqual(g.rows, 1)
    }

    func testPages() {
        XCTAssertEqual(BoardLayout.pages(cardCount: 7, perPage: 6, notes: 2),
                       [.quota(index: 0), .quota(index: 1), .note(index: 0), .note(index: 1)])
        XCTAssertEqual(BoardLayout.pages(cardCount: 0, perPage: 6, notes: 0), [.quota(index: 0)])
        XCTAssertEqual(BoardLayout.pages(cardCount: 6, perPage: 6, notes: 1), [.quota(index: 0), .note(index: 0)])
    }

    func testWeatherPlacement() {
        XCTAssertEqual(BoardLayout.weatherPlacement(CGSize(width: 1335, height: 939)), .leading)
        XCTAssertEqual(BoardLayout.weatherPlacement(CGSize(width: 466, height: 678)), .top)
    }

    func testFoldSplit() {
        let size = CGSize(width: 1000, height: 800)
        // 水平折痕 → 上下两区，不含折痕
        let h = BoardLayout.split(size, around: CGRect(x: 0, y: 390, width: 1000, height: 20))
        XCTAssertEqual(h?.0, CGRect(x: 0, y: 0, width: 1000, height: 390))
        XCTAssertEqual(h?.1, CGRect(x: 0, y: 410, width: 1000, height: 390))
        // 垂直折痕 → 左右两区
        let v = BoardLayout.split(size, around: CGRect(x: 490, y: 0, width: 20, height: 800))
        XCTAssertEqual(v?.0, CGRect(x: 0, y: 0, width: 490, height: 800))
        XCTAssertEqual(v?.1, CGRect(x: 510, y: 0, width: 490, height: 800))
        XCTAssertNil(BoardLayout.split(size, around: nil))
    }

    func testHexColor() {
        XCTAssertEqual(Palette.cardHex(0), 0x6DE1C2)
        XCTAssertEqual(Palette.cardHex(4), 0x83B6FF)
        XCTAssertEqual(Palette.paperHex(5), 0xDDEEB4)
    }
}
