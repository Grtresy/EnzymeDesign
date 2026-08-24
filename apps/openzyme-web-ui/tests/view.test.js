import assert from "node:assert/strict";
import test from "node:test";

import { buildCoreShellState } from "../src/core_shell.js";
import { ExtensionRendererRegistry } from "../src/extension_renderer_loader.js";
import {
  renderApp,
  renderCoreWorkspace,
  renderProjectionChangeObservations,
  renderToolAffordances,
} from "../src/view.js";

const digest = (character) => `sha256:${character.repeat(64)}`;

function shell() {
  const release = {
    schema_version: "openzyme_layered_release_identity@1",
    kernel_contract_digest: digest("a"), core_schema_digest: digest("b"),
    adapter_bundle_digest: digest("c"), extension_bundle_digest: digest("d"),
    declared_tool_catalog_digest: digest("e"), route_catalog_digest: digest("f"),
    projection_catalog_digest: digest("1"), migration_catalog_digest: digest("2"),
    workspace_backend_digest: digest("3"), host_build_digest: digest("4"),
    client_build_digest: digest("5"), release_digest: digest("6"),
    public_contract_digest: digest("7"),
  };
  const payload = {
    schema_version: "file_workspace_public@2",
    release,
    core: {
      agents: [], approvals: [], authority_leases: [],
      capability_binding: { binding_digest: digest("8") },
      conversation: {
        memories: [], messages: [],
        transcript: {
          schema_version: "ordered_transcript@1", messages: [],
          transcript_digest: "sha256:4cebf6af4adaee585bed6af9d28e906c6dc55111de3fe19d746eb7f6df43bbd0",
        },
      },
      failures: { observations: [] }, lanes: [],
      operations: {
        command_receipts: [], continuations: [], controlled: [],
        publication_intents: [], task_evidence: [],
      },
      protocol: { inbox: [], records: [] },
      publications: [{ publication_ref: "refs/openzyme/publication-1", commit: "abc" }],
      runtime: {
        commands: [],
        continuation_intents: [], outcome_consumptions: [], session_leases: [],
        settlement_intents: [], signals: [], turn_commands: [], outcomes: [],
        workflow_authority: {
          schema_version: "workflow_authority_projection@1",
          bindings: [], signal_links: [],
        },
      },
      session: {
        session_id: "session-1", objective: "Render Kernel truth",
        resident_readiness: {
          schema_version: "resident_teammate_readiness@1",
          readiness: "ready", workspace_id: "workspace-1",
          workspace_generation: 1, provisioning_intent_id: "provisioning-1",
          provisioning_intent_digest: digest("b"), failure_id: null,
          next_action: "message_or_drain",
        },
      },
      tasks: [],
      tool_reflection: {
        declared_tool_catalog_digest: release.declared_tool_catalog_digest,
        affordance_snapshot_digest: digest("9"),
        capability_binding_digest: digest("8"),
        available_tool_names: [],
        affordances: [{
          tool_name: "workspace.exec",
          tool_contract_digest: digest("0"),
          state: "blocked_authority",
          required_authorities: ["workspace.process.exec"],
          route_ids: [], route_refs: [],
          blockers: [{ code: "authority_missing", requirement: null, target_id: null }],
        }],
        tool_exposure: {
          schema_version: "tool_exposure_public@1",
          exposure_snapshot_id: "exposure-1",
          exposure_snapshot_digest: digest("c"),
          direct_tool_names: ["workspace.exec"], deferred_tool_names: [],
          command_expansions: [],
        },
      },
      workspace: {
        checkpoints: [],
        generations: [{ workspace_id: "workspace-1", generation: 2, status: "ready" }],
        repository_binding_pins: [], revision_path_verifications: [], runtime_bindings: [],
        provisioning: {
          schema_version: "workspace_provisioning_public@2",
          intent_id: "provisioning-1", intent_digest: digest("b"), status: "ready",
          intent_state_version: 2,
          workspace_id: "workspace-1", workspace_generation: 1,
          runtime_binding_id: "runtime-binding-1", failure_id: null,
          error_code: null, effect_certainty: "effect_known", mutation_applied: true,
          fallback_performed: false, retry_permitted: false,
          reconcile_required: false, diagnostic_id: null,
          next_action: "message_or_drain",
          reconciliation: null,
        },
      },
    },
    extensions: {},
  };
  return buildCoreShellState(
    payload,
    new ExtensionRendererRegistry({ rendererCatalogDigest: digest("a") }),
    { expectedRendererCatalogDigest: digest("a") },
  );
}

