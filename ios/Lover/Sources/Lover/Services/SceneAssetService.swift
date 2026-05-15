import Foundation
import Observation

enum CompanionScene: String, CaseIterable {
    case morning = "scene-morning"
    case afternoon = "scene-afternoon"
    case rain = "scene-rain"
    case evening = "scene-evening"
    case lateNight = "scene-late-night"
    case focus = "scene-focus"
    case waiting = "scene-waiting"
    case comfort = "scene-comfort"

    var statusLine: String {
        switch self {
        case .morning:
            return "学姐把水杯放在桌边，先陪你把今天稳住。"
        case .afternoon:
            return "午后的光落下来，学姐还在等你一句回声。"
        case .rain:
            return "外面像有雨，学姐把这一会儿替你收得安静些。"
        case .evening:
            return "灯压低一点，学姐把语气也放轻。"
        case .lateNight:
            return "夜里学姐不急着吵你，只把位置留着。"
        case .focus:
            return "学姐把书页摊开了，陪你慢慢进入状态。"
        case .waiting:
            return "学姐没有催你，只是认真地等你回来。"
        case .comfort:
            return "学姐把灯留得很软，先接住你这一刻。"
        }
    }

    static func from(key: String?) -> CompanionScene? {
        guard let key else { return nil }
        let normalized = key.replacingOccurrences(of: "_", with: "-")
        return allCases.first { scene in
            scene.rawValue == normalized || scene.rawValue == "scene-\(normalized)"
        }
    }
}

@Observable
final class SceneAssetService {
    var currentScene: CompanionScene = .morning
    var statusLine: String = CompanionScene.morning.statusLine
    var reason: String = "time"

    func refresh(
        for date: Date = .now,
        bootstrap: MobileBootstrap? = nil,
        isStreaming: Bool = false,
        latestPlan: ChatStreamEvent? = nil,
        hasRecentProactive: Bool = false
    ) {
        if let latestPlan, latestPlan.scene == "情绪安慰" {
            apply(.comfort, reason: "plan", line: CompanionScene.comfort.statusLine)
            return
        }
        if isStreaming {
            apply(.focus, reason: "streaming", line: "学姐正在认真想怎么回你。")
            return
        }
        if hasRecentProactive {
            apply(.waiting, reason: "proactive", line: CompanionScene.waiting.statusLine)
            return
        }
        if let sceneState = bootstrap?.sceneState, let scene = CompanionScene.from(key: sceneState.key) ?? CompanionScene.from(key: sceneState.assetName) {
            apply(scene, reason: sceneState.reason, line: sceneState.statusLine)
            return
        }
        let hour = Calendar.current.component(.hour, from: date)
        let scene: CompanionScene = switch hour {
        case 6..<12: .morning
        case 12..<18: .afternoon
        case 18..<23: .evening
        default: .lateNight
        }
        apply(scene, reason: "time", line: scene.statusLine)
    }

    private func apply(_ scene: CompanionScene, reason: String, line: String) {
        currentScene = scene
        self.reason = reason
        statusLine = line
    }
}
