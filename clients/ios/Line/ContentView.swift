import SwiftUI

struct ContentView: View {
    @StateObject private var model = VoiceClientViewModel()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                connectionSection
                vadSection
                logSection
            }
            .padding(.horizontal, 20)
            .padding(.top, 28)
            .padding(.bottom, 32)
        }
        .background(Color(.systemBackground))
    }

    private var connectionSection: some View {
        panel {
            HStack(spacing: 10) {
                Image(systemName: model.isConnected ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(model.isConnected ? .green : .secondary)
                    .frame(width: 20, height: 20)
                Text(model.connectionStatusText)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Spacer()
                Text(model.status)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            HStack(spacing: 8) {
                Image(systemName: model.isPaired ? "key.fill" : "key.slash.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(model.isPaired ? .green : .secondary)
                    .frame(width: 18, height: 18)
                Text(model.pairingStatusText)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(model.isPaired ? .green : .secondary)
                Spacer()
                if let mac = model.isPairedMacLabel {
                    Text(mac)
                        .font(.system(size: 12, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            VStack(spacing: 10) {
                field("Demo server URL", text: $model.demoServerURL)
                    .keyboardType(.URL)
                field("Identity", text: $model.identity)
                field("Room override", text: $model.roomOverride)
            }

            HStack(spacing: 10) {
                field("Pairing code", text: $model.pairingCode)
                    .textInputAutocapitalization(.characters)

                actionButton(
                    systemImage: "link.badge.plus",
                    tint: .purple,
                    disabled: !model.canPair,
                    accessibilityLabel: "Pair"
                ) {
                    Task { await model.pairDevice() }
                }

                actionButton(
                    systemImage: "key.slash",
                    tint: .gray,
                    disabled: !model.isPaired,
                    accessibilityLabel: "Forget Pairing"
                ) {
                    model.forgetPairing()
                }
            }

            HStack(spacing: 10) {
                actionButton(
                    systemImage: "dot.radiowaves.left.and.right",
                    tint: .blue,
                    disabled: model.isConnected || !model.isPaired,
                    accessibilityLabel: "Connect"
                ) {
                    Task { await model.connect() }
                }

                actionButton(
                    systemImage: "xmark",
                    tint: .gray,
                    disabled: !model.isConnected,
                    accessibilityLabel: "Disconnect"
                ) {
                    Task { await model.disconnect() }
                }

                actionButton(
                    systemImage: "arrow.counterclockwise",
                    tint: .gray,
                    accessibilityLabel: "Reset"
                ) {
                    Task { await model.resetState() }
                }

                Spacer()
            }
        }
    }

    private var vadSection: some View {
        panel {
            Gauge(value: Double(model.audioLevel)) {
                HStack(spacing: 10) {
                    Image(systemName: model.isPublishingSpeech ? "mic.fill" : "mic.slash.fill")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(model.isPublishingSpeech ? .green : .secondary)
                        .frame(width: 22, height: 22)
                    Text("Mic")
                        .font(.system(size: 17, weight: .semibold))
                    Spacer()
                    Text(model.isPublishingSpeech ? "Sending" : model.isConnected ? "Gated" : "Offline")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(model.isPublishingSpeech ? .green : .secondary)
                        .textCase(.uppercase)
                }
            } currentValueLabel: {
                Text("\(Int(model.audioLevel * 100))%")
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            .gaugeStyle(.accessoryLinearCapacity)
            .tint(model.isPublishingSpeech ? .green : .blue)

            Text(model.gateStatusText)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }

    private var logSection: some View {
        panel {
            if model.logLines.isEmpty {
                Text("No local events")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(.secondary)
            } else {
                Text("Events")
                    .font(.system(size: 17, weight: .semibold))
                ForEach(Array(model.logLines.prefix(8).enumerated()), id: \.offset) { _, line in
                    Text(line)
                        .font(.system(size: 12, weight: .regular, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("line")
                .font(.system(size: 34, weight: .bold))
                .lineLimit(1)
                .minimumScaleFactor(0.8)
            Text(model.isConnected ? "Ready for marker capture" : "Connect to start listening")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func field(_ placeholder: String, text: Binding<String>) -> some View {
        TextField(placeholder, text: text)
            .font(.system(size: 16))
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .padding(.horizontal, 12)
            .frame(height: 42)
            .background(Color(.tertiarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func actionButton(
        systemImage: String,
        tint: Color,
        disabled: Bool = false,
        accessibilityLabel: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: 20, weight: .semibold))
                .frame(width: 52, height: 42)
        }
        .buttonStyle(.plain)
        .foregroundStyle(disabled ? Color.secondary : Color.white)
        .background(disabled ? Color(.tertiarySystemFill) : tint)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .disabled(disabled)
        .accessibilityLabel(Text(accessibilityLabel))
    }

    private func panel<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            content()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

#Preview {
    ContentView()
}