test("Core view renders workspace revision/publication truth without product placeholders", () => {
  const html = renderCoreWorkspace(shell());
  assert.match(html, /workspace-1/);
  assert.match(html, /refs\/openzyme\/publication-1/);
  assert.doesNotMatch(html, /Scientific|Research|HPC|Report/);
});

test("blocked affordance remains visible with its exact blocker", () => {
  const html = renderToolAffordances(shell());
  assert.match(html, /workspace\.exec/);
  assert.match(html, /blocked_authority/);
  assert.match(html, /authority_missing/);
});

test("Plugin-free Standard shell stays usable and has no empty extension panel", () => {
  const html = renderApp({
    shell: shell(), loading: false, refreshing: false,
    messageBusy: false, drainBusy: false, error: "", mutationError: "",
  });
  assert.match(html, /OpenZyme Kernel workspace/);
  assert.match(html, /Message OpenZyme/);
  assert.match(html, /Exact workflow refs/);
  assert.doesNotMatch(html, /Extension views/);
});

test("contract blocker removes every mutation control", () => {
  const blocked = shell();
  blocked.contractBlocked = true;
  blocked.mutationAllowed = false;
  blocked.blockingError = "renderer_catalog_drift";
  const html = renderApp({ shell: blocked, loading: false, error: "" });
  assert.match(html, /non-operational/);
  assert.match(html, /renderer_catalog_drift/);
  assert.doesNotMatch(html, /<form|runtime-drain/);
});

test("provisioning state stays visible and disables message/runtime controls", () => {
  const pending = shell();
  pending.core.session.resident_readiness.readiness = "provisioning";
  pending.core.session.resident_readiness.next_action = "wait_for_provisioning_worker";
  pending.residentReadiness = "provisioning";
  pending.residentReady = false;
  pending.messageAllowed = false;
  pending.runtimeDrainAllowed = false;
  const html = renderApp({
    shell: pending, loading: false, refreshing: false,
    messageBusy: false, drainBusy: false, approvalBusy: false,
    error: "", mutationError: "",
  });

  assert.match(html, /Workspace provisioning is durable and still in progress/);
  assert.match(html, /textarea[^>]*disabled/);
  assert.match(html, /data-action="runtime-drain"[^>]*disabled/);
});

test("ordered assistant and tool transcript is rendered from canonical transcript", () => {
  const subject = shell();
  subject.core.conversation.transcript.messages = [
    {
      schema_version: "resident_transcript_message@1", ordinal: 1,
      message_id: "assistant-1", role: "assistant", content: "I queued the tool.",
      correlation_id: "correlation-1", tool_call_id: null,
      source_command_id: "turn-command-1", source_outcome_id: "outcome-1",
      created_at: "2026-08-24T00:00:00Z",
    },
    {
      schema_version: "resident_transcript_message@1", ordinal: 2,
      message_id: "tool-1", role: "tool", content: "tool result",
      correlation_id: "correlation-1", tool_call_id: "call-1",
      source_command_id: "turn-command-1", source_outcome_id: "outcome-1",
      created_at: "2026-08-24T00:00:01Z",
    },
  ];
  const html = renderApp({
    shell: subject, loading: false, refreshing: false,
    messageBusy: false, drainBusy: false, approvalBusy: false,
    error: "", mutationError: "",
  });

  assert.match(html, /I queued the tool/);
  assert.match(html, /tool result/);
  assert.doesNotMatch(html, /hidden_tool_names|Hidden tools/);
});

