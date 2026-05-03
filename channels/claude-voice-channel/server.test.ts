import { describe, expect, test } from "bun:test";

import {
  formatSse,
  isAuthorizedHeaders,
  parsePermissionVerdict,
  parseVoiceBody,
} from "./server";

const TEST_AUTH_VALUE = "test-auth-value";

describe("Claude voice channel helpers", () => {
  test("formats named SSE events", () => {
    expect(formatSse("reply", { chat_id: "voice", text: "Done" })).toBe(
      'event: reply\ndata: {"chat_id":"voice","text":"Done"}\n\n',
    );
  });

  test("parses JSON voice payloads", async () => {
    const body = await parseVoiceBody(
      JSON.stringify({ text: "Check tests", chat_id: "run" }),
      "application/json",
    );

    expect(body).toEqual({ text: "Check tests", chat_id: "run" });
  });

  test("parses plain text voice payloads with default chat id", async () => {
    const body = await parseVoiceBody("status", "text/plain");

    expect(body).toEqual({ text: "status", chat_id: "voice" });
  });

  test("accepts sender header or bearer token", () => {
    expect(
      isAuthorizedHeaders(new Headers({ "x-sender": "local-voice" }), {
        sender: "local-voice",
        token: "",
      }),
    ).toBe(true);

    expect(
      isAuthorizedHeaders(new Headers({ authorization: `Bearer ${TEST_AUTH_VALUE}` }), {
        sender: "local-voice",
        token: TEST_AUTH_VALUE,
      }),
    ).toBe(true);

    expect(
      isAuthorizedHeaders(new Headers({ "x-sender": "wrong" }), {
        sender: "local-voice",
        token: TEST_AUTH_VALUE,
      }),
    ).toBe(false);
  });

  test("parses short permission verdicts", () => {
    expect(parsePermissionVerdict("allow req_123")).toEqual({
      behavior: "allow",
      request_id: "req_123",
    });
    expect(parsePermissionVerdict("deny req_456")).toEqual({
      behavior: "deny",
      request_id: "req_456",
    });
    expect(parsePermissionVerdict("run tests")).toBe(null);
  });
});
