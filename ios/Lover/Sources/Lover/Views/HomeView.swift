import PhotosUI
import SwiftData
import SwiftUI
import UIKit

struct HomeView: View {
    let router: RouterPath

    @Environment(ChatStore.self) private var chat
    @Environment(SceneAssetService.self) private var sceneAssets
    @Environment(LocalNotificationService.self) private var notifications
    @Environment(\.modelContext) private var modelContext
    @State private var selectedPhoto: PhotosPickerItem?
    @State private var showFileImporter = false

    var body: some View {
        @Bindable var chat = chat
        ZStack {
            SceneBackground(scene: sceneAssets.currentScene)
            VStack(spacing: 0) {
                HomeHeader(router: router)
                MessageTimeline()
                ComposerBar(
                    draft: $chat.draft,
                    selectedTool: $chat.selectedTool,
                    selectedPhoto: $selectedPhoto,
                    isStreaming: chat.isStreaming,
                    hasUploads: !chat.activeUploads.isEmpty,
                    uploads: chat.activeUploads,
                    onSend: { Task { await chat.send(context: modelContext) } },
                    onVoice: { router.present(.voiceRecorder) },
                    onFile: { showFileImporter = true },
                    onRemoveUpload: { chat.removeUpload($0) }
                )
            }
        }
        .navigationBarBackButtonHidden()
        .task {
            sceneAssets.refresh(bootstrap: chat.bootstrap, isStreaming: chat.isStreaming, latestPlan: chat.latestPlan, hasRecentProactive: chat.timeline.contains { $0.isProactive })
            chat.loadCachedMessages(from: modelContext)
            await notifications.requestAuthorization()
            await chat.loadInitial(context: modelContext)
            sceneAssets.refresh(bootstrap: chat.bootstrap, isStreaming: chat.isStreaming, latestPlan: chat.latestPlan, hasRecentProactive: chat.timeline.contains { $0.isProactive })
            await chat.refreshStatus()
            await chat.pollProactive()
        }
        .onChange(of: chat.isStreaming) { _, _ in
            sceneAssets.refresh(bootstrap: chat.bootstrap, isStreaming: chat.isStreaming, latestPlan: chat.latestPlan, hasRecentProactive: chat.timeline.contains { $0.isProactive })
        }
        .onChange(of: chat.timeline.count) { _, _ in
            sceneAssets.refresh(bootstrap: chat.bootstrap, isStreaming: chat.isStreaming, latestPlan: chat.latestPlan, hasRecentProactive: chat.timeline.contains { $0.isProactive })
        }
        .onChange(of: selectedPhoto) { _, item in
            guard let item else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self) {
                    await chat.upload(files: [FileUpload(data: data, filename: "photo.jpg", mimeType: "image/jpeg")])
                }
                selectedPhoto = nil
            }
        }
        .fileImporter(
            isPresented: $showFileImporter,
            allowedContentTypes: [.image, .audio, .plainText, .pdf, .item],
            allowsMultipleSelection: false
        ) { result in
            guard case .success(let urls) = result, let url = urls.first else { return }
            Task {
                let didStart = url.startAccessingSecurityScopedResource()
                defer {
                    if didStart { url.stopAccessingSecurityScopedResource() }
                }
                if let data = try? Data(contentsOf: url) {
                    await chat.upload(files: [FileUpload(data: data, filename: url.lastPathComponent, mimeType: url.mimeType)])
                }
            }
        }
    }
}

private struct SceneBackground: View {
    let scene: CompanionScene

    var body: some View {
        Image(scene.rawValue)
            .resizable()
            .scaledToFill()
            .ignoresSafeArea()
            .overlay {
                LinearGradient(
                    colors: [
                        .black.opacity(0.20),
                        .black.opacity(0.10),
                        .black.opacity(0.54)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()
            }
    }
}

private struct HomeHeader: View {
    let router: RouterPath
    @Environment(ChatStore.self) private var chat
    @Environment(SceneAssetService.self) private var sceneAssets

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(chat.bootstrap?.profile.displayName ?? "学姐")
                    .font(.system(size: 22, weight: .semibold))
                Text(sceneAssets.statusLine)
                    .font(.footnote)
                    .lineLimit(2)
                    .foregroundStyle(.white.opacity(0.78))
            }
            Spacer()
            Button {
                router.present(.mode)
            } label: {
                Label(chat.mode.displayMode, systemImage: "slider.horizontal.3")
                    .labelStyle(.iconOnly)
                    .frame(width: 38, height: 38)
            }
            .accessibilityLabel("模式")
            Button {
                router.navigate(to: .settings)
            } label: {
                Image(systemName: "gearshape")
                    .frame(width: 38, height: 38)
            }
            .accessibilityLabel("设置")
        }
        .buttonStyle(.plain)
        .foregroundStyle(.white)
        .padding(.horizontal, 18)
        .padding(.top, 30)
        .padding(.bottom, 10)
    }
}

