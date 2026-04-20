import test from "node:test";
import assert from "node:assert/strict";

import { buildHostPaths } from "../src/client.js";

test("buildHostPaths matches the thin host api surface", () => {
  assert.deepEqual(buildHostPaths("ep_001"), {
    projects: "/projects",
    projectEpisodes: "/projects/proj_001/episodes",
    workspace: "/episodes/ep_001/workspace",
    workflow: "/episodes/ep_001/workflow",
    pendingActions: "/episodes/ep_001/pending-actions",
    runs: "/episodes/ep_001/runs",
    artifacts: "/episodes/ep_001/artifacts",
    reports: "/episodes/ep_001/reports",
    stream: "/episodes/ep_001/stream?replay=1",
    createEpisode: "/commands/create_episode",
    resumeEpisode: "/commands/resume_episode",
    resolveApproval: "/commands/resolve_approval",
    v3CreateSession: "/v3/sessions",
    v3Workspace: "/v3/sessions/ep_001/workspace",
    v3Messages: "/v3/sessions/ep_001/messages",
    v3Events: "/v3/sessions/ep_001/events?replay=1",
    v3ApprovalResolve: "/v3/approvals/appr_001/resolve",
  });
});
