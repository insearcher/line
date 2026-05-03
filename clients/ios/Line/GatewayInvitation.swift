import Foundation

struct GatewayInvitation {
    let serverURL: URL
    let code: String
    let macDeviceId: String?
    let expiresAt: String?

    init(url: URL) throws {
        guard url.scheme == "line", url.host == "pair" else {
            throw GatewayInvitationError.unsupportedURL
        }
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw GatewayInvitationError.unsupportedURL
        }
        let items = Dictionary(uniqueKeysWithValues: (components.queryItems ?? []).compactMap { item in
            item.value.map { (item.name, $0) }
        })
        guard let serverURLValue = items["serverUrl"], let serverURL = URL(string: serverURLValue) else {
            throw GatewayInvitationError.missingServerURL
        }
        guard let code = items["code"], !code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw GatewayInvitationError.missingCode
        }

        self.serverURL = serverURL
        self.code = code
        macDeviceId = items["macDeviceId"]
        expiresAt = items["expiresAt"]
    }
}

enum GatewayInvitationError: Error, LocalizedError {
    case unsupportedURL
    case missingServerURL
    case missingCode

    var errorDescription: String? {
        switch self {
        case .unsupportedURL:
            "Unsupported gateway invitation."
        case .missingServerURL:
            "Gateway invitation is missing the server URL."
        case .missingCode:
            "Gateway invitation is missing the pairing code."
        }
    }
}