private struct MessageTimeline: View {
    @Environment(ChatStore.self) private var chat

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 10) {
                    if chat.isStale {
                        StaleBanner()
                    }
                    ForEach(chat.timeline) { item in
                        TimelineBubble(item: item)
                            .id(item.id)
                    }
                    if !chat.streamingAssistantText.isEmpty {
                        StreamingBubble(text: chat.streamingAssistantText)
                            .id("streaming")
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: chat.timeline.count) { _, _ in
                scrollToBottom(proxy)
            }
            .onChange(of: chat.streamingAssistantText) { _, _ in
                scrollToBottom(proxy)
            }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        withAnimation(.easeOut(duration: 0.22)) {
            if !chat.streamingAssistantText.isEmpty {
                proxy.scrollTo("streaming", anchor: .bottom)
            } else if let last = chat.timeline.last {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }
}

private struct StaleBanner: View {
    var body: some View {
        Label("正在显示上次成功同步的内容", systemImage: "clock.arrow.circlepath")
            .font(.caption)
            .foregroundStyle(.white.opacity(0.85))
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(.black.opacity(0.26), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct TimelineBubble: View {
    let item: MobileTimelineItem

    var body: some View {
        HStack {
            if item.isUser { Spacer(minLength: 42) }
            VStack(alignment: .leading, spacing: 8) {
                if item.isProactive {
                    Label("学姐主动放下的一句", systemImage: "bell.badge")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                if !item.content.isEmpty {
                    Text(item.content)
                        .font(.body)
                        .textSelection(.enabled)
                }
                ForEach(item.attachments) { attachment in
                    AttachmentChip(title: attachment.filename, subtitle: attachment.summaryText, type: attachment.artifactType)
                }
                if let imageURL = item.generatedImageUrl {
                    AuthenticatedTimelineImage(imageURL: imageURL)
                        .frame(height: 190)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }
            .foregroundStyle(item.isUser ? .white : Color(.label))
            .padding(.horizontal, 13)
            .padding(.vertical, 10)
            .background(background, in: RoundedRectangle(cornerRadius: 8))
            if !item.isUser { Spacer(minLength: 42) }
        }
    }

    private var background: Color {
        if item.isUser {
            return Color(red: 0.38, green: 0.50, blue: 0.58)
        }
        if item.isProactive {
            return Color(red: 1.0, green: 0.96, blue: 0.88).opacity(0.94)
        }
        return Color.white.opacity(0.92)
    }
}

private struct AuthenticatedTimelineImage: View {
    let imageURL: String

    @State private var image: UIImage?
    @State private var didFail = false

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else if didFail {
                Image(systemName: "photo")
                    .font(.title2)
                    .frame(maxWidth: .infinity)
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity)
            }
        }
        .task(id: imageURL) {
            await load()
        }
    }

    @MainActor
    private func load() async {
        image = nil
        didFail = false
        guard let url = URL(string: imageURL, relativeTo: AppConfig.baseURL) else {
            didFail = true
            return
        }
        var request = URLRequest(url: url)
        MobileAPIClient.applyMobileAuthorization(to: &request)
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
                  let loadedImage = UIImage(data: data) else {
                didFail = true
                return
            }
            image = loadedImage
        } catch {
            didFail = true
        }
    }
}

private struct StreamingBubble: View {
    let text: String

    var body: some View {
        HStack {
            Text(text)
                .font(.body)
                .foregroundStyle(Color(.label))
                .padding(.horizontal, 13)
                .padding(.vertical, 10)
                .background(Color.white.opacity(0.92), in: RoundedRectangle(cornerRadius: 8))
            Spacer(minLength: 42)
        }
    }
}

private struct UploadShelf: View {
    let uploads: [MobileAttachmentUploadResponse]
    var onRemove: (String) -> Void = { _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(uploads, id: \.uploadUid) { upload in
                ForEach(upload.items) { item in
                    HStack(spacing: 8) {
                        AttachmentChip(title: item.filename, subtitle: item.summaryText, type: item.artifactType)
                        Button {
                            onRemove(upload.uploadUid)
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                        }
                        .accessibilityLabel("移除附件")
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct AttachmentChip: View {
    let title: String
    let subtitle: String
    let type: String

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.caption)
                    .lineLimit(1)
                if !subtitle.isEmpty {
                    Text(subtitle)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        } icon: {
            Image(systemName: symbol(for: type))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private func symbol(for type: String) -> String {
        switch type {
        case "image": "photo"
        case "audio": "waveform"
        default: "doc.text"
        }
    }
}

private struct ComposerBar: View {
    @Binding var draft: String
    @Binding var selectedTool: ComposerTool
    @Binding var selectedPhoto: PhotosPickerItem?
    let isStreaming: Bool
    let hasUploads: Bool
    let uploads: [MobileAttachmentUploadResponse]
    let onSend: () -> Void
    let onVoice: () -> Void
    let onFile: () -> Void
    let onRemoveUpload: (String) -> Void

    var body: some View {
        VStack(spacing: 8) {
            if selectedTool != .auto {
                HStack {
                    Label(selectedTool.title, systemImage: selectedTool.systemImage)
                        .font(.caption)
                    Spacer()
                    Button {
                        selectedTool = .auto
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                    }
                    .accessibilityLabel("关闭工具")
                }
                .foregroundStyle(.white.opacity(0.88))
                .padding(.horizontal, 12)
            }
            if !uploads.isEmpty {
                UploadShelf(uploads: uploads, onRemove: onRemoveUpload)
                    .padding(.horizontal, 12)
            }
            HStack(spacing: 8) {
                Menu {
                    Picker("工具", selection: $selectedTool) {
                        ForEach(ComposerTool.allCases) { tool in
                            Label(tool.title, systemImage: tool.systemImage).tag(tool)
                        }
                    }
                } label: {
                    Image(systemName: selectedTool.systemImage)
                        .frame(width: 38, height: 42)
                }
                .accessibilityLabel("工具")
                Button(action: onVoice) {
                    Image(systemName: "mic")
                        .frame(width: 38, height: 42)
                }
                .accessibilityLabel("语音")
                TextField("给学姐发消息", text: $draft, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(Color.white.opacity(0.92), in: RoundedRectangle(cornerRadius: 8))
                PhotosPicker(selection: $selectedPhoto, matching: .images) {
                    Image(systemName: "photo")
                        .frame(width: 34, height: 42)
                }
                .accessibilityLabel("选择图片")
                Button(action: onFile) {
                    Image(systemName: "paperclip")
                        .frame(width: 34, height: 42)
                }
                .accessibilityLabel("文件")
                Button(action: onSend) {
                    Image(systemName: isStreaming ? "hourglass" : "arrow.up")
                        .font(.system(size: 16, weight: .bold))
                        .frame(width: 42, height: 42)
                        .background((draft.isEmpty && !hasUploads) ? Color.white.opacity(0.25) : Color.white.opacity(0.92), in: Circle())
                }
                .disabled(isStreaming || (draft.isEmpty && !hasUploads))
                .accessibilityLabel("发送")
            }
        }
        .buttonStyle(.plain)
        .foregroundStyle(.white)
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(.black.opacity(0.28))
    }
}

private extension URL {
    var mimeType: String {
        let ext = pathExtension.lowercased()
        switch ext {
        case "jpg", "jpeg":
            return "image/jpeg"
        case "png":
            return "image/png"
        case "webp":
            return "image/webp"
        case "gif":
            return "image/gif"
        case "m4a":
            return "audio/mp4"
        case "mp3":
            return "audio/mpeg"
        case "wav":
            return "audio/wav"
        case "pdf":
            return "application/pdf"
        case "docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        case "txt":
            return "text/plain"
        default:
            return "application/octet-stream"
        }
    }
}
