import Foundation

struct ScopeSnapshot: Codable, Identifiable, Hashable {
    var userId: String
    var conversationId: String
    var channelId: String?
    var guildId: String?
    var displayName: String
    var lastMessageAt: String
    var latestSenderType: String
    var latestPreview: String
    var pendingCandidates: Int
    var activeMemories: Int
    var turnCount: Int

    var id: String { conversationId }
}

struct ModeState: Codable, Hashable {
    var mode: String = "auto"
    var learningMode: Bool = false
    var customModel: String?
    var backupModel: String?
    var metadata: [String: JSONValue] = [:]

    var displayMode: String {
        switch mode {
        case "fast": "快速"
        case "think": "思考"
        case "custom": "自定义"
        default: "自动"
        }
    }
}

struct MobileFeatureFlags: Codable, Hashable {
    var streamingChat: Bool
    var attachments: Bool
    var voiceTranscription: Bool
    var imageGeneration: Bool
    var localNotifications: Bool
    var apns: Bool
    var authenticationRequired: Bool
    var httpsRequired: Bool
    var deviceContextSync: Bool
    var nativeDashboard: Bool
}

struct CompanionProfile: Codable, Hashable {
    var appName: String
    var displayName: String
    var relationshipLabel: String
    var tone: String
}

struct MobileSceneState: Codable, Hashable {
    var key: String
    var assetName: String
    var statusLine: String
    var reason: String
    var updatedAt: String
}

struct MobileDashboardGroup: Codable, Identifiable, Hashable {
    var id: String
    var title: String
    var subtitle: String
    var panels: [String]
}

struct MobileBootstrap: Codable {
    var activeScope: ScopeSnapshot?
    var mode: ModeState
    var profile: CompanionProfile
    var sceneState: MobileSceneState?
    var timelineCursor: String?
    var dashboardGroups: [MobileDashboardGroup]?
    var presence: [String: JSONValue]
    var companionDay: [String: JSONValue]
    var proactive: [String: JSONValue]
    var realityContext: [String: JSONValue]
    var featureFlags: MobileFeatureFlags
    var refreshedAt: String
}

struct MobileMessage: Codable, Identifiable, Hashable {
    var id: Int
    var platform: String
    var conversationId: String
    var sessionId: String
    var platformMessageId: String?
    var senderType: String
    var authorId: String
    var userId: String
    var channelId: String
    var guildId: String?
    var replyToPlatformMessageId: String?
    var threadId: String?
    var content: String
    var metadata: [String: JSONValue]
    var createdAt: String

    var isUser: Bool { senderType == "user" }
}

struct MobileMessagesResponse: Codable {
    var activeScope: ScopeSnapshot?
    var items: [MobileMessage]
    var hasMore: Bool
    var nextBeforeId: Int?
    var refreshedAt: String
}

struct MobileTimelineAttachment: Codable, Identifiable, Hashable {
    var uploadUid: String?
    var filename: String
    var artifactType: String
    var contentType: String?
    var summaryText: String
    var metadata: [String: JSONValue]

    var id: String { "\(uploadUid ?? filename)-\(artifactType)" }
}

struct MobileTimelineItem: Codable, Identifiable, Hashable {
    var id: String
    var kind: String
    var createdAt: String
    var content: String
    var senderLabel: String
    var messageId: Int?
    var proactiveUid: String?
    var attachments: [MobileTimelineAttachment]
    var generatedImageUrl: String?
    var feedback: [String: JSONValue]
    var metadata: [String: JSONValue]

    var isUser: Bool {
        metadata["sender_type"]?.stringValue == "user" || senderLabel == "你"
    }

    var isProactive: Bool {
        kind == "proactive"
    }
}

struct MobileTimelineResponse: Codable {
    var activeScope: ScopeSnapshot?
    var items: [MobileTimelineItem]
    var hasMore: Bool
    var nextCursor: String?
    var refreshedAt: String
}

struct MobileToolOverrides: Codable, Hashable {
    var search: Bool?
    var draw: Bool?
}

struct MobileChatRequest: Codable {
    var content: String
    var clientMessageId: String?
    var attachmentUids: [String]
    var displayName: String
    var toolOverrides: MobileToolOverrides
    var clientScene: String?
    var clientTimezone: String?
    var metadata: [String: JSONValue]
}