test("populated collaboration, approval, failure, and blocked next action stay visible", () => {
  const subject = shell();
  subject.core.tasks = [{
    task_id: "task-1", subject: "Inspect evidence", status: "active",
  }];
  subject.core.agents = [{
    agent_member_id: "teammate-1", role: "teammate", readiness: "ready",
  }];
  subject.core.protocol.records = [{
    protocol_ref: "delegation-1", kind: "task_delegation",
    task_id: "task-1", recipient_member_id: "teammate-1",
  }];
  subject.core.protocol.inbox = [{
    message_id: "inbox-1", recipient_member_id: "teammate-1", status: "pending",
  }];
  subject.core.approvals = [{
    approval_id: "approval-1", status: "pending", intent_digest: digest("a"),
  }];
  subject.core.failures.observations = [{
    failure_id: "failure-1", diagnostic_id: "diagnostic-1",
    error_code: "workspace_provisioning_failed",
    next_action: "inspect_recovery_state",
  }];
  subject.core.session.resident_readiness.readiness = "blocked";
  subject.core.session.resident_readiness.failure_id = "failure-1";
  subject.core.session.resident_readiness.next_action = "inspect_recovery_state";
  subject.core.workspace.provisioning = {
    ...subject.core.workspace.provisioning,
    status: "blocked", failure_id: "failure-1",
    error_code: "workspace_provisioning_failed",
    effect_certainty: "no_effect", mutation_applied: false,
    retry_permitted: false, reconcile_required: true,
    diagnostic_id: "diagnostic-1", next_action: "inspect_recovery_state",
  };

  const html = renderApp({
    shell: subject, loading: false, refreshing: false,
    messageBusy: false, drainBusy: false, approvalBusy: false,
    error: "", mutationError: "",
  });

  for (const expected of [
    "task-1", "teammate-1", "delegation-1", "inbox-1", "approval-1",
    "failure-1", "diagnostic-1", "inspect_recovery_state",
  ]) assert.match(html, new RegExp(expected));
  assert.match(html, /data-action="approval-decision"/);
});

test("view renders verified projection change facts without claiming a Host event stream", () => {
  const subject = shell();
  subject.projectionObservations = [{
    schema_version: "file_workspace_projection_observation@1",
    observation_id: digest("d"),
    observation_kind: "workspace_projection_change",
    source: "verified_workspace_projection_poll",
    session_id: "session-1",
    release_digest: digest("6"),
    public_contract_digest: digest("7"),
    previous_projection_digest: null,
    projection_digest: digest("d"),
    facts: {
      schema_version: "resident_workspace_projection_change_facts@1",
      readiness: "ready",
      next_action: "message_or_drain",
      workspace_id: "workspace-1",
      workspace_generation: 1,
      provisioning_intent_id: "provisioning-1",
      provisioning_intent_state_version: 2,
      transcript_digest: digest("e"),
      pending_signal_count: 1,
      runtime_command_count: 2,
      latest_runtime_command: null,
      pending_approval_ids: ["approval-1"],
      failure_ids: [],
    },
  }];

  const observations = renderProjectionChangeObservations(subject);
  const html = renderApp({
    shell: subject, loading: false, refreshing: false,
    messageBusy: false, drainBusy: false, approvalBusy: false,
    projectionPollingStatus: "connected",
    error: "", mutationError: "",
  });

  assert.match(observations, /Verified projection change observations/);
  assert.match(observations, /pending_signal_count/);
  assert.match(observations, /approval-1/);
  assert.match(observations, /not a Host event stream/);
  assert.match(html, /Projection polling/);
  assert.match(html, /connected/);
  assert.doesNotMatch(html, /Verified Host projection events|Canonical event facts/);
});
