import test from "node:test";
import assert from "node:assert/strict";

import {
  renderApp,
  renderMainColumn,
  renderV3Outputs,
  renderV3ScientificEvidence,
} from "../src/view.js";

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
          operation_digest: `sha256:${"a".repeat(64)}`,
          route_policy_id: "bio_provider_http",
          selected_backend: "ebi_hmmer",
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
  assert.match(html, /op_001/);
  assert.match(html, /sha256:aaaaaaaaaaaaaa/);
  assert.match(html, /bio_provider_http/);
  assert.match(html, /srun_001/);
});

test("scientific evidence renders fail-closed quorum, continuity, empty result, and safe report status", () => {
  const html = renderV3ScientificEvidence({
    scientific_evidence: {
      schema_version: "v3.scientific_evidence.v1",
      active: true,
      scientific_outcome: "empty_result",
      providers: [
        {
          provider: "pubmed",
          requirement: "required",
          outcome: "completed",
          item_count: 1,
          request_digest: `sha256:${"1".repeat(64)}`,
          response_digest: `sha256:${"2".repeat(64)}`,
          private_locator: "http://127.0.0.1/private",
          api_key: "never-render-this-key",
        },
        {
          provider: "tavily",
          requirement: "enrichment",
          outcome: "degraded",
          item_count: 0,
          error_code: "provider_rate_limited",
        },
      ],
      quorum: { status: "degraded", cutover_eligible: true },
      operations: [
        {
          operation_id: "op_aox_001",
          logical_operation_key: "bio.hmmer_search",
          operation_digest: `sha256:${"3".repeat(64)}`,
          status: "completed",
          approval_id: "appr_aox_001",
          approval_state: "approved",
          route_policy_id: "bio_provider_http",
          selected_backend: "ebi_hmmer",
          host_path: "/home/private/aox",
        },
      ],
      artifacts: [
        {
          artifact_id: "art_scored",
          title: "scored_ref_plus_hits.csv",
          schema_id: "aox_motif_rule_score@1",
          cutover_eligible: true,
          content_digest: `sha256:${"4".repeat(64)}`,
        },
      ],
      reports: [
        {
          report_id: "report_aox_001",
          title: "AOX empty-result report",
          status: "published",
          published: true,
          cutover_eligible: false,
          artifact_id: "art_report",
        },
      ],
      citations: [
        {
          source_ref_id: "source_pubmed_001",
          provider: "pubmed",
          title: "AOX evidence paper",
          pmid: "12345678",
          response_digest: `sha256:${"5".repeat(64)}`,
        },
      ],
      verifier: { status: "missing" },
      cutover: {
        status: "blocked",
        eligible: false,
        blocker_codes: ["offline_verifier_evidence_missing"],
        warning_codes: ["tavily_enrichment_degraded"],
      },
    },
  });

  assert.match(html, /Provider quorum/);
  assert.match(html, /pubmed/);
  assert.match(html, /required · completed/);
  assert.match(html, /tavily_enrichment_degraded/);
  assert.match(html, /op_aox_001/);
  assert.match(html, /appr_aox_001 \/ approved/);
  assert.match(html, /sha256:33333333333333/);
  assert.match(html, /published true · eligible false/);
  assert.match(html, /Healthy empty result/);
  assert.match(html, /offline_verifier_evidence_missing/);
  assert.match(html, /PMID 12345678/);
  assert.doesNotMatch(html, /127\.0\.0\.1/);
  assert.doesNotMatch(html, /\/home\/private/);
  assert.doesNotMatch(html, /never-render-this-key/);
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

test("research notebook shell exposes real navigation and responsive panel controls", () => {
  const state = {
    currentProjectId: "proj_001",
    currentSessionId: "sess_001",
    currentSection: "tasks",
    mobilePane: "inspector",
    sidebarExpandedSessionIds: ["sess_001"],
    sessionSummaries: [{ session_id: "sess_001", title: "Manual run", objective: "Manual run", status: "active" }],
    runtimeHealth: { status: "degraded", deployment_profile: "local-dev" },
    workspace: workspace(),
    errors: { approvals: {}, runtimeHealth: "" },
    pendingApprovalId: "appr_001",
  };

  const html = renderApp(state);

  assert.match(html, /workspace-rail/);
  assert.match(html, /mobile-workspace-nav/);
  assert.match(html, /data-mobile-pane="inspector"/);
  assert.match(html, /Workspace inspector/);
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /Resolving\.\.\./);
  assert.match(html, /Message OpenZyme/);
  assert.match(html, /data-runtime-health="degraded"/);
  assert.match(html, /Runtime <strong>degraded<\/strong>/);
});
