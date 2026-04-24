import test from "node:test";
import assert from "node:assert/strict";

import { buildHostPaths } from "../src/client.js";

test("buildHostPaths exposes the v3 session workspace surface", () => {
  assert.deepEqual(buildHostPaths("proj_001", "sess_001"), {
    v3ProjectSessions: "/v3/projects/proj_001/sessions",
    v3CreateSession: "/v3/sessions",
    v3Session: "/v3/sessions/sess_001",
    v3Messages: "/v3/sessions/sess_001/messages",
    v3Events: "/v3/sessions/sess_001/events?replay=1&follow=1",
    v3ApprovalResolve: "/v3/approvals/appr_001/resolve",
    debugLlmCalls: "/debug/llm-calls",
    debugLlmCall: "/debug/llm-calls/llmdbg_001",
    debugLlmClear: "/debug/llm-calls/clear",
  });
});
