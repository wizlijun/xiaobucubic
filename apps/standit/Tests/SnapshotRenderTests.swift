import SwiftUI
import XCTest
@testable import StandIt

/// 按 Duo 内 / 外屏、半折叠、普通 iPhone 尺寸渲染主界面 PNG，供人工核对。
/// 运行：TEST_RUNNER_STANDIT_SNAPSHOT_DIR=<目录> tools/test.sh；未设置时跳过。
@MainActor
final class SnapshotRenderTests: XCTestCase {
    private let sizes: [(String, CGSize, CGRect?)] = [
        ("duo-inner-landscape", CGSize(width: 1335, height: 939), nil),
        ("duo-inner-portrait", CGSize(width: 939, height: 1335), nil),
        ("duo-inner-laptop-fold", CGSize(width: 1335, height: 939), CGRect(x: 0, y: 457, width: 1335, height: 24)),
        ("duo-inner-book-fold", CGSize(width: 939, height: 1335), CGRect(x: 457, y: 0, width: 24, height: 1335)),
        ("duo-outer-portrait", CGSize(width: 466, height: 678), nil),
        ("duo-outer-landscape", CGSize(width: 678, height: 466), nil),
        ("iphone-portrait", CGSize(width: 402, height: 874), nil),
        ("iphone-landscape", CGSize(width: 874, height: 402), nil),
    ]

    func testRenderBoards() throws {
        guard let dir = ProcessInfo.processInfo.environment["STANDIT_SNAPSHOT_DIR"] else {
            throw XCTSkip("STANDIT_SNAPSHOT_DIR not set")
        }
        let out = URL(fileURLWithPath: dir)
        try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        let bundle = Bundle(for: Self.self)
        let demo = try DisplayModel.normalize(Data(contentsOf: XCTUnwrap(bundle.url(forResource: "display", withExtension: "json"))))
        let extended = try DisplayModel.normalize(Data(contentsOf: XCTUnwrap(bundle.url(forResource: "display-v1-extended", withExtension: "json"))))
        let cases: [(String, CachedSnapshot?, FetchError?, Int)] = [
            ("demo", CachedSnapshot(snapshot: demo, receivedAt: Date(timeIntervalSince1970: TimeInterval(demo.generatedAt))), nil, demo.generatedAt + 60),
            ("extended", CachedSnapshot(snapshot: extended, receivedAt: Date(timeIntervalSince1970: TimeInterval(extended.generatedAt))), .network("x"), extended.generatedAt + 2000),
            ("empty", nil, .notConfigured, demo.generatedAt),
        ]
        for (name, size, fold) in sizes {
            for (label, cached, error, now) in cases {
                let pageCount = label == "demo" ? 3 : 1
                for page in 0..<pageCount {
                    let view = BoardContent(cached: cached, error: error, date: Date(timeIntervalSince1970: TimeInterval(now)),
                                            fold: fold, onSettings: {}, pageOverride: page)
                        .frame(width: size.width, height: size.height)
                        .environment(\.colorScheme, .dark)
                    let renderer = ImageRenderer(content: view)
                    renderer.scale = 1
                    let png = try XCTUnwrap(renderer.uiImage?.pngData())
                    try png.write(to: out.appendingPathComponent("\(name)-\(label)-p\(page).png"))
                }
            }
        }
    }
}
