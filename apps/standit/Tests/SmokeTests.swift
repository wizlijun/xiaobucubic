import XCTest
@testable import StandIt

final class SmokeTests: XCTestCase {
    /// App Group 可在 Local.xcconfig 中关闭（置空 → nil）；开启时必须已展开成 group.<前缀>.standit。
    func testSharedIdentifiersExpanded() throws {
        let keychain = try XCTUnwrap(SharedConfig.keychainGroup)
        XCTAssertTrue(keychain.hasSuffix(".standit.shared"))
        XCTAssertFalse(keychain.contains("$("))
        if let group = SharedConfig.appGroup {
            XCTAssertTrue(group.hasPrefix("group."))
            XCTAssertFalse(group.contains("$("))
        }
    }
}
