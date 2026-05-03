import Foundation
import Security

struct LiveKitTokenPayload: Decodable {
    let url: String
    let room: String
    let identity: String
    let token: String
}

struct PairingResponse: Decodable {
    let ok: Bool
    let phoneId: String
    let token: String
    let macDeviceId: String
}

struct TokenClient {
    let serverURL: URL

    func fetchToken(identity: String, room: String? = nil, authToken: String?) async throws -> LiveKitTokenPayload {
        let endpoint = serverURL.appending(path: "/api/token")
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        var queryItems = [URLQueryItem(name: "identity", value: identity)]
        if let room, !room.isEmpty {
            queryItems.append(URLQueryItem(name: "room", value: room))
        }
        components?.queryItems = queryItems

        guard let url = components?.url else {
            throw TokenClientError.invalidURL
        }

        var request = URLRequest(url: url)
        request.timeoutInterval = 8
        addAuthorization(to: &request, token: authToken)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(LiveKitTokenPayload.self, from: data)
    }

    func pair(code: String, deviceName: String) async throws -> PairingResponse {
        let endpoint = serverURL.appending(path: "/api/pair")
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 8
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(PairingRequest(code: code, deviceName: deviceName))
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(PairingResponse.self, from: data)
    }

    func resetState(authToken: String?) async throws {
        let endpoint = serverURL.appending(path: "/api/reset")
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 5
        addAuthorization(to: &request, token: authToken)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
    }

    private func addAuthorization(to request: inout URLRequest, token: String?) {
        guard let token, !token.isEmpty else {
            return
        }
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let httpResponse = response as? HTTPURLResponse, (200..<300).contains(httpResponse.statusCode) else {
            let payload = try? JSONDecoder().decode(ErrorResponse.self, from: data)
            throw TokenClientError.serverError(
                payload?.error ?? "Demo server returned a non-success response.",
                (response as? HTTPURLResponse)?.statusCode
            )
        }
    }
}

enum TokenClientError: Error, LocalizedError {
    case invalidURL
    case serverError(String, Int?)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            "Invalid demo server URL."
        case let .serverError(message, statusCode):
            "\(message)\(statusCode.map { " (\($0))" } ?? "")"
        }
    }
}

enum VoiceCredentialStore {
    private static let service = "dev.line.pairing"
    private static let tokenAccount = "authToken"
    private static let phoneIdAccount = "phoneId"
    private static let macDeviceIdAccount = "macDeviceId"

    static var authToken: String? {
        readString(account: tokenAccount)
    }

    static var phoneId: String? {
        readString(account: phoneIdAccount)
    }

    static var macDeviceId: String? {
        readString(account: macDeviceIdAccount)
    }

    static func save(pairing: PairingResponse) throws {
        try saveString(pairing.token, account: tokenAccount)
        try saveString(pairing.phoneId, account: phoneIdAccount)
        try saveString(pairing.macDeviceId, account: macDeviceIdAccount)
    }

    static func clear() {
        delete(account: tokenAccount)
        delete(account: phoneIdAccount)
        delete(account: macDeviceIdAccount)
    }

    private static func readString(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    private static func saveString(_ value: String, account: String) throws {
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecSuccess {
            return
        }
        if updateStatus != errSecItemNotFound {
            throw KeychainError.status(updateStatus)
        }

        var item = query
        attributes.forEach { key, value in item[key] = value }
        let addStatus = SecItemAdd(item as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw KeychainError.status(addStatus)
        }
    }

    private static func delete(account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}

enum KeychainError: Error, LocalizedError {
    case status(OSStatus)

    var errorDescription: String? {
        switch self {
        case let .status(status):
            "Keychain error \(status)."
        }
    }
}

private struct PairingRequest: Encodable {
    let code: String
    let deviceName: String
}

private struct ErrorResponse: Decodable {
    let error: String?
}
