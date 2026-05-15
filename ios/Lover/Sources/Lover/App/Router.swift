import Foundation
import Observation

enum Route: Hashable {
    case settings
    case controlCenter
    case dashboardPanel(DashboardPanel)
}

enum SheetDestination: Identifiable {
    case mode
    case status
    case attachmentPicker
    case voiceRecorder
    case error(String)

    var id: String {
        switch self {
        case .mode: "mode"
        case .status: "status"
        case .attachmentPicker: "attachmentPicker"
        case .voiceRecorder: "voiceRecorder"
        case .error(let message): "error-\(message)"
        }
    }
}

@MainActor
@Observable
final class RouterPath {
    var path: [Route] = []
    var sheet: SheetDestination?

    func navigate(to route: Route) {
        path.append(route)
    }

    func present(_ destination: SheetDestination) {
        sheet = destination
    }

    func reset() {
        path = []
        sheet = nil
    }
}
