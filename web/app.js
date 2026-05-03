const statusEl = document.querySelector("#status");
const connectButton = document.querySelector("#connect");
const disconnectButton = document.querySelector("#disconnect");
const resetButton = document.querySelector("#reset");
const eventsEl = document.querySelector("#events");
const agentRunsEl = document.querySelector("#agent-runs");
const usageEl = document.querySelector("#usage");
const logsEl = document.querySelector("#logs");
const remoteAudioEl = document.querySelector("#remote-audio");

let room = null;
let lastEventId = null;
const conversationTypes = new Set([
  "transcript.final",
  "stt.result",
  "capture.started",
  "capture.buffered",
  "capture.submitted",
  "capture.cancelled",
  "route.result",
  "agent_backend.dispatched",
  "agent_backend.done",
  "agent_backend.failed",
  "stt.empty",
  "stt.error",
  "tts.error",
]);

function log(message) {
  const timestamp = new Date().toLocaleTimeString();
  logsEl.textContent = `[${timestamp}] ${message}\n${logsEl.textContent}`;
}

async function connect() {
  const tokenPayload = await fetchJson("/api/token");
  room = new LivekitClient.Room();
  room.on(LivekitClient.RoomEvent.Connected, () => {
    statusEl.textContent = `Connected to ${tokenPayload.room} as ${tokenPayload.identity}`;
    connectButton.disabled = true;
    disconnectButton.disabled = false;
  });
  room.on(LivekitClient.RoomEvent.Disconnected, () => {
    statusEl.textContent = "Disconnected";
    connectButton.disabled = false;
    disconnectButton.disabled = true;
    remoteAudioEl.replaceChildren();
  });
  room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication, participant) => {
    attachRemoteAudio(track, publication, participant);
  });
  room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
    detachRemoteAudio(track);
  });

  await room.connect(tokenPayload.url, tokenPayload.token);
  if (typeof room.startAudio === "function") {
    await room.startAudio();
  }
  attachExistingRemoteAudio();
  const track = await LivekitClient.createLocalAudioTrack();
  await room.localParticipant.publishTrack(track);
  log("microphone published");
}

async function disconnect() {
  if (room) {
    room.disconnect();
    room = null;
  }
}

async function refresh() {
  const eventsUrl = lastEventId ? `/api/events?after=${encodeURIComponent(lastEventId)}` : "/api/events";
  const eventsPayload = await fetchJson(eventsUrl);
  for (const event of eventsPayload.events) {
    appendEvent(event);
    lastEventId = event.id;
  }

  const agentRunsPayload = await fetchJson("/api/agent-runs");
  agentRunsEl.replaceChildren(...agentRunsPayload.agent_runs.slice(0, 20).map(renderAgentRun));

  const month = new Date().toISOString().slice(0, 7);
  const usagePayload = await fetchJson(`/api/usage?month=${month}`);
  usageEl.textContent = JSON.stringify(usagePayload.summary, null, 2);
}

function appendEvent(event) {
  if (!conversationTypes.has(event.type)) {
    return;
  }
  const item = document.createElement("li");
  item.className = "conversation-event";
  item.append(...renderConversationEvent(event));
  eventsEl.prepend(item);
}

function renderConversationEvent(event) {
  const time = formatEventTime(event.created_at);
  if (event.type === "transcript.final") {
    return [renderEventHeader("You", time), renderEventMessage(event.payload.text, "event-user")];
  }
  if (event.type === "stt.result") {
    return [renderEventHeader("STT recognized", time), renderEventMessage(event.payload.text, "event-stt")];
  }
  if (event.type === "capture.started") {
    return [renderEventHeader("Capture started", time), renderEventMessage(event.payload.buffer || "Recording command", "event-capture")];
  }
  if (event.type === "capture.buffered") {
    return [renderEventHeader("Capture buffered", time), renderEventMessage(event.payload.buffer || event.payload.text, "event-capture")];
  }
  if (event.type === "capture.submitted") {
    return [renderEventHeader("Capture submitted", time), renderEventMessage(event.payload.prompt, "event-user")];
  }
  if (event.type === "capture.cancelled") {
    return [renderEventHeader("Capture cancelled", time), renderEventMessage(event.payload.reason || "cancelled", "event-error")];
  }
  if (event.type === "route.result") {
    return [renderEventHeader("Agent", time), renderEventMessage(event.payload.reply, "event-agent")];
  }
  if (event.type === "agent_backend.dispatched") {
    return [renderEventHeader(`You -> ${event.payload.backend}`, time), renderEventMessage(event.payload.text, "event-user")];
  }
  if (event.type === "agent_backend.done") {
    return [renderEventHeader(`${event.payload.backend} -> You`, time), renderEventMessage(event.payload.reply, "event-agent")];
  }
  if (event.type === "agent_backend.failed") {
    return [renderEventHeader(`${event.payload.backend} error`, time), renderEventMessage(event.payload.error, "event-error")];
  }
  if (event.type === "stt.empty") {
    return [renderEventHeader("STT", time), renderEventMessage(`No transcript (${event.payload.seconds}s)`, "event-stt")];
  }
  if (event.type === "stt.error") {
    return [renderEventHeader("STT error", time), renderEventMessage(event.payload.error, "event-error")];
  }
  if (event.type === "tts.error") {
    return [renderEventHeader("TTS error", time), renderEventMessage(event.payload.error, "event-error")];
  }
  return [renderEventHeader(event.type, time), renderEventMessage(JSON.stringify(event.payload, null, 2), "event-stt")];
}

