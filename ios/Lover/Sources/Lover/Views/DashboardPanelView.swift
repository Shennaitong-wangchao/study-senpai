import SwiftUI
import SwiftData

struct DashboardPanelView: View {
    let panel: DashboardPanel

    @Environment(MobileAPIClient.self) private var api
    @Environment(DashboardClient.self) private var dashboard
    @Environment(\.modelContext) private var modelContext
    @State private var payload: JSONValue?
    @State private var query = ""
    @State private var status = ""
    @State private var isLoading = false
    @State private var isStale = false
    @State private var errorText: String?

    var body: some View {
        Group {
            if isLoading && payload == nil {
                ProgressView()
            } else if let payload {
                PayloadView(panel: panel, payload: payload, isStale: isStale, reload: { Task { await load() } })
            } else if let errorText {
                ContentUnavailableView(panel.title, systemImage: panel.systemImage, description: Text(errorText))
            } else {
                ContentUnavailableView(panel.title, systemImage: panel.systemImage)
            }
        }
        .navigationTitle(panel.title)
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Picker("状态", selection: $status) {
                        Text("全部").tag("")
                        Text("pending").tag("pending")
                        Text("open").tag("open")
                        Text("processed").tag("processed")
                        Text("approved").tag("approved")
                        Text("rejected").tag("rejected")
                    }
                } label: {
                    Image(systemName: "line.3.horizontal.decrease.circle")
                }
                .accessibilityLabel("筛选")
            }
        }
        .task { loadCached(); await load() }
        .task(id: status) {
            try? await Task.sleep(for: .milliseconds(180))
            if !Task.isCancelled { await load() }
        }
        .task(id: query) {
            try? await Task.sleep(for: .milliseconds(280))
            if !Task.isCancelled { await load() }
        }
        .refreshable { await load() }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            var queryItems = query.isEmpty ? [] : [URLQueryItem(name: "q", value: query)]
            if !status.isEmpty {
                queryItems.append(URLQueryItem(name: "status", value: status))
            }
            let data: Data = try await api.dataRequest("/mobile/dashboard/\(panel.rawValue)", query: queryItems, body: Optional<Int>.none)
            payload = try api.decoder.decode(JSONValue.self, from: data)
            errorText = nil
            isStale = false
            cache(data)
        } catch {
            errorText = error.localizedDescription
            loadCached(markStale: true)
        }
    }

    private func loadCached(markStale: Bool = false) {
        let panelKey = panel.rawValue
        let descriptor = FetchDescriptor<CachedDashboardPanel>(
            predicate: #Predicate { $0.panelKey == panelKey }
        )
        guard let cached = try? modelContext.fetch(descriptor).first,
              let data = cached.payloadText.data(using: .utf8),
              let decoded = try? api.decoder.decode(JSONValue.self, from: data)
        else { return }
        payload = decoded
        isStale = markStale
    }

    private func cache(_ data: Data) {
        let panelKey = panel.rawValue
        let text = String(data: data, encoding: .utf8) ?? "{}"
        let descriptor = FetchDescriptor<CachedDashboardPanel>(
            predicate: #Predicate { $0.panelKey == panelKey }
        )
        if let existing = try? modelContext.fetch(descriptor).first {
            existing.payloadText = text
            existing.refreshedAt = .now
        } else {
            modelContext.insert(CachedDashboardPanel(panelKey: panelKey, payloadText: text))
        }
        try? modelContext.save()
    }
}

private struct PayloadView: View {
    let panel: DashboardPanel
    let payload: JSONValue
    let isStale: Bool
    let reload: () -> Void

    var body: some View {
        List {
            if isStale {
                Section {
                    Label("显示上次成功缓存，刷新失败", systemImage: "clock.arrow.circlepath")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            if let object = payload.objectValue {
                if let meta = object["meta"] {
                    Section("Meta") {
                        JSONSummary(value: meta)
                    }
                }
                if let active = object["activeScope"] ?? object["active_scope"] {
                    Section("Scope") {
                        JSONSummary(value: active)
                    }
                }
                if let summary = object["summary"] {
                    Section("Summary") {
                        JSONSummary(value: summary)
                    }
                }
                if let overview = object["overview"] {
                    Section("Overview") {
                        JSONSummary(value: overview)
                    }
                }
                if let groups = object["groups"]?.arrayValue, !groups.isEmpty {
                    Section("Groups") {
                        ForEach(Array(groups.enumerated()), id: \.offset) { _, group in
                            JSONSummary(value: group)
                        }
                    }
                }
                if let items = (object["items"]?.arrayValue) {
                    Section("Items") {
                        ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                            DashboardItemRow(panel: panel, item: item, reload: reload)
                        }
                    }
                } else {
                    Section("Payload") {
                        JSONSummary(value: payload)
                    }
                }
            } else {
                JSONSummary(value: payload)
            }
        }
    }
}

private struct DashboardItemRow: View {
    let panel: DashboardPanel
    let item: JSONValue
    let reload: () -> Void

