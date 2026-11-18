import Foundation

/// App 与小组件共用的标识，均由 Info.plist 在构建时展开。
enum SharedConfig {
    /// 未开通 App Group 时为 nil（构建设置置空），缓存退回各自进程的 Caches 目录。
    static var appGroup: String? {
        (Bundle.main.object(forInfoDictionaryKey: "StandItAppGroup") as? String).flatMap { $0.isEmpty ? nil : $0 }
    }
    static var keychainGroup: String? { Bundle.main.object(forInfoDictionaryKey: "StandItKeychainGroup") as? String }
}