struct ChatStreamEvent: Codable, Identifiable, Hashable {
    var event: String
    var requestId: String?
    var turnUid: String?
    var text: String?
    var fullText: String?
    var message: String?
    var modelName: String?
    var fallbackUsed: Bool?
    var userMessageId: Int?
    var assistantMessageId: Int?
    var generatedImagePath: String?
    var imageUrl: String?
    var latencyMs: Double?
    var requestType: String?
    var scene: String?
    var replyGoal: String?
    var shouldSearch: Bool?
    var shouldDraw: Bool?

    var id: String { "\(event)-\(requestId ?? turnUid ?? UUID().uuidString)" }
}

struct MobileAttachmentItem: Codable, Identifiable, Hashable {
    var filename: String
    var artifactType: String
    var contentType: String?
    var extractedText: String
    var summaryText: String
    var truncated: Bool
    var metadata: [String: JSONValue]

    var id: String { filename + artifactType + summaryText }
}

struct MobileAttachmentUploadResponse: Codable {
    var uploadUid: String
    var items: [MobileAttachmentItem]
    var createdAt: String
}

struct MobileStatusResponse: Codable {
    var activeScope: ScopeSnapshot?
    var text: String
    var mode: ModeState
    var requestsLastHour: Int
    var refreshedAt: String
}

struct ProactiveMessage: Codable, Identifiable, Hashable {
    var proactiveUid: String
    var userId: String?
    var conversationId: String?
    var channelId: String?
    var triggerType: String?
    var openingText: String
    var status: String?
    var accepted: Bool?
    var coldResponse: Bool?
    var responseMessageId: Int?
    var responseLatencyMinutes: Double?
    var metadata: [String: JSONValue]
    var sentAt: String
    var updatedAt: String?

    var id: String { proactiveUid }
}

struct MobileProactiveResponse: Codable {
    var activeScope: ScopeSnapshot?
    var items: [ProactiveMessage]
    var cursor: String?
    var refreshedAt: String
}

struct ProactivePreferences: Codable, Hashable {
    var enabled: Bool = true
    var cadence: String = "low"
    var source: String?
    var updatedAt: String?

    init(enabled: Bool = true, cadence: String = "low", source: String? = nil, updatedAt: String? = nil) {
        self.enabled = enabled
        self.cadence = cadence
        self.source = source
        self.updatedAt = updatedAt
    }

    init(json: [String: JSONValue]) {
        enabled = json["enabled"]?.boolValue ?? true
        cadence = json["cadence"]?.stringValue ?? "low"
        source = json["source"]?.stringValue
        updatedAt = json["updatedAt"]?.stringValue ?? json["updated_at"]?.stringValue
    }

    var cadenceLabel: String {
        switch cadence {
        case "high": "高频"
        case "normal": "中频"
        default: "低频"
        }
    }
}

struct MobileProactivePreferencesResponse: Codable {
    var activeScope: ScopeSnapshot?
    var preferences: ProactivePreferences
    var gate: [String: JSONValue]
    var refreshedAt: String
}

struct PaginationMeta: Codable, Hashable {
    var page: Int
    var pageSize: Int
    var total: Int
    var totalPages: Int
    var q: String?
    var sort: String?
    var filters: [String: JSONValue]?
    var refreshedAt: String?
    var durationMs: Double?
}

struct PanelEnvelope: Codable {
    var activeScope: ScopeSnapshot?
    var items: [JSONValue]
    var groups: [JSONValue]
    var summary: [String: JSONValue]
    var highlights: [String: JSONValue]
    var meta: PaginationMeta
}

struct ActionResponse: Codable {
    var ok: Bool
    var message: String?
    var itemId: String?
    var activeScope: ScopeSnapshot?
    var payload: [String: JSONValue]
}

struct DeviceLocationPayload: Codable {
    var label: String
    var latitude: Double
    var longitude: Double
    var note: String?
}

struct DeviceCalendarEventPayload: Codable, Hashable {
    var title: String
    var startAt: String
    var endAt: String?
    var location: String?
    var isAllDay: Bool
    var note: String?
}

struct DeviceContextPayload: Codable {
    var location: DeviceLocationPayload?
    var calendarEvents: [DeviceCalendarEventPayload]
    var source: String
}
