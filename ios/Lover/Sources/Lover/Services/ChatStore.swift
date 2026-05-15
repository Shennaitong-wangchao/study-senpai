import Foundation
import Observation
import SwiftData

enum ComposerTool: String, CaseIterable, Identifiable {
    case auto
    case search
    case draw

    var id: String { rawValue }

    var title: String {
        switch self {
        case .auto: "自动"
        case .search: "搜索"
        case .draw: "绘图"
        }
    }

    var systemImage: String {
        switch self {
        case .auto: "sparkles"
        case .search: "magnifyingglass"
        case .draw: "paintbrush"
        }
    }
}

@MainActor
@Observable
final class ChatStore {
    var bootstrap: MobileBootstrap?
    var messages: [MobileMessage] = []
    var timeline: [MobileTimelineItem] = []
    var mode = ModeState()
    var statusText: String = ""
    var draft: String = ""
    var streamingAssistantText: String = ""
    var activeUploads: [MobileAttachmentUploadResponse] = []
    var latestPlan: ChatStreamEvent?
    var selectedTool: ComposerTool = .auto
    var timelineCursor: String?
    var proactivePreferences = ProactivePreferences()
    var isLoading = false
    var isStreaming = false
    var isStale = false
    var lastError: String?
    var proactiveCursor: String?

    private let api: MobileAPIClient
    private let stream: ChatStreamClient
    private let upload: UploadClient
    private let notifications: LocalNotificationService

    init(
        api: MobileAPIClient,
        stream: ChatStreamClient,
        upload: UploadClient,
        notifications: LocalNotificationService
    ) {
        self.api = api
        self.stream = stream
        self.upload = upload
        self.notifications = notifications
    }

    func loadCachedMessages(from context: ModelContext) {
        loadCachedTimeline(from: context)
        let descriptor = FetchDescriptor<CachedMessage>(sortBy: [SortDescriptor(\.id)])
        if let cached = try? context.fetch(descriptor), !cached.isEmpty {
            messages = cached.map {
                MobileMessage(
                    id: $0.id,
                    platform: "cache",
                    conversationId: "",
                    sessionId: "",
                    platformMessageId: nil,
                    senderType: $0.senderType,
                    authorId: "",
                    userId: "",
                    channelId: "",
                    guildId: nil,
                    replyToPlatformMessageId: nil,
                    threadId: nil,
                    content: $0.content,
                    metadata: [:],
                    createdAt: $0.createdAt
                )
            }
        }
    }

    func loadCachedTimeline(from context: ModelContext) {
        let descriptor = FetchDescriptor<CachedTimelineItem>(sortBy: [SortDescriptor(\.createdAt)])
        guard let cached = try? context.fetch(descriptor), !cached.isEmpty else { return }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let decoded = cached.compactMap { item -> MobileTimelineItem? in
            guard let data = item.payloadText.data(using: .utf8) else { return nil }
            return try? decoder.decode(MobileTimelineItem.self, from: data)
        }
        if !decoded.isEmpty {
            timeline = decoded
            isStale = true
        }
    }

