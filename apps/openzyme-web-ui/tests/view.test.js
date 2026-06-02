import test from "node:test";
import assert from "node:assert/strict";

import { renderMainColumn, renderV3Outputs } from "../src/view.js";

function workspace() {
  return {
    session: {
      session_id: "sess_001",
      title: "Manual run",
      objective: "Manual run",
      status: "active",
    },
    conversation: [],
    task_board: { items: [] },
    lane_board: { lanes: [] },
    delegation: {
      agents: [
        {
          agent: {
            agent_id: "agent:executor",
            name: "Executor",
            role: "executor",
            status: "working",
          },
        },
      ],
    },
    agent_traces: { "agent:executor": [] },
    pending_approvals: [
      {
        approval_id: "appr_001",
        kind: "sdk_controlled_operation",
        requested_action: "Approve supervised SDK operation.",
        status: "pending",
        operation: {
          operation_id: "op_001",
          logical_operation_key: "bio.hmmer_search",
          backend_category: "provider_http",
          sandbox_run_id: "srun_001",
        },
        sandbox_run: { sandbox_run_id: "srun_001", status: "running" },
      },
    ],
    activity_feed: [],
    artifacts: [],
    artifact_index: [],
    sandbox_runs: [],
    report_drafts: [],
    reports: [],
    capabilities: {},
  };
}

test("teammate trace view still renders pending approval card", () => {
  const state = {
    workspace: workspace(),
    selectedTeammateAgentId: "agent:executor",
    errors: { approvals: {} },
    pendingApprovalId: "",
  };

  const html = renderMainColumn(state);

  assert.match(html, /approval-stack-root/);
  assert.match(html, /bio\.hmmer_search/);
  assert.match(html, /srun_001/);
});

test("outputs render folded artifact index entries with version count", () => {
  const ws = {
    ...workspace(),
    pending_approvals: [],
    artifact_index: [
      {
        relative_path: "aox_hmm/AOX_ref21.fasta",
        latest_artifact_id: "art_latest",
        artifact_ids: ["art_old", "art_latest"],
        version_count: 2,
        latest: {
          artifact_id: "art_latest",
          relative_path: "aox_hmm/AOX_ref21.fasta",
          kind: "sequence",
          title: "AOX_ref21.fasta",
          metadata: {},
          provenance: {},
        },
      },
    ],
  };

  const html = renderV3Outputs(ws, { selectedArtifactId: "", errors: { approvals: {} } });

  assert.match(html, /AOX_ref21\.fasta/);
  assert.match(html, /2 versions/);
  assert.doesNotMatch(html, /art_old ·/);
});
