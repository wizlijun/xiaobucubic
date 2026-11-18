import UIKit
import XCTest
@testable import StandIt

final class NoteFontTests: XCTestCase {
    /// 便签正文用文楷子集 StandIt Note（常规字重）；字体必须随 App 注册成功，否则会悄悄退回系统字体。
    func testNoteFontRegistered() throws {
        let font = try XCTUnwrap(UIFont(name: NoteFont.postScriptName, size: 20))
        XCTAssertEqual(font.familyName, "StandIt Note")
        XCTAssertFalse(font.fontDescriptor.symbolicTraits.contains(.traitBold))
    }
}
