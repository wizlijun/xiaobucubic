import SwiftUI

/// 唯一的交互：粘贴接入点与 token，保存后立即试连一次。
struct SettingsView: View {
    var initial: EndpointConfig?
    var onSaved: () -> Void
    var onClose: (() -> Void)?

    @State private var url = ""
    @State private var token = ""
    @State private var message: String?
    @State private var saving = false
    @FocusState private var focus: Field?

    enum Field { case url, token }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Text("StandIt").font(.system(size: 34, weight: .bold, design: .rounded))
                    Spacer()
                    if let onClose {
                        Button("返回看板", action: onClose).font(.system(.body, design: .rounded))
                    }
                }
                field("接入点 URL", text: $url, prompt: "http://host:8007", field: .url)
                field("Token（可留空）", text: $token, prompt: "只读 token", field: .token)
                HStack(spacing: 12) {
                    PasteButton(payloadType: String.self) { strings in
                        guard let value = strings.first?.trimmingCharacters(in: .whitespacesAndNewlines) else { return }
                        if focus == .token { token = value } else { url = value }
                    }
                    .labelStyle(.titleAndIcon)
                    Button {
                        Task { await save() }
                    } label: {
                        Text(saving ? "连接中…" : "保存").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent).disabled(saving)
                }
                if let message {
                    Text(message).foregroundStyle(Palette.warning).font(.system(.callout, design: .rounded))
                }
                Text("接入点可填服务根地址或完整的 /v1/display 地址。接入点与 token 只保存在本机钥匙串中。")
                    .font(.system(.footnote, design: .rounded)).foregroundStyle(Palette.muted)
            }
            .padding(24)
            .frame(maxWidth: 560)
            .frame(maxWidth: .infinity)
        }
        .foregroundStyle(Palette.text)
        .background(Palette.background.ignoresSafeArea())
        .onAppear {
            url = initial?.url.absoluteString ?? ""
            token = initial?.token ?? ""
            focus = initial == nil ? .url : nil
        }
    }

    private func field(_ title: String, text: Binding<String>, prompt: String, field: Field) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(.subheadline, design: .rounded)).foregroundStyle(Palette.muted)
            Group {
                if field == .token {
                    SecureField(prompt, text: text)
                } else {
                    TextField(prompt, text: text).keyboardType(.URL)
                }
            }
            .textInputAutocapitalization(.never).autocorrectionDisabled()
            .focused($focus, equals: field)
            .padding(12)
            .background(Palette.panel, in: RoundedRectangle(cornerRadius: 10))
        }
    }

    private func save() async {
        guard let endpoint = Endpoint.normalize(url) else {
            message = "接入点格式不对：需要 http:// 或 https:// 开头"
            return
        }
        let config = EndpointConfig(url: endpoint, token: token.trimmingCharacters(in: .whitespacesAndNewlines))
        do {
            try ConfigStore.shared.save(config)
        } catch {
            message = "无法保存到钥匙串"
            return
        }
        url = endpoint.absoluteString
        saving = true
        defer { saving = false }
        do {
            let (_, raw) = try await DisplayClient().fetch(config)
            SnapshotCache.shared.store(raw: raw, receivedAt: Date(timeIntervalSince1970: Date().timeIntervalSince1970.rounded(.down)))
            message = nil
            onSaved()
        } catch let error as FetchError {
            message = error == .unauthorized ? "鉴权失败：请检查 token" : "已保存，但\(error.message)"
            if SaveOutcome.entersBoard(after: error) { onSaved() } // 进看板后由看板重试并显示错误
        } catch {
            onSaved()
        }
    }
}
