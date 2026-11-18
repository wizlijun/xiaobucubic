import Foundation
import Security

struct EndpointConfig: Codable, Equatable {
    var url: URL
    var token: String
}

enum Endpoint {
    /// 用户粘贴的地址 → 完整的 `/v1/display` 地址；无法识别时返回 nil。
    static func normalize(_ raw: String) -> URL? {
        let s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var parts = URLComponents(string: s), let scheme = parts.scheme?.lowercased(),
              ["http", "https"].contains(scheme), parts.host?.isEmpty == false else { return nil }
        var path = parts.path
        while path.hasSuffix("/") { path.removeLast() }
        if !path.lowercased().hasSuffix("/v1/display") { path += "/v1/display" }
        parts.path = path
        return parts.url
    }
}

/// 接入点与 token 只存 Keychain（App 与小组件共享同一访问组），不进 UserDefaults、不写日志。
final class ConfigStore {
    private let accessGroup: String?
    private let account: String

    init(accessGroup: String?, account: String = "endpoint") {
        self.accessGroup = accessGroup
        self.account = account
    }

    static var shared: ConfigStore { ConfigStore(accessGroup: SharedConfig.keychainGroup) }

    private var query: [String: Any] {
        var q: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                kSecAttrService as String: "standit",
                                kSecAttrAccount as String: account]
        if let accessGroup { q[kSecAttrAccessGroup as String] = accessGroup }
        return q
    }

    func load() -> EndpointConfig? {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
        return try? JSONDecoder().decode(EndpointConfig.self, from: data)
    }

    func save(_ config: EndpointConfig) throws {
        let data = try JSONEncoder().encode(config)
        clear()
        var q = query
        q[kSecValueData as String] = data
        // StandBy 在锁屏时运行：首次解锁后小组件即可读取。
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(q as CFDictionary, nil)
        guard status == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(status)) }
    }

    func clear() {
        SecItemDelete(query as CFDictionary)
    }
}
