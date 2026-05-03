import Foundation
import LiveKit

final class VADAudioGate: NSObject, AudioCustomProcessingDelegate, @unchecked Sendable {
    private let callbackQueue = DispatchQueue(label: "codex.voice.vad-audio-gate")
    private let stateLock = NSLock()
    private let onLevel: @Sendable (Float, TimeInterval, Bool?) -> Void

    private var vad = EnergyVAD()
    private var sampleRate = 48_000
    private var isGateOpen = false

    init(onLevel: @escaping @Sendable (Float, TimeInterval, Bool?) -> Void) {
        self.onLevel = onLevel
    }

    func audioProcessingInitialize(sampleRate sampleRateHz: Int, channels: Int) {
        _ = channels
        stateLock.lock()
        sampleRate = sampleRateHz
        vad.reset()
        isGateOpen = false
        stateLock.unlock()
    }

    func audioProcessingProcess(audioBuffer: LKAudioBuffer) {
        let rms = Self.rmsLevel(for: audioBuffer)
        let duration = TimeInterval(audioBuffer.frames) / TimeInterval(max(sampleRate, 1))

        stateLock.lock()
        let decision = vad.process(rms: rms, duration: duration)
        if let decision {
            isGateOpen = decision
        }
        let shouldPassAudio = isGateOpen
        stateLock.unlock()
        if !shouldPassAudio {
            Self.zero(audioBuffer)
        }

        callbackQueue.async { [onLevel] in
            onLevel(rms, duration, decision)
        }
    }

    func audioProcessingRelease() {
        stateLock.lock()
        vad.reset()
        isGateOpen = false
        stateLock.unlock()
    }

    func reset() {
        stateLock.lock()
        vad.reset()
        isGateOpen = false
        stateLock.unlock()
    }

    static func rmsLevel(for audioBuffer: LKAudioBuffer) -> Float {
        let frameCount = audioBuffer.frames
        let channelCount = max(1, audioBuffer.channels)
        guard frameCount > 0 else {
            return 0
        }

        var sum: Float = 0
        var sampleCount = 0

        for channelIndex in 0..<channelCount {
            let channel = audioBuffer.rawBuffer(forChannel: channelIndex)
            for frameIndex in 0..<frameCount {
                let sample = normalizedSample(channel[frameIndex])
                sum += sample * sample
                sampleCount += 1
            }
        }

        guard sampleCount > 0 else {
            return 0
        }
        return sqrt(sum / Float(sampleCount))
    }

    private static func normalizedSample(_ sample: Float) -> Float {
        if abs(sample) <= 1 {
            return sample
        }
        return sample / 32768
    }

    static func zero(_ audioBuffer: LKAudioBuffer) {
        let frameCount = audioBuffer.frames
        let channelCount = max(1, audioBuffer.channels)
        guard frameCount > 0 else {
            return
        }

        for channelIndex in 0..<channelCount {
            let channel = audioBuffer.rawBuffer(forChannel: channelIndex)
            for frameIndex in 0..<frameCount {
                channel[frameIndex] = 0
            }
        }
    }
}
