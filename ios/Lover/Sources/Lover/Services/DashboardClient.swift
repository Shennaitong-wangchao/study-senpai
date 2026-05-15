import Foundation
import Observation

enum DashboardPanel: String, CaseIterable, Identifiable {
    case overview
    case search
    case scopes
    case memories
    case candidates
    case snapshots
    case turns
    case attachments
    case proactive
    case presence
    case companionDay = "companion-day"
    case realityContext = "reality-context"
    case facts
    case relationships
    case summaries
    case modes
    case tasks
    case errors
    case health
    case performance
    case logs
    case security
    case audits

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: "概览"
        case .search: "全局搜索"
        case .scopes: "会话"
        case .memories: "长期记忆"
        case .candidates: "候选记忆"
        case .snapshots: "记忆快照"
        case .turns: "Turn Trace"
        case .attachments: "附件"
        case .proactive: "主动消息"
        case .presence: "Presence"
        case .companionDay: "她的一天"
        case .realityContext: "现实锚点"
        case .facts: "结构化事实"
        case .relationships: "关系状态"
        case .summaries: "摘要"
        case .modes: "模式"
        case .tasks: "后台任务"
        case .errors: "错误"
        case .health: "健康"
        case .performance: "性能"
        case .logs: "日志"
        case .security: "安全"
        case .audits: "审计"
        }
    }

    var systemImage: String {
        switch self {
        case .overview: "gauge.with.dots.needle.67percent"
        case .search: "magnifyingglass"
        case .scopes: "person.2"
        case .memories: "archivebox"
        case .candidates: "tray.and.arrow.down"
        case .snapshots: "square.stack.3d.up"
        case .turns: "waveform.path.ecg"
        case .attachments: "paperclip"
        case .proactive: "bell.badge"
        case .presence: "sparkles"
        case .companionDay: "sun.max"
        case .realityContext: "location"
        case .facts: "list.bullet.rectangle"
        case .relationships: "heart.text.square"
        case .summaries: "text.justify"
        case .modes: "slider.horizontal.3"
        case .tasks: "checklist"
        case .errors: "exclamationmark.triangle"
        case .health: "cross.case"
        case .performance: "speedometer"
        case .logs: "doc.text.magnifyingglass"
        case .security: "lock.shield"
        case .audits: "clock.arrow.circlepath"
        }
    }

    var requiresConfirmation: Bool {
        switch self {
        case .memories, .candidates, .tasks, .errors, .presence, .companionDay, .realityContext, .proactive, .audits:
            return true
        default:
            return false
        }
    }
}

@Observable
final class DashboardClient {
    private let api: MobileAPIClient

    init(api: MobileAPIClient) {
        self.api = api
    }

    func panel(_ panel: DashboardPanel, query: String = "", page: Int = 1, status: String? = nil) async throws -> PanelEnvelope {
        let items = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "page", value: String(page)),
            URLQueryItem(name: "status", value: status)
        ].filter { ($0.value ?? "").isEmpty == false }
        return try await api.request("/mobile/dashboard/\(panel.rawValue)", query: items)
    }

    func action(_ path: String, method: String = "POST", body: [String: JSONValue] = [:]) async throws -> ActionResponse {
        try await api.request(path, method: method, body: body)
    }

    func setMode(_ mode: String, learningMode: Bool, customModel: String? = nil) async throws -> ModeState {
        struct Body: Encodable {
            var mode: String
            var learningMode: Bool
            var customModel: String?
        }
        return try await api.request("/mobile/mode", method: "POST", body: Body(mode: mode, learningMode: learningMode, customModel: customModel))
    }
}
