import SwiftData
import SwiftUI

struct RootView: View {
    @State private var router = RouterPath()

    var body: some View {
        @Bindable var router = router
        NavigationStack(path: $router.path) {
            HomeView(router: router)
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .settings:
                        SettingsView(router: router)
                    case .controlCenter:
                        ControlCenterView(router: router)
                    case .dashboardPanel(let panel):
                        DashboardPanelView(panel: panel)
                    }
                }
        }
        .sheet(item: $router.sheet) { sheet in
            switch sheet {
            case .mode:
                ModeSheet()
                    .presentationDetents([.medium])
            case .status:
                StatusSheet()
                    .presentationDetents([.medium, .large])
            case .attachmentPicker:
                AttachmentImportSheet()
            case .voiceRecorder:
                VoiceRecorderSheet()
                    .presentationDetents([.medium])
            case .error(let message):
                ErrorSheet(message: message)
                    .presentationDetents([.height(180)])
            }
        }
    }
}
