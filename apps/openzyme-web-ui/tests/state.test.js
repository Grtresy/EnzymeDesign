import test from "node:test";
import assert from "node:assert/strict";

import { buildInitialViewState, reduceWorkspaceWithEvent } from "../src/state.js";
import { renderApp } from "../src/view.js";

function buildWorkspace() {
  return {
    episode_id: "ep_001",
    workflow: {
      episode_id: "ep_001",
      project_id: "proj_001",
      objective: "Improve thermostability",
      current_phase: "report_review",
      episode_status: "interrupted",
      progress: {
        phase: "report_review",
        active_node: "generate_report",
        status: "waiting",
        updated_at: "2026-04-11T00:00:00+00:00",
        message: "Building final report",
      },
      pending_interrupt: {
        type: "approval",
        approval_id: "appr_001",
      },
      pending_approval: {
        approval_id: "appr_001",
        requested_action: "Approve execution submission",
        created_at: "2026-04-11T00:00:00+00:00",
      },
      summary: {
        current_phase: "report_review",
        workflow_status: "interrupted",
        active_node: "generate_report",
        message: "Building final report",
        wait_state: "approval",
        evidence_count: 1,
        candidate_count: 1,
        selected_candidate_id: null,
        report_id: null,
        report_status: null,
      },
      updated_at: "2026-04-11T00:00:00+00:00",
    },
    pending_actions: [
      {
        approval_id: "appr_001",
        requested_action: "Approve execution submission",
        status: "pending",
        created_at: "2026-04-11T00:00:00+00:00",
      },
    ],
    runs: [],
    artifacts: [],
    research: {
      summary: { summary: "One scaffold family is promising." },
      evidence: [
        {
          evidence_id: "ev_001",
          summary: "Scaffold A is promising.",
          query: "scaffold A evidence",
          source_refs: [],
        },
      ],
      source_refs: [],
      unresolved_gaps: [{ gap_id: "gap_001", summary: "Need structural confirmation." }],
    },
    design: {
      candidates: [
        {
          candidate_id: "cand_001",
          title: "Candidate A",
          ranking: { rank: 1 },
        },
      ],
      rankings: [{ candidate_id: "cand_001", rank: 1 }],
      selected_candidate: null,
    },
    report: null,
  };
}

test("view state starts empty and renderApp shows create form", () => {
  const state = buildInitialViewState();
  const html = renderApp(state);
  assert.equal(state.currentProjectId, "");
  assert.equal(state.currentEpisodeId, "");
  assert.match(html, /Create Episode/);
  assert.match(html, /Project Shell/);
});

test("workspace render explains auto-run phases instead of looking skipped", () => {
  const html = renderApp({
    projects: [{ project_id: "proj_001", name: "Thermostability project" }],
    episodes: [{ episode_id: "ep_001", objective: "Improve thermostability", status: "interrupted" }],
    currentProjectId: "proj_001",
    currentEpisodeId: "ep_001",
    workspace: buildWorkspace(),
    errorMessage: "",
    busy: false,
  });

  assert.match(html, /Create Episode will auto-run the workflow until the next approval gate/);
  assert.match(html, /research/);
  assert.match(html, /design/);
  assert.match(html, /The current node is the place where execution paused, not the whole history/);
});

test("workflow stream events update the host workspace projection in place", () => {
  let workspace = buildWorkspace();
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_type: "workflow.progress_updated",
    progress: {
      phase: "execution",
      active_node: "execute_runner",
      status: "running",
      updated_at: "2026-04-11T00:01:00+00:00",
      message: "Executing runner",
    },
    updated_at: "2026-04-11T00:01:00+00:00",
  });
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_type: "workflow.run_status_changed",
    run: {
      run_id: "run_001",
      episode_id: "ep_001",
      status: "succeeded",
      execution_mode: "ssh",
      created_at: "2026-04-11T00:01:00+00:00",
      completed_at: "2026-04-11T00:02:00+00:00",
    },
  });
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_type: "workflow.artifact_available",
    artifact: {
      artifact_id: "art_001",
      episode_id: "ep_001",
      run_id: "run_001",
      kind: "result",
      storage_uri: "/tmp/result.json",
      created_at: "2026-04-11T00:02:00+00:00",
    },
  });
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_type: "workflow.selected_candidate_changed",
    selected_candidate: {
      episode_id: "ep_001",
      candidate_id: "cand_001",
      rationale: "Selected for execution handoff.",
      selected_at: "2026-04-11T00:03:00+00:00",
    },
  });
  workspace = reduceWorkspaceWithEvent(workspace, {
    event_type: "workflow.report_available",
    report: {
      report_id: "rep_001",
      episode_id: "ep_001",
      status: "ready",
      artifact_id: "art_report",
      artifact_storage_uri: "/tmp/report.md",
      title: "Final report",
      summary: "Execution completed and report review is ready.",
      stage_summary: "Research, design, execution, and report review are complete.",
      updated_at: "2026-04-11T00:04:00+00:00",
    },
  });

  assert.equal(workspace.workflow.progress.active_node, "execute_runner");
  assert.equal(workspace.runs[0].run_id, "run_001");
  assert.equal(workspace.artifacts[0].artifact_id, "art_001");
  assert.equal(workspace.design.selected_candidate.candidate_id, "cand_001");
  assert.equal(workspace.report.report_id, "rep_001");

  const html = renderApp({
    projects: [{ project_id: "proj_001", name: "Thermostability project" }],
    episodes: [{ episode_id: "ep_001", objective: "Improve thermostability", status: "completed" }],
    currentProjectId: "proj_001",
    currentEpisodeId: "ep_001",
    workspace,
    errorMessage: "",
    busy: false,
  });
  assert.match(html, /Approve execution submission/);
  assert.match(html, /run_001/);
  assert.match(html, /art_001/);
  assert.match(html, /Scaffold A is promising/);
  assert.match(html, /Candidate A/);
  assert.match(html, /Final report/);
});
