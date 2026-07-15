import test from "node:test";
import assert from "node:assert/strict";

import { buildHostPaths, HostApiClient } from "../src/client.js";

test("buildHostPaths exposes the v3 session workspace surface", () => {
  assert.deepEqual(buildHostPaths("proj_001", "sess_001"), {
    v3ProjectSessions: "/v3/projects/proj_001/sessions",
    v3RuntimeHealth: "/v3/runtime/health",
    v3CreateSession: "/v3/sessions",
    v3Session: "/v3/sessions/sess_001",
    v3Messages: "/v3/sessions/sess_001/messages",
    v3Events: "/v3/sessions/sess_001/events?replay=1&follow=1&envelope=1",
    v3ApprovalResolve: "/v3/approvals/appr_001/resolve",
    debugLlmCalls: "/debug/llm-calls",
    debugLlmCall: "/debug/llm-calls/llmdbg_001",
    debugLlmClear: "/debug/llm-calls/clear",
  });
});

test("v3 stream consumes the generic envelope without an event-type allowlist", () => {
  const originalEventSource = globalThis.EventSource;
  let source = null;
  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.listeners = new Map();
      source = this;
    }

    addEventListener(name, handler) {
      this.listeners.set(name, handler);
    }

    close() {}
  }
  globalThis.EventSource = FakeEventSource;
  try {
    const events = [];
    new HostApiClient().streamV3Session("sess_001", (event) => events.push(event));
    assert.match(source.url, /envelope=1/);
    assert.deepEqual(Array.from(source.listeners.keys()), ["openzyme.event"]);
    source.listeners.get("openzyme.event")({
      data: JSON.stringify({
        event_id: "evt_future",
        event_type: "future.event.type",
        payload: { value: 1 },
      }),
    });
    assert.equal(events[0].event_type, "future.event.type");
  } finally {
    globalThis.EventSource = originalEventSource;
  }
});

test("v3 mutations carry a unique idempotency key", async () => {
  const originalFetch = globalThis.fetch;
  let request = null;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return {
      ok: true,
      async json() {
        return { session_id: "sess_001" };
      },
    };
  };
  try {
    await new HostApiClient().createV3Session({
      project_id: "proj_001",
      objective: "Retry safely",
    });
    assert.equal(request.url, "/v3/sessions");
    assert.equal(request.options.method, "POST");
    assert.match(request.options.headers["Idempotency-Key"], /^web-/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
