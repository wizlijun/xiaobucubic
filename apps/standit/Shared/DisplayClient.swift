import Foundation

enum FetchError: Error, Equatable {
    case notConfigured, unauthorized, http(Int), invalid(String), network(String)
}

struct DisplayClient {
    var session: URLSession = .shared

    init(session: URLSession = .shared) { self.session = session }

    /// 拉取并校验；返回规范化后的快照和原始 JSON（原始 JSON 用于写缓存）。
    func fetch(_ config: EndpointConfig) async throws -> (DisplaySnapshot, Data) {
        var request = URLRequest(url: config.url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        let token = config.token.trimmingCharacters(in: .whitespacesAndNewlines)
        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw FetchError.network((error as? URLError)?.localizedDescription ?? "网络错误")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 || status == 403 { throw FetchError.unauthorized }
        guard (200..<300).contains(status) else { throw FetchError.http(status) }
        do {
            return (try DisplayModel.normalize(data), data)
        } catch DisplayError.unsupportedVersion {
            throw FetchError.invalid("接口版本不支持")
        } catch DisplayError.missingTime {
            throw FetchError.invalid("缺少数据时间")
        } catch {
            throw FetchError.invalid("数据格式错误")
        }
    }
}

enum Backoff {
    private static let steps: [TimeInterval] = [5, 10, 20, 40, 80, 160, 300]

    /// failures == 0 为正常轮询间隔；连续失败按序退避，封顶 300 秒。
    static func delay(failures: Int) -> TimeInterval {
        failures <= 0 ? 60 : steps[min(failures, steps.count) - 1]
    }
}

extension FetchError {
    /// 面向用户的简短说明（App 状态行与小组件共用）。
    var message: String {
        switch self {
        case .notConfigured: "打开 Stand It 设置接入点"
        case .unauthorized: "鉴权失败"
        case .http(let code): "服务返回 \(code)"
        case .invalid(let reason): reason
        case .network: "无法连接"
        }
    }
}

/// 设置页保存后的去向。
enum SaveOutcome {
    static func entersBoard(after error: FetchError?) -> Bool { error != .unauthorized }
}
