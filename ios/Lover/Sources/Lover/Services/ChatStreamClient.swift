import Foundation
import Observation

struct SSEParser {
    private var eventName: String?
    private var dataLines: [String] = []
    private let decoder: JSONDecoder

    init(decoder: JSONDecoder) {
        self.decoder = decoder
    }

    mutating func consume(line: String) throws -> ChatStreamEvent? {
        if line.isEmpty {
            return try flush()
        }
        if line.hasPrefix("event:") {
            eventName = String(line.dropFirst("event:".count)).trimmingCharacters(in: .whitespaces)
            return nil
        }
        if line.hasPrefix("data:") {
            dataLines.append(String(line.dropFirst("data:".count)).trimmingCharacters(in: .whitespaces))
        }
        return nil
    }

    mutating func flush() throws -> ChatStreamEvent? {
        guard !dataLines.isEmpty else {
            eventName = nil
            return nil
        }
        let dataString = dataLines.joined(separator: "\n")
        dataLines.removeAll()
        let data = Data(dataString.utf8)
        var event = try decoder.decode(ChatStreamEvent.self, from: data)
        if event.event.isEmpty {
            event = ChatStreamEvent(
                event: eventName ?? "message",
                requestId: event.requestId,
                turnUid: event.turnUid,
                text: event.text,
                fullText: event.fullText,
                message: event.message,
                modelName: event.modelName,
                fallbackUsed: event.fallbackUsed,
                userMessageId: event.userMessageId,
                assistantMessageId: event.assistantMessageId,
                generatedImagePath: event.generatedImagePath,
                imageUrl: event.imageUrl,
                latencyMs: event.latencyMs,
                requestType: event.requestType,
                scene: event.scene,
                replyGoal: event.replyGoal,
                shouldSearch: event.shouldSearch,
                shouldDraw: event.shouldDraw
            )
        }
        eventName = nil
        return event
    }
}

@Observable
final class ChatStreamClient {
    private let api: MobileAPIClient

    init(api: MobileAPIClient) {
        self.api = api
    }

    func streamChat(_ body: MobileChatRequest) -> AsyncThrowingStream<ChatStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    var request = URLRequest(url: api.makeURL("/mobile/chat/stream"))
                    request.httpMethod = "POST"
                    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    api.applyMobileAuthorization(to: &request)
                    request.httpBody = try api.encoder.encode(body)

                    let (bytes, response) = try await URLSession.shared.bytes(for: request)
                    guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
                    guard (200..<300).contains(http.statusCode) else { throw APIError.badStatus(http.statusCode, "") }

                    var parser = SSEParser(decoder: api.decoder)
                    for try await line in bytes.lines {
                        if let event = try parser.consume(line: line) {
                            continuation.yield(event)
                        }
                    }
                    if let event = try parser.flush() {
                        continuation.yield(event)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }
}
