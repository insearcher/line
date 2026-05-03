#!/usr/bin/env bun
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 8790;
const DEFAULT_SENDER = "local-voice";

type AuthOptions = {
  sender: string;
  token: string;
};

type VoiceBody = {
  text: string;
  chat_id: string;
};

type PermissionVerdict = {
  request_id: string;
  behavior: "allow" | "deny";
};

type SseListener = (chunk: string) => void;

const ReplyArgs = z.object({
  chat_id: z.string().min(1).default("voice"),
  text: z.string().min(1),
  status: z.enum(["ack", "progress", "done", "error", "reply"]).default("reply"),
});

const ClaudePermissionRequestSchema = z.object({
  method: z.literal("notifications/claude/channel/permission_request"),
  params: z
    .object({
      request_id: z.string(),
      tool_name: z.string().optional(),
      description: z.string().optional(),
      input_preview: z.unknown().optional(),
    })
    .passthrough(),
});

export function formatSse(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

export async function parseVoiceBody(bodyText: string, contentType: string | null): Promise<VoiceBody> {
  const normalizedContentType = (contentType ?? "").toLowerCase();
  if (normalizedContentType.includes("application/json")) {
    const payload = JSON.parse(bodyText) as Record<string, unknown>;
    const text = typeof payload.text === "string" ? payload.text.trim() : "";
    const chatId = typeof payload.chat_id === "string" ? payload.chat_id.trim() : "voice";
    if (!text) {
      throw new Error("JSON voice payload must contain a non-empty text field");
    }
    return { text, chat_id: chatId || "voice" };
  }

  const text = bodyText.trim();
  if (!text) {
    throw new Error("Voice payload must not be empty");
  }
  return { text, chat_id: "voice" };
}

export function isAuthorizedHeaders(headers: Headers, auth: AuthOptions): boolean {
  const sender = headers.get("x-sender") ?? "";
  if (sender && sender === auth.sender) {
    return true;
  }

  const authorization = headers.get("authorization") ?? "";
  const bearer = authorization.match(/^Bearer\s+(.+)$/i)?.[1] ?? "";
  return Boolean(auth.token) && bearer === auth.token;
}

export function parsePermissionVerdict(text: string): PermissionVerdict | null {
  const match = text.trim().match(/^(allow|deny)\s+([A-Za-z0-9_.:-]+)$/i);
  if (!match) {
    return null;
  }
  return {
    behavior: match[1].toLowerCase() as "allow" | "deny",
    request_id: match[2],
  };
}

function broadcast(listeners: Set<SseListener>, event: string, data: unknown): void {
  const chunk = formatSse(event, data);
  for (const listener of listeners) {
    listener(chunk);
  }
}

function createMcpServer(listeners: Set<SseListener>): Server {
  const server = new Server(
    { name: "line", version: "0.1.0" },
    {
      capabilities: {
        experimental: {
          "claude/channel": {},
          "claude/channel/permission": {},
        },
        tools: {},
      },
      instructions: [
        "Voice messages from the operator arrive as Claude channel events.",
        "They are short Russian or English commands spoken through a local voice UI.",
        "Always call reply_to_voice with the same chat_id for user-facing responses.",
        "Keep replies short because they will be spoken through TTS.",
        "For actionable coding tasks, acknowledge immediately, do the work in this Claude Code session, then call reply_to_voice again with a concise Russian result.",
      ].join(" "),
    },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
      {
        name: "reply_to_voice",
        title: "Reply to voice channel",
        description: "Send a concise user-facing reply back to the local voice UI.",
        inputSchema: {
          type: "object",
          properties: {
            chat_id: {
              type: "string",
              description: "The chat_id from the incoming voice channel event.",
            },
            text: {
              type: "string",
              description: "Short text that will be spoken through TTS.",
            },
            status: {
              type: "string",
              enum: ["ack", "progress", "done", "error", "reply"],
              description: "Optional status label for the voice UI.",
            },
          },
          required: ["chat_id", "text"],
        },
        annotations: {
          title: "Reply to voice",
          readOnlyHint: true,
          destructiveHint: false,
          openWorldHint: false,
        },
      },
    ],
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    if (request.params.name !== "reply_to_voice") {
      return {
        isError: true,
        content: [{ type: "text", text: `Unknown tool: ${request.params.name}` }],
      };
    }

    const args = ReplyArgs.parse(request.params.arguments ?? {});
    broadcast(listeners, "reply", {
      chat_id: args.chat_id,
      text: args.text,
      status: args.status,
      created_at: new Date().toISOString(),
    });
    return {
      content: [{ type: "text", text: "Voice reply delivered." }],
    };
  });

  server.setNotificationHandler(ClaudePermissionRequestSchema as any, async (notification) => {
    broadcast(listeners, "permission_request", {
      ...notification.params,
      created_at: new Date().toISOString(),
    });
  });

  return server;
}

