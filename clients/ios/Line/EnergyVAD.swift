import Foundation

struct EnergyVADConfiguration: Equatable {
    var startThreshold: Float = 0.12
    var stopThreshold: Float = 0.04
    var startFrameCount: Int = 3
    var hangoverMilliseconds: Double = 700
}

struct EnergyVAD {
    private(set) var isSpeechActive = false
    private var loudFrameCount = 0
    private var quietMilliseconds: Double = 0
    private let configuration: EnergyVADConfiguration

    init(configuration: EnergyVADConfiguration = EnergyVADConfiguration()) {
        self.configuration = configuration
    }

    mutating func process(rms: Float, duration: TimeInterval) -> Bool? {
        if isSpeechActive {
            if rms <= configuration.stopThreshold {
                quietMilliseconds += duration * 1000
            } else {
                quietMilliseconds = 0
            }

            if quietMilliseconds >= configuration.hangoverMilliseconds {
                isSpeechActive = false
                loudFrameCount = 0
                quietMilliseconds = 0
                return false
            }
            return nil
        }

        if rms >= configuration.startThreshold {
            loudFrameCount += 1
        } else {
            loudFrameCount = 0
        }

        if loudFrameCount >= configuration.startFrameCount {
            isSpeechActive = true
            quietMilliseconds = 0
            return true
        }
        return nil
    }

    mutating func reset() {
        isSpeechActive = false
        loudFrameCount = 0
        quietMilliseconds = 0
    }
}