function renderEventHeader(label, time) {
  const header = document.createElement("div");
  header.className = "event-header";
  header.textContent = `${label} · ${time}`;
  return header;
}

function renderEventMessage(text, className) {
  const message = document.createElement("div");
  message.className = `event-message ${className}`;
  message.textContent = text || "";
  return message;
}

function formatEventTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString();
}

function renderAgentRun(run) {
  const item = document.createElement("li");
  item.className = `run run-${run.status}`;
  const duration = run.duration_seconds === null || run.duration_seconds === undefined ? "" : ` · ${run.duration_seconds}s`;
  const header = document.createElement("div");
  header.className = "run-header";
  header.textContent = `${run.status} · ${run.backend}/${run.model}${duration}`;

  const prompt = document.createElement("div");
  prompt.className = "run-message run-prompt";
  prompt.textContent = `You: ${run.prompt}`;

  item.append(header, prompt);

  if (run.reply) {
    const reply = document.createElement("div");
    reply.className = "run-message run-reply";
    reply.textContent = `Agent: ${run.reply}`;
    item.append(reply);
  }

  if (run.error) {
    const error = document.createElement("div");
    error.className = "run-message run-error";
    error.textContent = `Error: ${run.error}`;
    item.append(error);
  }

  return item;
}

function attachRemoteAudio(track, publication, participant) {
  if (!isAudioTrack(track)) {
    return;
  }
  const trackSid = publication?.trackSid || publication?.sid || track.sid || "";
  if (trackSid && remoteAudioEl.querySelector(`[data-track-sid="${trackSid}"]`)) {
    return;
  }
  const element = track.attach();
  element.autoplay = true;
  element.playsInline = true;
  element.dataset.trackSid = trackSid;
  element.dataset.participantIdentity = participant?.identity || "";
  remoteAudioEl.appendChild(element);
  log(`remote audio attached from ${participant?.identity || "unknown"}`);
}

function attachExistingRemoteAudio() {
  for (const participant of room.remoteParticipants.values()) {
    for (const publication of participant.trackPublications.values()) {
      if (publication.track) {
        attachRemoteAudio(publication.track, publication, participant);
      }
    }
  }
}

function detachRemoteAudio(track) {
  if (!track || typeof track.detach !== "function") {
    return;
  }
  for (const element of track.detach()) {
    element.remove();
  }
}

function isAudioTrack(track) {
  return String(track?.kind || "").toLowerCase().endsWith("audio");
}

async function resetDemoState() {
  await fetchJson("/api/reset", { method: "POST" });
  lastEventId = null;
  eventsEl.replaceChildren();
  agentRunsEl.replaceChildren();
  usageEl.textContent = "{}";
  log("demo state cleared");
}

async function fetchJson(path, options) {
  const response = await fetch(path, { cache: "no-store", ...(options || {}) });
  if (!response.ok) {
    throw new Error(`${path} failed with ${response.status}`);
  }
  return response.json();
}

connectButton.addEventListener("click", () => connect().catch((error) => log(error.message)));
disconnectButton.addEventListener("click", () => disconnect().catch((error) => log(error.message)));
resetButton.addEventListener("click", () => resetDemoState().catch((error) => log(error.message)));
setInterval(() => refresh().catch((error) => log(error.message)), 1000);
refresh().catch((error) => log(error.message));
