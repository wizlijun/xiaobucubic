import Foundation

/// App 与小组件共用的标识，均由 Info.plist 在构建时展开。
enum SharedConfig {
    static var appGroup: String? { Bundle.main.object(forInfoDictionaryKey: "StandItAppGroup") as? String }
    static var keychainGroup: String? { Bundle.main.object(forInfoDictionaryKey: "StandItKeychainGroup") as? String }
}
