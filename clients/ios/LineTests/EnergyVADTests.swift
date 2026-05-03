import XCTest
@testable import Line

final class EnergyVADTests: XCTestCase {
    func testStartsAfterConfiguredLoudFrameCount() {
        var vad = EnergyVAD(
            configuration: EnergyVADConfiguration(
                startThreshold: 0.5,
                stopThreshold: 0.2,
                startFrameCount: 2,
                hangoverMilliseconds: 300
            )
        )

        XCTAssertNil(vad.process(rms: 0.6, duration: 0.02))
        XCTAssertEqual(vad.process(rms: 0.7, duration: 0.02), true)
        XCTAssertTrue(vad.isSpeechActive)
    }

    func testDoesNotStartOnIntermittentNoise() {
        var vad = EnergyVAD(
            configuration: EnergyVADConfiguration(
                startThreshold: 0.5,
                stopThreshold: 0.2,
                startFrameCount: 2,
                hangoverMilliseconds: 300
            )
        )

        XCTAssertNil(vad.process(rms: 0.6, duration: 0.02))
        XCTAssertNil(vad.process(rms: 0.1, duration: 0.02))
        XCTAssertNil(vad.process(rms: 0.6, duration: 0.02))
        XCTAssertFalse(vad.isSpeechActive)
    }

    func testStopsAfterHangoverBelowStopThreshold() {
        var vad = EnergyVAD(
            configuration: EnergyVADConfiguration(
                startThreshold: 0.5,
                stopThreshold: 0.2,
                startFrameCount: 1,
                hangoverMilliseconds: 100
            )
        )

        XCTAssertEqual(vad.process(rms: 0.7, duration: 0.02), true)
        XCTAssertNil(vad.process(rms: 0.1, duration: 0.04))
        XCTAssertNil(vad.process(rms: 0.1, duration: 0.04))
        XCTAssertEqual(vad.process(rms: 0.1, duration: 0.04), false)
        XCTAssertFalse(vad.isSpeechActive)
    }

    func testDefaultConfigurationIgnoresSustainedLiveKitNoiseFloor() {
        var vad = EnergyVAD()

        for _ in 0..<20 {
            XCTAssertNil(vad.process(rms: 0.08, duration: 0.1))
        }

        XCTAssertFalse(vad.isSpeechActive)
    }

    func testDefaultConfigurationStartsOnSustainedSpeechLevel() {
        var vad = EnergyVAD()

        XCTAssertNil(vad.process(rms: 0.16, duration: 0.1))
        XCTAssertNil(vad.process(rms: 0.17, duration: 0.1))
        XCTAssertEqual(vad.process(rms: 0.18, duration: 0.1), true)
        XCTAssertTrue(vad.isSpeechActive)
    }

    func testDisplayLevelDoesNotSaturateAtIdleNoiseFloor() {
        XCTAssertEqual(VoiceClientViewModel.displayLevel(forRMS: 0.08), 0.26, accuracy: 0.02)
    }

    func testDisplayLevelSaturatesAtSpeechLevel() {
        XCTAssertEqual(VoiceClientViewModel.displayLevel(forRMS: 0.22), 1, accuracy: 0.01)
    }
}
