import assert from "node:assert/strict";
import test from "node:test";

import {
  renderV3Failures,
  renderV3Outputs,
  renderV3ScientificAttempts,
} from "../src/view.js";

test("file tree, private revision, publication and pagination render exact public identities", () => {
  const html = renderV3Outputs({
    workspace_status: [{
      workspace_id: "workspace-1",
      workspace_generation: 5,
      status: "ready",
      dirty_state: "dirty",
      head_commit: "a".repeat(40),
      changed_paths: ["scientific/result.json"],
      changed_paths_truncated: true,
      changed_paths_continuation: "observation-1:100",
    }],
    private_revisions: [{
      workspace_id: "workspace-1",
      workspace_generation: 5,
      commit: "b".repeat(40),
      tree: "c".repeat(40),
    }],
    published_revisions: [{
      publication_ref: "refs/openzyme/publications/publication-1",
      commit: "d".repeat(40),
      manifest_digest: `sha256:${"e".repeat(64)}`,
      publisher_agent_member_id: "member-1",
    }],
    reports: [],
  });
  assert.match(html, /scientific\/result\.json/);
  assert.match(html, /bbbbbbbbbbbb/);
  assert.match(html, /refs\/openzyme\/publications\/publication-1/);
  assert.match(html, /data-action="load-more-changed-paths"/);
  assert.match(html, /data-workspace-id="workspace-1"/);
});

test("external job view distinguishes unknown effect from terminal observation", () => {
  const html = renderV3ScientificAttempts({
    external_jobs: [{
      execution_id: "execution-1",
      lifecycle_state: "cancel_requested",
      effect_certainty: "unknown",
      source_commit: "a".repeat(40),
      accepted_at: "2026-08-18T00:00:00Z",
    }],
    external_job_results: [{
      result_id: "result-1",
      terminal_state: "cancelled",
      exit_code: null,
      result_digest: `sha256:${"b".repeat(64)}`,
      source_commit: "a".repeat(40),
    }],
  });
  assert.match(html, /cancel_requested · unknown/);
  assert.match(html, /cancelled · exit unknown/);
});

test("diagnostic view renders allowlisted public facts and never private context", () => {
  const html = renderV3Failures({
    failure_observations: [{
      failure_id: "failure-1",
      failure_class: "workspace_file_cleanup_incomplete",
      recoverability: "operator_action_required",
      safe_summary: "temporary handoff residue requires exact cleanup",
      effect_certainty: "effect_applied",
      private_diagnostic: {
        traceback: "SECRET_TOKEN=do-not-render",
        absolute_path: "/private/operator/path",
      },
    }],
  });
  assert.match(html, /workspace_file_cleanup_incomplete/);
  assert.match(html, /failure-1/);
  assert.match(html, /effect effect_applied/);
  assert.doesNotMatch(html, /SECRET_TOKEN|do-not-render|\/private\/operator\/path/);
});
