import XCTest
@testable import Line

final class GatewayInvitationTests: XCTestCase {
    func testParsesPairingDeepLink() throws {
        let url = try XCTUnwrap(URL(string: "line://pair?serverUrl=http%3A%2F%2F192.0.2.10%3A8787&code=ABCD-2345&macDeviceId=mac-1&expiresAt=2026-05-04T10%3A00%3A00Z"))

        let invitation = try GatewayInvitation(url: url)

        XCTAssertEqual(invitation.serverURL.absoluteString, "http://192.0.2.10:8787")
        XCTAssertEqual(invitation.code, "ABCD-2345")
        XCTAssertEqual(invitation.macDeviceId, "mac-1")
        XCTAssertEqual(invitation.expiresAt, "2026-05-04T10:00:00Z")
    }

    func testRejectsMissingCode() throws {
        let url = try XCTUnwrap(URL(string: "line://pair?serverUrl=http%3A%2F%2F192.0.2.10%3A8787"))

        XCTAssertThrowsError(try GatewayInvitation(url: url))
    }
}
