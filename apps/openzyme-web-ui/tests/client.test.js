import test from "node:test";
import assert from "node:assert/strict";

import { buildHostPaths } from "../src/client.js";

test("buildHostPaths exposes only the v3 session surface", () => {
  assert.deepEqual(buildHostPaths("sess_001"), {
    v3CreateSession: "/v3/sessions",
    v3Messages: "/v3/sessions/sess_001/messages",
    v3Events: "/v3/sessions/sess_001/events?replay=1",
    v3ApprovalResolve: "/v3/approvals/appr_001/resolve",
  });
});
