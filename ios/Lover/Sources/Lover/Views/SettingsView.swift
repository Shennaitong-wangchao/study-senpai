import SwiftUI

struct SettingsView: View {
    let router: RouterPath

    @Environment(DeviceContextSyncService.self) private var deviceContext
    @Environment(LocalNotificationService.self) private var notifications
    @Environment(ChatStore.self) private var chat
    @State private var proactiveEnabled = true
    @State private var proactiveCadence = "low"
    @AppStorage(AppConfig.serverBaseURLKey) private var serverBaseURLText = AppConfig.defaultServerBaseURLString
    @AppStorage(AppConfig.mobileAPITokenKey) private var mobileAPIToken = ""

    var body: some View {
        List {
            Section {
                Button {
                    router.navigate(to: .controlCenter)
                } label: {
                    SettingsRow(title: "控制中心", detail: "完整后台", systemImage: "rectangle.grid.2x2")
                }
                Button {
                    router.present(.status)
                } label: {
                    SettingsRow(title: "状态", detail: chat.mode.displayMode, systemImage: "waveform.path.ecg")
                }
                Button {
                    router.present(.mode)
                } label: {
                    SettingsRow(title: "模式", detail: chat.mode.learningMode ? "学习开启" : "学习关闭", systemImage: "slider.horizontal.3")
                }
            }
            Section {
                Toggle("主动消息", isOn: $proactiveEnabled)
                    .onChange(of: proactiveEnabled) { _, value in
                        guard value != chat.proactivePreferences.enabled else { return }
                        Task { await chat.setProactivePreferences(enabled: value) }
                    }
                Picker("主动频率", selection: $proactiveCadence) {
                    Text("低频").tag("low")
                    Text("中频").tag("normal")
                    Text("高频").tag("high")
                }
                .pickerStyle(.segmented)
                .disabled(!proactiveEnabled)
                .onChange(of: proactiveCadence) { _, value in
                    guard value != chat.proactivePreferences.cadence else { return }
                    Task { await chat.setProactivePreferences(cadence: value) }
                }
                Button {
                    Task { await deviceContext.requestPermissionsAndSync() }
                } label: {
                    SettingsRow(title: "现实锚点", detail: deviceContext.lastSyncMessage ?? deviceContext.authorizationSummary, systemImage: "location")
                }
                Button {
                    Task { await notifications.requestAuthorization() }
                } label: {
                    SettingsRow(title: "本地通知", detail: notificationLabel, systemImage: "bell")
                }
            }
            Section {
                LabeledContent {
                    TextField("http://127.0.0.1:8000", text: $serverBaseURLText)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .multilineTextAlignment(.trailing)
                        .onSubmit {
                            serverBaseURLText = AppConfig.normalizedServerBaseURLString(serverBaseURLText)
                        }
                } label: {
                    Label("Server Base URL", systemImage: "server.rack")
                }
                LabeledContent {
                    SecureField("可选", text: $mobileAPIToken)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .multilineTextAlignment(.trailing)
                } label: {
                    Label("Mobile API Token", systemImage: "key")
                }
                Button {
                    serverBaseURLText = AppConfig.defaultServerBaseURLString
                    mobileAPIToken = ""
                } label: {
                    SettingsRow(title: "恢复本地默认", detail: AppConfig.defaultServerBaseURLString, systemImage: "arrow.counterclockwise")
                }
                SettingsRow(title: "应用", detail: "\(AppConfig.appName) · \(AppConfig.companionFullName)", systemImage: "app")
            }
        }
        .navigationTitle("设置")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await notifications.refreshAuthorization()
            await chat.refreshProactivePreferences()
            proactiveEnabled = chat.proactivePreferences.enabled
            proactiveCadence = chat.proactivePreferences.cadence
        }
    }

    private var notificationLabel: String {
        switch notifications.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return "已允许"
        case .denied:
            return "已拒绝"
        case .notDetermined:
            return "未询问"
        @unknown default:
            return "未知"
        }
    }
}

private struct SettingsRow: View {
    let title: String
    let detail: String
    let systemImage: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .frame(width: 28, height: 28)
                .foregroundStyle(Color.accentColor)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .foregroundStyle(Color(.label))
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
        }
        .contentShape(Rectangle())
    }
}
