import Foundation
import LiveKit

@MainActor
final class VoiceClientViewModel: ObservableObject {
    private static let defaultDemoServerURL = "http://127.0.0.1:8787"

    @Published var demoServerURL = VoiceClientViewModel.initialDemoServerURL()
    @Published var identity = UserDefaults.standard.string(forKey: "voiceIdentity") ?? "iphone-vad"
    @Published var roomOverride = ""
    @Published var pairingCode = ""
    @Published private(set) var status = "Disconnected"
    @Published private(set) var isConnected = false
    @Published private(set) var isPaired = VoiceCredentialStore.authToken != nil
    @Published private(set) var isPublishingSpeech = false
    @Published private(set) var audioLevel: Float = 0
    @Published private(set) var logLines: [String] = []

    private var room: Room?
    private var microphonePublication: LocalTrackPublication?
    private var audioGate: VADAudioGate?

    private static func initialDemoServerURL() -> String {
        UserDefaults.standard.string(forKey: "demoServerURL") ?? defaultDemoServerURL
    }

    var gateStatusText: String {
        guard isConnected else {
            return "Offline"
        }
        return isPublishingSpeech ? "Speech gate open" : "Speech gate closed"
    }

    var connectionStatusText: String {
        isConnected ? "Connected" : "Disconnected"
    }

    var pairingStatusText: String {
        isPaired ? "Paired" : "Pair required"
    }

    var canPair: Bool {
        !pairingCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var isPairedMacLabel: String? {
        guard isPaired, let macDeviceId = VoiceCredentialStore.macDeviceId else {
            return nil
        }
        return String(macDeviceId.prefix(8))
    }

    func pairDevice() async {
        guard let serverURL = URL(string: demoServerURL) else {
            appendLog("Pair failed: invalid demo server URL")
            return
        }
        let code = pairingCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty else {
            appendLog("Pair failed: enter a pairing code")
            return
        }

        UserDefaults.standard.set(demoServerURL, forKey: "demoServerURL")
        UserDefaults.standard.set(identity, forKey: "voiceIdentity")
        status = "Pairing"
        appendLog("Pairing with \(serverURL.absoluteString)")

        do {
            let response = try await TokenClient(serverURL: serverURL).pair(
                code: code,
                deviceName: "line \(identity)"
            )
            try VoiceCredentialStore.save(pairing: response)
            isPaired = true
            pairingCode = ""
            status = isConnected ? "Connected" : "Disconnected"
            appendLog("Paired with Mac \(response.macDeviceId.prefix(8)); phone \(response.phoneId.prefix(8))")
        } catch {
            status = isConnected ? "Connected" : "Pair failed"
            appendLog("Pair failed: \(describe(error))")
        }
    }

    func forgetPairing() {
        VoiceCredentialStore.clear()
        isPaired = false
        appendLog("Pairing cleared")
    }

    func connect() async {
        guard !isConnected else {
            return
        }
        guard let serverURL = URL(string: demoServerURL) else {
            appendLog("Invalid demo server URL")
            return
        }
        guard let authToken = VoiceCredentialStore.authToken else {
            status = "Pair required"
            appendLog("Pair this iPhone before connecting")
            return
        }

        UserDefaults.standard.set(demoServerURL, forKey: "demoServerURL")
        UserDefaults.standard.set(identity, forKey: "voiceIdentity")
        status = "Fetching token"
        appendLog("Fetching token from \(serverURL.absoluteString) for identity \(identity)")

        do {
            let token = try await TokenClient(serverURL: serverURL).fetchToken(
                identity: identity,
                room: roomOverride.isEmpty ? nil : roomOverride,
                authToken: authToken
            )
            status = "Connecting to \(token.room)"
            appendLog("Token received for room \(token.room); connecting to \(token.url)")

            let room = Room()
            self.room = room
            try await room.connect(url: token.url, token: token.token)
            appendLog("LiveKit connected; attaching local audio gate")

            let audioGate = VADAudioGate { [weak self] rms, duration, decision in
                Task { @MainActor [weak self] in
                    self?.handleAudioGate(rms: rms, duration: duration, decision: decision)
                }
            }
            self.audioGate = audioGate
            AudioManager.shared.capturePostProcessingDelegate = audioGate
            appendLog("Audio gate attached")

            let publication = try await room.localParticipant.setMicrophone(enabled: true)
            appendLog("Microphone enabled; non-speech PCM is zeroed locally")
            microphonePublication = publication

            isConnected = true
            isPublishingSpeech = false
            status = "Connected to \(token.room)"
            appendLog("Connected as \(token.identity); microphone is VAD-gated")
        } catch {
            appendLog("Connect failed: \(describe(error))")
            await disconnect()
        }
    }

    func disconnect() async {
        AudioManager.shared.capturePostProcessingDelegate = nil
        audioGate?.reset()
        audioGate = nil
        microphonePublication = nil
        audioLevel = 0
        isPublishingSpeech = false

        await room?.disconnect()
        room = nil
        isConnected = false
        status = "Disconnected"
        appendLog("Disconnected")
    }

    func resetState() async {
        clearLocalVoiceState()
        logLines.removeAll()

        guard let serverURL = URL(string: demoServerURL) else {
            status = isConnected ? "Connected" : "Disconnected"
            appendLog("Reset failed: invalid demo server URL")
            return
        }

        do {
            try await TokenClient(serverURL: serverURL).resetState(authToken: VoiceCredentialStore.authToken)
            status = isConnected ? "Connected" : "Disconnected"
            appendLog("Reset sent")
        } catch {
            status = isConnected ? "Connected" : "Disconnected"
            appendLog("Reset failed: \(describe(error))")
        }
    }

    private func handleAudioGate(rms: Float, duration: TimeInterval, decision: Bool?) {
        audioLevel = smoothedLevel(current: audioLevel, next: Self.displayLevel(forRMS: rms))
        guard isConnected else {
            return
        }
        _ = duration
        guard let decision, decision != isPublishingSpeech else {
            return
        }
        isPublishingSpeech = decision
        appendLog(decision ? "VAD speech start: opening audio gate" : "VAD speech end: closing audio gate")
    }

    private func clearLocalVoiceState() {
        audioGate?.reset()
        audioLevel = 0
        isPublishingSpeech = false
    }

    private func smoothedLevel(current: Float, next: Float) -> Float {
        if next > current {
            return current * 0.35 + next * 0.65
        }
        return current * 0.82 + next * 0.18
    }

    nonisolated static func displayLevel(forRMS rms: Float) -> Float {
        let floor: Float = 0.03
        let ceiling: Float = 0.22
        let normalized = (rms - floor) / (ceiling - floor)
        return min(1, max(0, normalized))
    }

    private func describe(_ error: Error) -> String {
        let localized = error.localizedDescription
        let reflected = String(reflecting: error)
        if localized == reflected {
            return localized
        }
        return "\(localized) [\(reflected)]"
    }

    private func appendLog(_ message: String) {
        let timestamp = Date.now.formatted(date: .omitted, time: .standard)
        print("[line] \(message)")
        logLines.insert("[\(timestamp)] \(message)", at: 0)
        logLines = Array(logLines.prefix(80))
    }
}