    func loadInitial(context: ModelContext?) async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let bootstrapTask: MobileBootstrap = api.request("/mobile/bootstrap")
            async let messagesTask: MobileMessagesResponse = api.request("/mobile/messages")
            async let timelineTask: MobileTimelineResponse = api.request("/mobile/timeline")
            let loadedBootstrap = try await bootstrapTask
            let loadedMessages = try await messagesTask
            let loadedTimeline = try await timelineTask
            bootstrap = loadedBootstrap
            mode = loadedBootstrap.mode
            if let preferences = loadedBootstrap.proactive["preferences"]?.objectValue {
                proactivePreferences = ProactivePreferences(json: preferences)
            }
            messages = loadedMessages.items
            timeline = loadedTimeline.items
            timelineCursor = loadedTimeline.nextCursor ?? loadedBootstrap.timelineCursor
            proactiveCursor = (loadedBootstrap.proactive["cursor"]?.stringValue)
            isStale = false
            if let context {
                cacheMessages(loadedMessages.items, in: context)
                cacheTimeline(loadedTimeline.items, in: context)
            }
        } catch {
            lastError = error.localizedDescription
            isStale = !timeline.isEmpty
        }
    }

    func refreshTimeline(context: ModelContext?) async {
        do {
            let response: MobileTimelineResponse = try await api.request("/mobile/timeline")
            timeline = response.items
            timelineCursor = response.nextCursor
            isStale = false
            if let context {
                cacheTimeline(response.items, in: context)
            }
        } catch {
            lastError = error.localizedDescription
            isStale = !timeline.isEmpty
        }
    }

    func refreshStatus() async {
        do {
            let response: MobileStatusResponse = try await api.request("/mobile/status")
            statusText = response.text
            mode = response.mode
        } catch {
            lastError = error.localizedDescription
        }
    }

    func setMode(_ newMode: String, learningMode: Bool, customModel: String? = nil) async {
        do {
            struct Body: Encodable {
                var mode: String
                var learningMode: Bool
                var customModel: String?
            }
            mode = try await api.request(
                "/mobile/mode",
                method: "POST",
                body: Body(mode: newMode, learningMode: learningMode, customModel: customModel)
            )
        } catch {
            lastError = error.localizedDescription
        }
    }

    func send(context: ModelContext?) async {
        let content = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        let uploadIds = activeUploads.map(\.uploadUid)
        guard !content.isEmpty || !uploadIds.isEmpty else { return }
        draft = ""
        streamingAssistantText = ""
        isStreaming = true
        latestPlan = nil
        let clientMessageId = "ios-\(UUID().uuidString)"
        let localMessage = MobileMessage(
            id: -Int(Date().timeIntervalSince1970 * 1000),
            platform: "mobile",
            conversationId: bootstrap?.activeScope?.conversationId ?? "",
            sessionId: "ios",
            platformMessageId: clientMessageId,
            senderType: "user",
            authorId: "mobile-user",
            userId: bootstrap?.activeScope?.userId ?? "",
            channelId: bootstrap?.activeScope?.channelId ?? "mobile",
            guildId: nil,
            replyToPlatformMessageId: nil,
            threadId: nil,
            content: content.isEmpty ? "我发了一个附件给你。" : content,
            metadata: [:],
            createdAt: ISO8601DateFormatter().string(from: .now)
        )
        messages.append(localMessage)
        timeline.append(localTimelineItem(from: localMessage, uploads: activeUploads))

        let body = MobileChatRequest(
            content: content,
            clientMessageId: clientMessageId,
            attachmentUids: uploadIds,
            displayName: AppConfig.appName,
            toolOverrides: toolOverrides,
            clientScene: bootstrap?.sceneState?.key,
            clientTimezone: TimeZone.current.identifier,
            metadata: ["source": .string("ios")]
        )
        do {
            for try await event in stream.streamChat(body) {
                handle(event)
            }
            activeUploads.removeAll()
            selectedTool = .auto
            let refreshed: MobileMessagesResponse = try await api.request("/mobile/messages")
            let refreshedTimeline: MobileTimelineResponse = try await api.request("/mobile/timeline")
            messages = refreshed.items
            timeline = refreshedTimeline.items
            timelineCursor = refreshedTimeline.nextCursor
            isStale = false
            if let context {
                cacheMessages(refreshed.items, in: context)
                cacheTimeline(refreshedTimeline.items, in: context)
            }
        } catch {
            lastError = error.localizedDescription
            isStale = !timeline.isEmpty
        }
        isStreaming = false
    }

    func upload(files: [FileUpload]) async {
        do {
            let response = try await upload.upload(files)
            activeUploads.append(response)
        } catch {
            lastError = error.localizedDescription
        }
    }

    func removeUpload(_ uploadUid: String) {
        activeUploads.removeAll { $0.uploadUid == uploadUid }
    }

    func pollProactive() async {
        do {
            let query = proactiveCursor.map { [URLQueryItem(name: "after", value: $0)] } ?? []
            let response: MobileProactiveResponse = try await api.request("/mobile/proactive", query: query)
            proactiveCursor = response.cursor
            for item in response.items.reversed() {
                await notifications.notify(proactive: item)
            }
        } catch {
            lastError = error.localizedDescription
        }
    }

    func refreshProactivePreferences() async {
        do {
            let response: MobileProactivePreferencesResponse = try await api.request("/mobile/proactive/preferences")
            proactivePreferences = response.preferences
        } catch {
            lastError = error.localizedDescription
        }
    }

    func setProactivePreferences(enabled: Bool? = nil, cadence: String? = nil) async {
        struct Body: Encodable {
            var enabled: Bool?
            var cadence: String?
        }
        do {
            let response: MobileProactivePreferencesResponse = try await api.request(
                "/mobile/proactive/preferences",
                method: "PATCH",
                body: Body(enabled: enabled, cadence: cadence)
            )
            proactivePreferences = response.preferences
        } catch {
            lastError = error.localizedDescription
        }
    }

    private func handle(_ event: ChatStreamEvent) {
        switch event.event {
        case "plan":
            latestPlan = event
        case "delta":
            streamingAssistantText = event.fullText ?? (streamingAssistantText + (event.text ?? ""))
        case "final":
            streamingAssistantText = event.text ?? streamingAssistantText
        case "error":
            lastError = event.message ?? "回复失败"
        default:
            break
        }
    }

    private var toolOverrides: MobileToolOverrides {
        switch selectedTool {
        case .auto:
            return MobileToolOverrides(search: nil, draw: nil)
        case .search:
            return MobileToolOverrides(search: true, draw: nil)
        case .draw:
            return MobileToolOverrides(search: nil, draw: true)
        }
    }

    private func localTimelineItem(from message: MobileMessage, uploads: [MobileAttachmentUploadResponse]) -> MobileTimelineItem {
        MobileTimelineItem(
            id: "local:\(message.platformMessageId ?? UUID().uuidString)",
            kind: "message",
            createdAt: message.createdAt,
            content: message.content,
            senderLabel: "你",
            messageId: message.id,
            proactiveUid: nil,
            attachments: uploads.flatMap { upload in
                upload.items.map {
                    MobileTimelineAttachment(
                        uploadUid: upload.uploadUid,
                        filename: $0.filename,
                        artifactType: $0.artifactType,
                        contentType: $0.contentType,
                        summaryText: $0.summaryText,
                        metadata: $0.metadata
                    )
                }
            },
            generatedImageUrl: nil,
            feedback: [:],
            metadata: ["sender_type": .string("user"), "source": .string("ios-local")]
        )
    }

    private func cacheMessages(_ messages: [MobileMessage], in context: ModelContext) {
        if let existing = try? context.fetch(FetchDescriptor<CachedMessage>()) {
            for item in existing {
                context.delete(item)
            }
        }
        for message in messages {
            let cached = CachedMessage(
                id: message.id,
                senderType: message.senderType,
                content: message.content,
                createdAt: message.createdAt
            )
            context.insert(cached)
        }
        try? context.save()
    }

    private func cacheTimeline(_ items: [MobileTimelineItem], in context: ModelContext) {
        if let existing = try? context.fetch(FetchDescriptor<CachedTimelineItem>()) {
            for item in existing {
                context.delete(item)
            }
        }
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        for item in items {
            let payload = (try? encoder.encode(item)).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
            context.insert(
                CachedTimelineItem(
                    id: item.id,
                    kind: item.kind,
                    createdAt: item.createdAt,
                    senderLabel: item.senderLabel,
                    content: item.content,
                    payloadText: payload
                )
            )
        }
        try? context.save()
    }
}
