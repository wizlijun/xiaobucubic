import XCTest
@testable import StandIt

final class SmokeTests: XCTestCase {
    func testSharedIdentifiersExpanded() {
        XCTAssertEqual(SharedConfig.appGroup?.hasPrefix("group."), true)
        XCTAssertFalse(SharedConfig.appGroup?.contains("$(") ?? true)
    }
}
