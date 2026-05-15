import SwiftData
import SwiftUI

@main
struct LoverApp: App {
    @State private var apiClient: MobileAPIClient
    @State private var chatStreamClient: ChatStreamClient
    @State private var uploadClient: UploadClient
    @State private var dashboardClient: DashboardClient
    @State private var deviceContextSync: DeviceContextSyncService
    @State private var localNotifications: LocalNotificationService
    @State private var sceneAssets: SceneAssetService
    @State private var chatStore: ChatStore

    init() {
        let api = MobileAPIClient()
        let stream = ChatStreamClient(api: api)
        let upload = UploadClient(api: api)
        let dashboard = DashboardClient(api: api)
        let deviceContext = DeviceContextSyncService(api: api)
        let notifications = LocalNotificationService()
        let scenes = SceneAssetService()
        _apiClient = State(initialValue: api)
        _chatStreamClient = State(initialValue: stream)
        _uploadClient = State(initialValue: upload)
        _dashboardClient = State(initialValue: dashboard)
        _deviceContextSync = State(initialValue: deviceContext)
        _localNotifications = State(initialValue: notifications)
        _sceneAssets = State(initialValue: scenes)
        _chatStore = State(initialValue: ChatStore(
            api: api,
            stream: stream,
            upload: upload,
            notifications: notifications
        ))
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(apiClient)
                .environment(chatStreamClient)
                .environment(uploadClient)
                .environment(dashboardClient)
                .environment(deviceContextSync)
                .environment(localNotifications)
                .environment(sceneAssets)
                .environment(chatStore)
        }
        .modelContainer(for: [
            CachedMessage.self,
            CachedTimelineItem.self,
            DraftState.self,
            UploadQueueItem.self,
            DashboardFilter.self,
            CachedDashboardPanel.self,
            MobileCursor.self,
            DeviceContextSnapshot.self
        ])
    }
}
