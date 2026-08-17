import test from "node:test";
import assert from "node:assert/strict";

import { buildHostPaths, HostApiClient } from "../src/client.js";
import { FILE_WORKSPACE_RELEASE } from "../src/file_workspace_release.js";

function workspaceResponse() {
  return {
    session_id: "sess_001",
    workspace: {
      schema_version: FILE_WORKSPACE_RELEASE.schemaVersion,
      tool_catalog_digest: FILE_WORKSPACE_RELEASE.toolCatalogDigest,
      schema_bundle_digest: FILE_WORKSPACE_RELEASE.schemaBundleDigest,
      session: { session_id: "sess_001" },
      agent_workspaces: [],
      workspace_status: [],
      private_revisions: [],
      published_revisions: [],
      reports: [],
      scientific_deliverables: [],
      external_jobs: [],
      external_job_results: [],
      capability_leases: [],
    },
  };
}

test("buildHostPaths exposes the v3 session workspace surface", () => {
  assert.deepEqual(buildHostPaths("proj_001", "sess_001"), {
    v3ProjectSessions: "/v3/projects/proj_001/sessions",
    v3RuntimeHealth: "/v3/runtime/health",
    v3RuntimeDrain: "/v3/sessions/sess_001/runtime/drain",
    v3RuntimeCommand: "/v3/sessions/sess_001/runtime/commands/runtime_command_001",
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
        schema_version: FILE_WORKSPACE_RELEASE.schemaVersion,
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
        return workspaceResponse();
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

test("v3 session reads forward an abort signal", async () => {
  const originalFetch = globalThis.fetch;
  let request = null;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return {
      ok: true,
      async json() {
        return workspaceResponse();
      },
    };
  };
  const abortController = new AbortController();
  try {
    await new HostApiClient().getV3Session("sess_001", {
      signal: abortController.signal,
    });
    assert.equal(request.url, "/v3/sessions/sess_001");
    assert.equal(request.options.signal, abortController.signal);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("v3 runtime command client uses session-scoped command routes", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    return {
      ok: true,
      async json() {
        return {
          schema_version: "runtime_command_status@1",
          session_id: "sess_001",
          command_id: "runtime_command_001",
          status: "accepted",
        };
      },
    };
  };
  try {
    const client = new HostApiClient();
    await client.drainV3Runtime("sess_001", {
      max_signals: 1,
      max_steps_per_agent: 2,
    });
    await client.getV3RuntimeCommand("sess_001", "runtime_command_001");

    assert.equal(requests[0].url, "/v3/sessions/sess_001/runtime/drain");
    assert.equal(requests[0].options.method, "POST");
    assert.match(requests[0].options.headers["Idempotency-Key"], /^web-/);
    assert.equal(
      requests[1].url,
      "/v3/sessions/sess_001/runtime/commands/runtime_command_001",
    );
    assert.equal(requests[1].options.method, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