    @Environment(DashboardClient.self) private var dashboard
    @State private var isActing = false
    @State private var pendingAction: PanelAction?
    @State private var resultText: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
                .lineLimit(2)
            Text(subtitle)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(4)
            if !actions.isEmpty {
                HStack {
                    ForEach(actions, id: \.title) { action in
                        Button(action.title) {
                            if action.requiresConfirmation {
                                pendingAction = action
                            } else {
                                Task { await run(action) }
                            }
                        }
                        .buttonStyle(.bordered)
                        .tint(action.tone == .danger ? .red : nil)
                        .disabled(isActing)
                    }
                }
                .font(.caption)
            }
            if let resultText {
                Text(resultText)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
        .confirmationDialog(
            pendingAction?.confirmationTitle ?? "确认操作",
            isPresented: Binding(
                get: { pendingAction != nil },
                set: { if !$0 { pendingAction = nil } }
            ),
            titleVisibility: .visible
        ) {
            if let pendingAction {
                Button(pendingAction.title, role: pendingAction.tone == .danger ? .destructive : nil) {
                    Task { await run(pendingAction) }
                }
            }
            Button("取消", role: .cancel) {}
        }
    }

    private var object: [String: JSONValue] {
        item.objectValue ?? [:]
    }

    private var title: String {
        for key in ["content", "openingText", "opening_text", "message", "title", "taskType", "task_type", "memoryType", "memory_type", "candidateUid", "candidate_uid", "turnUid", "turn_uid", "filename"] {
            if let value = object[key]?.stringValue, !value.isEmpty { return value }
        }
        return item.displayString
    }

    private var subtitle: String {
        let values = ["status", "category", "scene", "summaryText", "summary_text", "createdAt", "created_at", "updatedAt", "updated_at"]
            .compactMap { key -> String? in
                guard let value = object[key]?.stringValue, !value.isEmpty else { return nil }
                return "\(key): \(value)"
            }
        return values.joined(separator: "  ")
    }

    private var actions: [PanelAction] {
        switch panel {
        case .memories:
            if let id = object["memoryUid"]?.stringValue ?? object["memory_uid"]?.stringValue {
                return [
                    PanelAction(title: "归档", path: "/mobile/dashboard/memories/\(id)/archive", requiresConfirmation: true, tone: .danger),
                    PanelAction(title: "恢复", path: "/mobile/dashboard/memories/\(id)/restore")
                ]
            }
        case .candidates:
            if let id = object["candidateUid"]?.stringValue ?? object["candidate_uid"]?.stringValue {
                return [
                    PanelAction(title: "确认", path: "/mobile/dashboard/candidates/\(id)/approve", body: ["note": .string("ios")]),
                    PanelAction(title: "拒绝", path: "/mobile/dashboard/candidates/\(id)/reject", body: ["note": .string("ios")], requiresConfirmation: true, tone: .danger),
                    PanelAction(title: "重开", path: "/mobile/dashboard/candidates/\(id)/reopen")
                ]
            }
        case .tasks:
            if let id = object["taskUid"]?.stringValue ?? object["task_uid"]?.stringValue {
                return [
                    PanelAction(title: "重试", path: "/mobile/dashboard/tasks/\(id)/retry"),
                    PanelAction(title: "加速", path: "/mobile/dashboard/tasks/\(id)/boost", body: ["priority": .number(2)]),
                    PanelAction(title: "取消", path: "/mobile/dashboard/tasks/\(id)/cancel", requiresConfirmation: true, tone: .danger)
                ]
            }
        case .errors:
            if let id = object["errorUid"]?.stringValue ?? object["error_uid"]?.stringValue {
                return [PanelAction(title: "处理", path: "/mobile/dashboard/errors/\(id)/status", body: ["status": .string("processed")], requiresConfirmation: true)]
            }
        case .proactive:
            if let id = object["proactiveUid"]?.stringValue ?? object["proactive_uid"]?.stringValue {
                return [
                    PanelAction(title: "有用", path: "/mobile/dashboard/proactive/\(id)/feedback", body: ["feedback": .string("good")]),
                    PanelAction(title: "太频繁", path: "/mobile/dashboard/proactive/\(id)/feedback", body: ["feedback": .string("too_frequent")], requiresConfirmation: true),
                    PanelAction(title: "不合适", path: "/mobile/dashboard/proactive/\(id)/feedback", body: ["feedback": .string("bad")], requiresConfirmation: true, tone: .danger)
                ]
            }
        case .audits:
            if let id = object["auditUid"]?.stringValue ?? object["audit_uid"]?.stringValue {
                return [PanelAction(title: "撤销", path: "/mobile/dashboard/audits/\(id)/undo", requiresConfirmation: true, tone: .danger)]
            }
        default:
            break
        }
        return []
    }

    private func run(_ action: PanelAction) async {
        isActing = true
        defer { isActing = false }
        do {
            let response = try await dashboard.action(action.path, method: action.method, body: action.body)
            resultText = response.message ?? "已完成"
        } catch {
            resultText = error.localizedDescription
        }
        pendingAction = nil
        reload()
    }
}

private enum PanelActionTone: Equatable {
    case normal
    case danger
}

private struct PanelAction: Identifiable {
    var title: String
    var path: String
    var method: String = "POST"
    var body: [String: JSONValue] = [:]
    var requiresConfirmation = false
    var tone: PanelActionTone = .normal

    var id: String { "\(title)-\(path)" }
    var confirmationTitle: String { "确认\(title)？" }
}

private struct JSONSummary: View {
    let value: JSONValue

    var body: some View {
        switch value {
        case .object(let object):
            ForEach(object.keys.sorted(), id: \.self) { key in
                HStack(alignment: .top) {
                    Text(key)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(width: 112, alignment: .leading)
                    Text(object[key]?.displayString ?? "-")
                        .font(.caption)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        case .array(let array):
            ForEach(Array(array.enumerated()), id: \.offset) { _, item in
                Text(item.displayString)
                    .font(.caption)
            }
        default:
            Text(value.displayString)
                .font(.caption)
        }
    }
}
