import SwiftUI

@main
struct LineApp: App {
    @StateObject private var model = VoiceClientViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
                .onOpenURL { url in
                    Task { await model.pairFromInvitationURL(url) }
                }
        }
    }
}
