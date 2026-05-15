import AVFoundation
import SwiftUI
import UniformTypeIdentifiers

struct ModeSheet: View {
    @Environment(ChatStore.self) private var chat
    @Environment(\.dismiss) private var dismiss
    @State private var selectedMode = "auto"
    @State private var learningMode = false
    @State private var customModel = ""

    var body: some View {
        NavigationStack {
            Form {
                Picker("模式", selection: $selectedMode) {
                    Text("自动").tag("auto")
                    Text("快速").tag("fast")
                    Text("思考").tag("think")
                    Text("自定义").tag("custom")
                }
                .pickerStyle(.segmented)
                Toggle("学习模式", isOn: $learningMode)
                if selectedMode == "custom" {
                    TextField("模型", text: $customModel)
                        .textInputAutocapitalization(.never)
                }
            }
            .navigationTitle("模式")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") {
                        Task {
                            await chat.setMode(selectedMode, learningMode: learningMode, customModel: customModel.isEmpty ? nil : customModel)
                            dismiss()
                        }
                    }
                }
            }
            .onAppear {
                selectedMode = chat.mode.mode
                learningMode = chat.mode.learningMode
                customModel = chat.mode.customModel ?? ""
            }
        }
    }
}

struct StatusSheet: View {
    @Environment(ChatStore.self) private var chat

    var body: some View {
        NavigationStack {
            ScrollView {
                Text(chat.statusText.isEmpty ? "正在读取" : chat.statusText)
                    .font(.body)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                    .padding()
            }
            .navigationTitle("状态")
            .navigationBarTitleDisplayMode(.inline)
            .task {
                await chat.refreshStatus()
            }
        }
    }
}

struct ErrorSheet: View {
    let message: String

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "exclamationmark.triangle")
                .font(.title2)
                .foregroundStyle(.orange)
            Text(message)
                .font(.body)
                .multilineTextAlignment(.center)
        }
        .padding()
    }
}

struct AttachmentImportSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ContentUnavailableView("附件", systemImage: "paperclip")
            .onAppear {
                dismiss()
            }
    }
}

struct VoiceRecorderSheet: View {
    @Environment(ChatStore.self) private var chat
    @Environment(\.dismiss) private var dismiss
    @State private var recorder: AVAudioRecorder?
    @State private var isRecording = false
    @State private var elapsed: TimeInterval = 0
    @State private var timer: Timer?

    var body: some View {
        VStack(spacing: 22) {
            Image(systemName: isRecording ? "waveform.circle.fill" : "mic.circle")
                .font(.system(size: 68))
                .foregroundStyle(isRecording ? .red : Color.accentColor)
            Text(timeString)
                .font(.title2.monospacedDigit())
            HStack(spacing: 18) {
                Button {
                    if isRecording {
                        stopAndUpload()
                    } else {
                        start()
                    }
                } label: {
                    Image(systemName: isRecording ? "stop.fill" : "record.circle")
                        .font(.system(size: 22, weight: .semibold))
                        .frame(width: 58, height: 48)
                }
                .buttonStyle(.borderedProminent)
                Button {
                    cancel()
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 18, weight: .semibold))
                        .frame(width: 58, height: 48)
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(24)
        .onDisappear {
            timer?.invalidate()
            recorder?.stop()
        }
    }

    private var timeString: String {
        let seconds = Int(elapsed)
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }

    private func start() {
        let permissionHandler: (Bool) -> Void = { granted in
            guard granted else { return }
            Task { @MainActor in
                let session = AVAudioSession.sharedInstance()
                try? session.setCategory(.playAndRecord, mode: .spokenAudio)
                try? session.setActive(true)
                let url = FileManager.default.temporaryDirectory.appendingPathComponent("voice-\(UUID().uuidString).m4a")
                let settings: [String: Any] = [
                    AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
                    AVSampleRateKey: 44_100,
                    AVNumberOfChannelsKey: 1,
                    AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
                ]
                recorder = try? AVAudioRecorder(url: url, settings: settings)
                recorder?.record()
                isRecording = true
                elapsed = 0
                timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
                    elapsed += 1
                }
            }
        }
        if #available(iOS 17.0, *) {
            AVAudioApplication.requestRecordPermission(completionHandler: permissionHandler)
        } else {
            AVAudioSession.sharedInstance().requestRecordPermission(permissionHandler)
        }
    }

    private func stopAndUpload() {
        guard let recorder else { return }
        let url = recorder.url
        recorder.stop()
        timer?.invalidate()
        isRecording = false
        Task {
            if let data = try? Data(contentsOf: url) {
                await chat.upload(files: [FileUpload(data: data, filename: url.lastPathComponent, mimeType: "audio/mp4")])
            }
            dismiss()
        }
    }

    private func cancel() {
        recorder?.stop()
        timer?.invalidate()
        dismiss()
    }
}
