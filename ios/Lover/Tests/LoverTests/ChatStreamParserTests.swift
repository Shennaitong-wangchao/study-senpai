import XCTest
@testable import Lover

final class ChatStreamParserTests: XCTestCase {
    func testParsesServerSentEvent() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        var parser = SSEParser(decoder: decoder)

        XCTAssertNil(try parser.consume(line: "event: delta"))
        XCTAssertNil(try parser.consume(line: #"data: {"event":"delta","text":"知微","full_text":"知微"}"#))
        let event = try parser.consume(line: "")

        XCTAssertEqual(event?.event, "delta")
        XCTAssertEqual(event?.text, "知微")
        XCTAssertEqual(event?.fullText, "知微")
    }

    func testDecodesMixedTimeline() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let data = Data(
            """
            {
              "items": [
                {
                  "id": "message:1",
                  "kind": "message",
                  "created_at": "2026-04-27T00:00:00Z",
                  "content": "在",
                  "sender_label": "学姐",
                  "message_id": 1,
                  "attachments": [],
                  "feedback": {},
                  "metadata": {"sender_type": "assistant"}
                },
                {
                  "id": "proactive:p1",
                  "kind": "proactive",
                  "created_at": "2026-04-27T00:01:00Z",
                  "content": "我在这儿。",
                  "sender_label": "学姐",
                  "proactive_uid": "p1",
                  "attachments": [],
                  "feedback": {"status": "sent"},
                  "metadata": {}
                }
              ],
              "has_more": false,
              "refreshed_at": "2026-04-27T00:02:00Z"
            }
            """.utf8
        )

        let response = try decoder.decode(MobileTimelineResponse.self, from: data)

        XCTAssertEqual(response.items.count, 2)
        XCTAssertTrue(response.items[1].isProactive)
        XCTAssertEqual(response.items[0].senderLabel, "学姐")
    }

    @MainActor
    func testSceneSelectionUsesBackendScene() {
        let service = SceneAssetService()
        let bootstrap = MobileBootstrap(
            activeScope: nil,
            mode: ModeState(),
            profile: CompanionProfile(appName: "Lover", displayName: "学姐", relationshipLabel: "学姐陪伴", tone: "温柔"),
            sceneState: MobileSceneState(key: "rain", assetName: "scene-rain", statusLine: "雨声很轻。", reason: "weather", updatedAt: "2026-04-27T00:00:00Z"),
            timelineCursor: nil,
            dashboardGroups: [],
            presence: [:],
            companionDay: [:],
            proactive: [:],
            realityContext: [:],
            featureFlags: MobileFeatureFlags(
                streamingChat: true,
                attachments: true,
                voiceTranscription: true,
                imageGeneration: true,
                localNotifications: true,
                apns: false,
                authenticationRequired: false,
                httpsRequired: false,
                deviceContextSync: true,
                nativeDashboard: true
            ),
            refreshedAt: "2026-04-27T00:00:00Z"
        )

        service.refresh(bootstrap: bootstrap)

        XCTAssertEqual(service.currentScene, .rain)
        XCTAssertEqual(service.statusLine, "雨声很轻。")
    }
}
