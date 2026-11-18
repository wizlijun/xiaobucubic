import XCTest
@testable import StandIt

final class BoardLayoutTests: XCTestCase {
    func testPages() {
        XCTAssertEqual(BoardLayout.pages(cardCount: 7, perPage: 6, notes: 2),
                       [.quota(index: 0), .quota(index: 1), .note(index: 0), .note(index: 1)])
        XCTAssertEqual(BoardLayout.pages(cardCount: 0, perPage: 6, notes: 0), [.quota(index: 0)])
        XCTAssertEqual(BoardLayout.pages(cardCount: 6, perPage: 6, notes: 1), [.quota(index: 0), .note(index: 0)])
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
        XCTAssertEqual(Palette.cardHex(0), 0xFFC078)
        XCTAssertEqual(Palette.cardHex(4), 0x6DE1C2)
        XCTAssertEqual(Palette.paperHex(5), 0xDDEEB4)
    }

    /// 便签抬头用加深色，与设备 app_ui.c 一致。
    func testNoteHeaderColorsMatchDevice() {
        XCTAssertEqual((0..<4).map(Palette.paperHeaderHex), [0xE2CA65, 0xAEC87C, 0xDE8580, 0x83BBD7])
        XCTAssertEqual(Palette.paperHeaderHex(5), 0xAEC87C)
    }
}
