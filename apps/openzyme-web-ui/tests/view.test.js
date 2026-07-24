import test from "node:test";
import assert from "node:assert/strict";

import {
  renderApp,
  renderMainColumn,
  renderV3Outputs,
  renderV3ScientificEvidence,
  renderV3ScientificAttempts,
  renderV3Failures,
  renderV3Activity,
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
    scientific_attempts: {
      schema_id: "scientific_attempt_workspace@1",
      authorizations: [],
      attempts: [],
    },
    failure_observations: [],
    runtime_state: { task_attention: [] },
  };
}

test("scientific attempt view audits authority, dispositions, and closure", () => {
  const html = renderV3ScientificAttempts({
    scientific_attempts: {
      authorizations: [
        {
          envelope_id: "envelope_001",
          campaign_id: "campaign_aox",
          workflow_id: "aox_blank_world",
          status: "active",
          attempts: { consumed: 1, max: 2, remaining: 1 },
          resources: { micu: { reserved: 10, max: 100 } },
          expires_at: "2026-07-30T00:00:00+00:00",
        },
      ],
      attempts: [
        {
          attempt_id: "attempt_001",
          status: "closed",
          scope: "formal",
          ordinal: 1,
          selection_head: { selection_id: "selection_001" },
          selections: [
            {
              selection_id: "selection_001",
              operation_universe_digest: "sha256:universe",
              occurrences: [{ operation_id: "op_failed" }, { operation_id: "op_final" }],
              dispositions: [
                { operation_id: "op_failed", kind: "failed" },
                { operation_id: "op_final", kind: "adopted" },
              ],
              adoptions: [{ workflow_role: "final" }],
            },
          ],
          closure: { closure_id: "closure_001" },
        },
      ],
    },
  });

  assert.match(html, /remaining 1/);
  assert.match(html, /op_failed:failed/);
  assert.match(html, /adopted roles final/);
  assert.match(html, /closure_001/);
  assert.doesNotMatch(html, /allowed_providers/);
});

test("activity renders runtime command scheduler and projection separately", () => {
  const html = renderV3Activity({
    activity_feed: [
      {
        event_id: "evt_runtime_command",
        event_type: "runtime.command.finished",
        created_at: "2026-07-24T00:00:00+00:00",
        payload: {
          command_id: "runtime_command_001",
          status: "failed",
          bounded_outcome_summary: {
            schema_version: "runtime_command_outcome@2",
            core_receipt_formed: true,
            scheduler_status: "completed",
            processed_signal_count: 1,
            suspended: false,
            projection_status: "failed",
            projection_error_code: "runtime_projection_failed",
            projection_failed_stage: "runtime_consistency",
            replay_safe: false,
            claim_owner: "never-render-private-worker",
            host_path: "/home/private/runtime.sqlite3",
          },
        },
      },
    ],
  });

  assert.match(html, /data-runtime-command-outcome="runtime_command_outcome@2"/);
  assert.match(html, /scheduler completed · projection failed/);
  assert.match(html, /processed 1 · suspended false · replay safe false/);
  assert.match(html, /projection error runtime_projection_failed · stage runtime_consistency/);
  assert.doesNotMatch(html, /never-render-private-worker/);
  assert.doesNotMatch(html, /\/home\/private/);
});

test("activity keeps historical runtime receipt uncertainty explicit", () => {
  const html = renderV3Activity({
    activity_feed: [
      {
        event_type: "runtime.command.finished",
        created_at: "2026-07-20T00:00:00+00:00",
        payload: {
          command_id: "runtime_command_historical",
          status: "failed",
          bounded_outcome_summary: {
            schema_version: "runtime_command_outcome@1",
            processed_signal_count: 0,
            suspended: false,
          },
        },
      },
    ],
  });

  assert.match(html, /historical @1 · processed 0 · suspended false/);
  assert.match(
    html,
    /scheduler, projection, and replay safety were not recorded separately/,
  );
  assert.doesNotMatch(html, /replay safe true/);
});

test("structured failure view separates facts, likely causes, and agent hypothesis", () => {
  const html = renderV3Failures({
    runtime_state: {
      task_attention: [
        {
          task_id: "task_001",
          reasons: ["system_runtime_failure"],
          failure_observation_ids: ["failure_001"],
        },
      ],
    },
    failure_observations: [
      {
        failure_id: "failure_001",
        actor_kind: "system",
        error_code: "provider_unavailable",
        safe_summary: "The agent runtime could not produce a decision.",
        recoverability: "runtime_retry",
        effect_certainty: "no_effect",
        retry_eligibility: "same_phase_safe",
        facts: { agent_decision_produced: false, status_code: 502 },
        likely_causes: ["The configured provider is temporarily unavailable."],
        agent_hypothesis: "Quota may be exhausted.",
        agent_hypothesis_confidence: "low",
        safe_hint: "Resume after operator recovery.",
      },
    ],
  });

  assert.match(html, /Harness facts/);
  assert.match(html, /Likely causes/);
  assert.match(html, /Agent hypothesis \(low\)/);
  assert.match(html, /failure_001/);
  assert.doesNotMatch(html, /private_diagnostic_digest/);
});

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