async function sendVoiceMessage(server: Server, body: VoiceBody): Promise<void> {
  const verdict = parsePermissionVerdict(body.text);
  if (verdict) {
    await server.notification({
      method: "notifications/claude/channel/permission",
      params: verdict,
    } as any);
    return;
  }

  await server.notification({
    method: "notifications/claude/channel",
    params: {
      content: body.text,
      meta: {
        chat_id: body.chat_id,
        source: "line_voice",
        medium: "voice",
        created_at: new Date().toISOString(),
      },
    },
  } as any);
}

async function handleHttpRequest(
  request: Request,
  server: Server,
  listeners: Set<SseListener>,
  auth: AuthOptions,
): Promise<Response> {
  const url = new URL(request.url);

  if (request.method === "GET" && url.pathname === "/health") {
    return jsonResponse({ ok: true, service: "claude-voice-channel" });
  }

  if (request.method === "GET" && url.pathname === "/events") {
    return createSseResponse(request, listeners);
  }

  if (request.method === "POST" && url.pathname === "/voice") {
    if (!isAuthorizedHeaders(request.headers, auth)) {
      return jsonResponse({ ok: false, error: "unauthorized" }, 401);
    }
    try {
      const body = await parseVoiceBody(await request.text(), request.headers.get("content-type"));
      await sendVoiceMessage(server, body);
      return jsonResponse({ ok: true, chat_id: body.chat_id });
    } catch (error) {
      return jsonResponse({ ok: false, error: formatError(error) }, 400);
    }
  }

  if (request.method === "POST" && url.pathname === "/permission") {
    if (!isAuthorizedHeaders(request.headers, auth)) {
      return jsonResponse({ ok: false, error: "unauthorized" }, 401);
    }
    try {
      const payload = (await request.json()) as PermissionVerdict;
      const verdict = PermissionVerdictSchema.parse(payload);
      await server.notification({
        method: "notifications/claude/channel/permission",
        params: verdict,
      } as any);
      return jsonResponse({ ok: true });
    } catch (error) {
      return jsonResponse({ ok: false, error: formatError(error) }, 400);
    }
  }

  return jsonResponse({ ok: false, error: "not_found" }, 404);
}

const PermissionVerdictSchema = z.object({
  request_id: z.string().min(1),
  behavior: z.enum(["allow", "deny"]),
});

function createSseResponse(request: Request, listeners: Set<SseListener>): Response {
  const encoder = new TextEncoder();
  let closed = false;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const listener: SseListener = (chunk: string) => {
        if (!closed) {
          controller.enqueue(encoder.encode(chunk));
        }
      };
      listeners.add(listener);
      controller.enqueue(encoder.encode(": connected\n\n"));
      request.signal.addEventListener("abort", () => {
        closed = true;
        listeners.delete(listener);
        try {
          controller.close();
        } catch {
          // The controller can already be closed by the runtime during abort.
        }
      });
    },
  });

  return new Response(stream, {
    headers: {
      "cache-control": "no-cache",
      connection: "keep-alive",
      "content-type": "text/event-stream; charset=utf-8",
    },
  });
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function formatError(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return String(error);
}

export async function main(): Promise<void> {
  const host = process.env.VOICE_CHANNEL_HOST || DEFAULT_HOST;
  const port = Number.parseInt(process.env.VOICE_CHANNEL_PORT || String(DEFAULT_PORT), 10);
  const auth: AuthOptions = {
    sender: process.env.VOICE_CHANNEL_SENDER || DEFAULT_SENDER,
    token: process.env.VOICE_CHANNEL_TOKEN || "",
  };
  const listeners = new Set<SseListener>();
  const server = createMcpServer(listeners);

  Bun.serve({
    hostname: host,
    port,
    fetch: (request) => handleHttpRequest(request, server, listeners, auth),
  });
  console.error(`claude-voice-channel listening on http://${host}:${port}`);

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

if (import.meta.main) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
