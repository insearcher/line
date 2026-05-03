import AVFoundation
import Foundation
import LiveKit

final class LocalAudioLevelMonitor: NSObject, AudioRenderer, @unchecked Sendable {
    private let callbackQueue = DispatchQueue(label: "codex.voice.local-audio-level")
    private let onLevel: @Sendable (Float, TimeInterval) -> Void

    init(onLevel: @escaping @Sendable (Float, TimeInterval) -> Void) {
        self.onLevel = onLevel
    }

    func render(pcmBuffer: AVAudioPCMBuffer) {
        let rms = Self.rmsLevel(for: pcmBuffer)
        let duration = TimeInterval(pcmBuffer.frameLength) / pcmBuffer.format.sampleRate
        callbackQueue.async { [onLevel] in
            onLevel(rms, duration)
        }
    }

    static func rmsLevel(for buffer: AVAudioPCMBuffer) -> Float {
        guard let channels = buffer.floatChannelData, buffer.frameLength > 0 else {
            return 0
        }

        let frameCount = Int(buffer.frameLength)
        let channelCount = max(1, Int(buffer.format.channelCount))
        var sum: Float = 0
        var sampleCount = 0

        for channelIndex in 0..<channelCount {
            let channel = channels[channelIndex]
            for frameIndex in 0..<frameCount {
                let sample = channel[frameIndex]
                sum += sample * sample
                sampleCount += 1
            }
        }

        guard sampleCount > 0 else {
            return 0
        }
        return sqrt(sum / Float(sampleCount))
    }
}
