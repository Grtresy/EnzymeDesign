import test from "node:test";
import assert from "node:assert/strict";

import { WorkspaceController } from "../src/controller.js";

function buildPendingWorkspace() {
  return {
    episode_id: "ep_001",
    workflow: {
      episode_id: "ep_001",
      project_id: "proj_001",
      objective: "Improve thermostability",
      current_phase: "design",
      episode_status: "interrupted",
      progress: {
        phase: "design",
        active_node: "approval_gate",
        status: "waiting",
        updated_at: "2026-04-11T00:00:00+00:00",
        message: "Waiting for approval",
      },
      pending_interrupt: { type: "approval", approval_id: "appr_001" },
      pending_approval: {
        approval_id: "appr_001",
        requested_action: "Approve selected candidate for a design run",
        created_at: "2026-04-11T00:00:00+00:00",
      },
      summary: {
        current_phase: "design",
        workflow_status: "interrupted",
        active_node: "approval_gate",
        message: "Waiting for approval",
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
        requested_action: "Approve selected candidate for a design run",
        status: "pending",
        created_at: "2026-04-11T00:00:00+00:00",
      },
    ],
    runs: [],
    artifacts: [],
    research: {
      summary: { summary: "One scaffold family is promising." },
      evidence: [{ evidence_id: "ev_001", summary: "Scaffold A is promising.", query: "scaffold A evidence" }],
      source_refs: [],
      unresolved_gaps: [],
    },
    design: {
      candidates: [{ candidate_id: "cand_001", title: "Candidate A", ranking: { rank: 1 } }],
      rankings: [{ candidate_id: "cand_001", rank: 1 }],
      selected_candidate: null,
    },
    report: null,
  };
}

function buildCompletedWorkspace(episodeId = "ep_001") {
  return {
    episode_id: episodeId,
    workflow: {
      episode_id: episodeId,
      project_id: "proj_001",
      objective: "Improve thermostability",
      current_phase: "report_review",
      episode_status: "completed",
      progress: {
        phase: "report_review",
        active_node: "generate_report",
        status: "succeeded",
        updated_at: "2026-04-11T00:02:00+00:00",
        message: "Report review finished",
      },
      pending_interrupt: null,
      pending_approval: null,
      summary: {
        current_phase: "report_review",
        workflow_status: "completed",
        active_node: "generate_report",
        message: "Report review finished",
        wait_state: null,
        evidence_count: 1,
        candidate_count: 1,
        selected_candidate_id: "cand_001",
        report_id: "rep_001",
        report_status: "ready",
      },
      updated_at: "2026-04-11T00:02:10+00:00",
    },
    pending_actions: [],
    runs: [
      {
        run_id: "run_001",
        episode_id: episodeId,
        status: "succeeded",
        execution_mode: "ssh",
        created_at: "2026-04-11T00:01:00+00:00",
        completed_at: "2026-04-11T00:02:00+00:00",
      },
    ],
    artifacts: [
      {
        artifact_id: "art_001",
        episode_id: episodeId,
        run_id: "run_001",
        kind: "result",
        storage_uri: "/tmp/result.json",
        created_at: "2026-04-11T00:02:00+00:00",
      },
      {
        artifact_id: "art_report",
        episode_id: episodeId,
        run_id: "run_001",
        kind: "report",
        storage_uri: "/tmp/report.md",
        created_at: "2026-04-11T00:02:10+00:00",
      },
    ],
    research: {
      summary: { summary: "One scaffold family is promising." },
      evidence: [{ evidence_id: "ev_001", summary: "Scaffold A is promising.", query: "scaffold A evidence" }],
      source_refs: [],
      unresolved_gaps: [],
    },
    design: {
      candidates: [{ candidate_id: "cand_001", title: "Candidate A", ranking: { rank: 1 } }],
      rankings: [{ candidate_id: "cand_001", rank: 1 }],
      selected_candidate: {
        episode_id: episodeId,
        candidate_id: "cand_001",
        rationale: "Selected for the design run.",
        selected_at: "2026-04-11T00:01:30+00:00",
      },
    },
    report: {
      report_id: "rep_001",
      episode_id: episodeId,
      status: "ready",
      artifact_id: "art_report",
      artifact_storage_uri: "/tmp/report.md",
      title: "Final report",
      summary: "Design loop completed and report review is ready.",
      stage_summary: "Intake, design, and report review are complete.",
      updated_at: "2026-04-11T00:02:10+00:00",
    },
  };
}

function buildEpisodes() {
  return [
    {
      episode_id: "ep_000",
      project_id: "proj_001",
      objective: "Earlier run",
      status: "completed",
    },
    {
      episode_id: "ep_001",
      project_id: "proj_001",
      objective: "Improve thermostability",
      status: "completed",
    },
  ];
}

test("workspace controller closes the loop from create through report visibility", async () => {
  let streamHandler = null;
  const changes = [];
  const fakeClient = {
    async getProjects() {
      return [{ project_id: "proj_001", name: "Thermostability project" }];
    },
    async getProjectEpisodes() {
      return buildEpisodes();
    },
    async getWorkspace(episodeId) {
      return buildCompletedWorkspace(episodeId);
    },
    async createEpisode() {
      return { episode_id: "ep_001", workspace: buildPendingWorkspace() };
    },
    async resumeEpisode() {
      return { episode_id: "ep_001", workspace: buildCompletedWorkspace() };
    },
    async resolveApproval() {
      return { episode_id: "ep_001", workspace: buildCompletedWorkspace() };
    },
    streamEpisode(_episodeId, onEvent) {
      streamHandler = onEvent;
      return { close() {} };
    },
  };

  const controller = new WorkspaceController(fakeClient, (snapshot) => {
    changes.push(snapshot);
  });

  await controller.bootstrap();
  await controller.createEpisode({
    project_id: "proj_001",
    objective: "Improve thermostability",
  });
  assert.equal(controller.state.currentEpisodeId, "ep_001");
  assert.equal(controller.state.workspace.pending_actions.length, 1);

  await controller.resolveApproval("approved");
  assert.equal(controller.state.workspace.runs[0].run_id, "run_001");
  assert.equal(controller.state.workspace.design.selected_candidate.candidate_id, "cand_001");
  assert.equal(controller.state.workspace.report.report_id, "rep_001");

  streamHandler?.({
    event_type: "workflow.artifact_available",
    artifact: {
      artifact_id: "art_002",
      episode_id: "ep_001",
      run_id: "run_001",
      kind: "log",
      storage_uri: "/tmp/stdout.log",
      created_at: "2026-04-11T00:03:00+00:00",
    },
  });
  assert.equal(controller.state.workspace.artifacts.length, 3);
  assert.ok(changes.length >= 4);
});

test("workspace controller bootstraps project shell and switches episodes", async () => {
  let loadedEpisodeId = "";
  const fakeClient = {
    async getProjects() {
      return [{ project_id: "proj_001", name: "Thermostability project" }];
    },
    async getProjectEpisodes() {
      return buildEpisodes();
    },
    async getWorkspace(episodeId) {
      loadedEpisodeId = episodeId;
      return buildCompletedWorkspace(episodeId);
    },
    streamEpisode() {
      return { close() {} };
    },
  };

  const controller = new WorkspaceController(fakeClient);
  await controller.bootstrap();
  assert.equal(controller.state.currentProjectId, "proj_001");
  assert.equal(controller.state.currentEpisodeId, "ep_001");

  await controller.selectEpisode("ep_000");
  assert.equal(loadedEpisodeId, "ep_000");
  assert.equal(controller.state.currentEpisodeId, "ep_000");
});
