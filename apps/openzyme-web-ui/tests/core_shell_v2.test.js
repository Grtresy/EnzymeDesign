import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  buildCoreShellState,
  reduceCoreShellProjectionObservation,
} from "../src/core_shell.js";
import { ExtensionRendererRegistry } from "../src/extension_renderer_loader.js";
import {
  buildFileWorkspaceV2ProjectionObservation,
  requireAvailableTool,
} from "../src/file_workspace_v2_state.js";


const digest = (character) => `sha256:${character.repeat(64)}`;

function core() {
  const bindingDigest = digest("1");
  return {
    agents: [],
    approvals: [],
    authority_leases: [],
    capability_binding: { binding_digest: bindingDigest },
    conversation: {
      memories: [], messages: [],
      transcript: {
        schema_version: "ordered_transcript@1", messages: [],
        transcript_digest: "sha256:4cebf6af4adaee585bed6af9d28e906c6dc55111de3fe19d746eb7f6df43bbd0",
      },
    },
    failures: { observations: [] },
    lanes: [],
    operations: {
      command_receipts: [],
      continuations: [],
      controlled: [],
      publication_intents: [],
      task_evidence: [],
    },
    protocol: { inbox: [], records: [] },
    publications: [],
    runtime: {
      commands: [],
      continuation_intents: [],
      outcome_consumptions: [],
      outcomes: [],
      session_leases: [],
      settlement_intents: [],
      signals: [],
      turn_commands: [],
      workflow_authority: {
        schema_version: "workflow_authority_projection@1",
        bindings: [], signal_links: [],
      },
    },
    session: {
      session_id: "session-1",
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
      declared_tool_catalog_digest: digest("8"),
      affordance_snapshot_digest: digest("9"),
      capability_binding_digest: bindingDigest,
      available_tool_names: [],
      affordances: [],
      tool_exposure: {
        schema_version: "tool_exposure_public@1",
        exposure_snapshot_id: "exposure-1",
        exposure_snapshot_digest: digest("c"),
        direct_tool_names: [], deferred_tool_names: [], command_expansions: [],
      },
    },
    workspace: {
      checkpoints: [],
      generations: [],
      repository_binding_pins: [],
      revision_path_verifications: [],
      runtime_bindings: [],
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
  };
}

function projection(extensions = {}) {
  return {
    schema_version: "file_workspace_public@2",
    release: {
      schema_version: "openzyme_layered_release_identity@1",
      kernel_contract_digest: digest("a"),
      core_schema_digest: digest("b"),
      adapter_bundle_digest: digest("c"),
      declared_tool_catalog_digest: digest("8"),
      route_catalog_digest: digest("d"),
      migration_catalog_digest: digest("e"),
      workspace_backend_digest: digest("f"),
      release_digest: digest("2"),
      public_contract_digest: digest("3"),
      extension_bundle_digest: digest("4"),
      projection_catalog_digest: digest("5"),
      host_build_digest: digest("6"),
      client_build_digest: digest("7"),
    },
    core: core(),
    extensions,
  };
}

function runtimeTurnCommand() {
  return {
    schema_version: "runtime_turn_command_public@1",
    command_id: "turn-command-1",
    turn_id: "turn-1",
    session_id: "session-1",
    agent_id: "agent-1",
    agent_member_id: "member-1",
    signal_id: "signal-1",
    signal_attempt: 1,
    runtime_lease_generation: 1,
    runtime_fence: 1,
    process_epoch: 1,
    distribution_id: "distribution-1",
    distribution_manifest_digest: digest("a"),
    release_digest: digest("2"),
    adapter_bundle_digest: digest("c"),
    extension_bundle_digest: digest("4"),
    declared_tool_catalog_digest: digest("8"),
    capability_binding_id: "binding-1",
    capability_binding_revision: 1,
    capability_binding_digest: digest("1"),
    affordance_snapshot_id: "affordance-1",
    affordance_snapshot_digest: digest("9"),
    workflow_authority_id: "authority-1",
    workflow_authority_epoch: 1,
    workflow_authority_digest: digest("d"),
    signal_authority_link_digest: digest("e"),
    tool_exposure_snapshot_id: "exposure-1",
    tool_exposure_snapshot_digest: digest("c"),
    context_digest: digest("f"),
    message_count: 1,
    runtime_adapter_id: "runtime-adapter-1",
    runtime_adapter_contract_digest: digest("0"),
    max_steps: 8,
    max_duration_seconds: 60,
    max_input_units: 4096,
    max_output_units: 2048,
    task_id: null,
    lane_id: null,
    continuation_id: null,
    source_command_digest: digest("a"),
  };
}

function runtimeOutcomeReceipt({ failed = false } = {}) {
  return {
    schema_version: "runtime_turn_outcome_receipt_public@1",
    receipt_id: "outcome-receipt-1",
    accepted_at: "2026-08-24T00:01:00Z",
    source_receipt_digest: digest("1"),
    outcome: {
      schema_version: "runtime_turn_outcome_public@1",
      outcome_id: "outcome-1",
      command_id: "turn-command-1",
      source_command_digest: digest("a"),
      turn_id: "turn-1",
      session_id: "session-1",
      agent_id: "agent-1",
      agent_member_id: "member-1",
      signal_id: "signal-1",
      signal_attempt: 1,
      runtime_lease_generation: 1,
      runtime_fence: 1,
      process_epoch: 1,
      workflow_authority_id: "authority-1",
      workflow_authority_epoch: 1,
      workflow_authority_digest: digest("d"),
      tool_exposure_snapshot_id: "exposure-1",
      tool_exposure_snapshot_digest: digest("c"),
      disposition: failed ? "failed" : "idle",
      summary: failed ? "The selected runtime failed." : "The turn settled idle.",
      message_count: 1,
      tool_request_count: 0,
      tool_request_digest: digest("2"),
      usage: {
        schema_version: "runtime_usage@1",
        input_units: 10,
        output_units: 5,
        total_units: 15,
        provider_reported: true,
      },
      continuation_id: null,
      waiting_approval_id: null,
      failure: failed ? {
        schema_version: "runtime_failure_public@1",
        failure_id: "failure-1",
        error_code: "runtime_provider_failed",
        safe_summary: "The selected runtime failed.",
        diagnostic_id: "diagnostic-1",
        effect_certainty: "no_effect",
        mutation_applied: false,
        fallback_performed: false,
        reconcile_required: false,
        next_action: "inspect_diagnostic",
      } : null,
      task_id: null,
      lane_id: null,
      correlation_id: "correlation-1",
      source_outcome_digest: digest("3"),
    },
  };
}

function runtimeOutcomeConsumption(overrides = {}) {
  return {
    schema_version: "runtime_outcome_consumption_public@1",
    consumption_id: "consumption-1",
    consumption_digest: digest("4"),
    command_id: "turn-command-1",
    command_digest: digest("a"),
    outcome_id: "outcome-1",
    outcome_digest: digest("3"),
    outcome_receipt_id: "outcome-receipt-1",
    outcome_receipt_digest: digest("1"),
    session_id: "session-1",
    agent_id: "agent-1",
    agent_member_id: "member-1",
    signal_id: "signal-1",
    signal_attempt: 1,
    continuation_intent_id: null,
    settlement_intent_id: "settlement-1",
    consumed_at: "2026-08-24T00:02:00Z",
    ...overrides,
  };
}

function failureObservation(overrides = {}) {
  return {
    schema_version: "failure_observation@2",
    failure_id: "failure-1",
    session_id: "session-1",
    source_kind: "runtime_turn",
    source_ref: "turn-command-1",
    source_version: digest("5"),
    phase: "settlement",
    failure_class: "runtime",
    recoverability: "agent_can_replan",
    effect_certainty: "no_effect",
    retry_eligibility: "same_phase_safe",
    actor_kind: "system",
    error_code: "runtime_turn_failed",
    safe_summary: "The runtime turn did not settle successfully.",
    facts: {
      fallback_performed: false,
      mutation_applied: false,
      missing_ids: ["outcome-1"],
      process_epoch: 1,
      retry_eligibility: "same_phase_safe",
      retry_performed: false,
    },
    likely_causes: ["The selected runtime returned a typed failure."],
    evidence_refs: ["diagnostic-1"],
    created_at: "2026-08-24T00:03:00Z",
    task_id: null,
    lane_id: null,
    agent_id: "agent-1",
    safe_hint: "Inspect the public diagnostic identity.",
    component: "runtime_owner",
    operation: "settle_outcome",
    identities: {
      command_id: "turn-command-1",
      session_id: "session-1",
      signal_id: "signal-1",
    },
    mutation_applied: false,
    fallback_performed: false,
    cause_chain: [{
      type: "RuntimeError",
      code: "runtime_failure",
      message_digest: digest("6"),
    }],
    diagnostic_id: "diagnostic-1",
    next_action: "inspect_diagnostic",
    ...overrides,
  };
}

function registry(entries = [], rendererCatalogDigest = digest("8")) {
  return new ExtensionRendererRegistry({ rendererCatalogDigest, entries });
}

test("plugin-free @2 projection yields a Core-only mutable shell", () => {
  const shell = buildCoreShellState(projection(), registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });

  assert.equal(shell.core.session.session_id, "session-1");
  assert.deepEqual(shell.extensionRendering.renderedSections, {});
  assert.equal(shell.contractBlocked, false);
  assert.equal(shell.mutationAllowed, true);
  assert.equal("extensions" in shell.core, false);
});

test("ready reconciliation preserves the failed intent without blocking the shell", () => {
  const payload = projection();
  const provisioning = payload.core.workspace.provisioning;
  provisioning.status = "blocked";
  provisioning.failure_id = "failure-original";
  provisioning.error_code = "workspace_provisioning_dispatch_in_doubt";
  provisioning.effect_certainty = "dispatch_in_doubt";
  provisioning.mutation_applied = null;
  provisioning.reconcile_required = true;
  provisioning.diagnostic_id = "diagnostic-original";
  provisioning.reconciliation = {
    schema_version: "workspace_provisioning_reconciliation_public@1",
    reconciliation_id: "reconciliation-1",
    reconciliation_digest: digest("1"),
    status: "ready",
    attempt: 1,
    parent_reconciliation_id: null,
    blocked_intent_state_version: 3,
    blocked_intent_digest: provisioning.intent_digest,
    source_receipt_id: "receipt-original",
    source_receipt_digest: digest("2"),
    dispatch_receipt_digest: digest("3"),
    result_receipt_id: "receipt-reconciled",
    result_receipt_digest: digest("4"),
    effect_certainty: "terminal_known",
    mutation_applied: true,
    fallback_performed: false,
    retry_permitted: false,
    reconcile_required: false,
    failure_id: null,
    diagnostic_id: null,
    requested_at: "2026-08-24T00:01:00Z",
    requested_claim_seconds: 60,
    settled_at: "2026-08-24T00:02:00Z",
    next_action: "message_or_drain",
  };

  const shell = buildCoreShellState(payload, registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });

  assert.equal(shell.contractBlocked, false);
  assert.equal(shell.mutationAllowed, true);
  assert.equal(shell.core.workspace.provisioning.status, "blocked");
  assert.equal(shell.core.workspace.provisioning.reconciliation.status, "ready");
});

test("extension payload is handled only by its exact manifest renderer", () => {
  const sectionContractDigest = digest("9");
  const rendererContractDigest = digest("a");
  const science = {
    attempts: [{ attempt_id: "attempt-1", scientific_terminal: "closed" }],
  };
  const shell = buildCoreShellState(
    projection({
      "openzyme.science@1": {
        section_contract_digest: sectionContractDigest,
        payload: science,
        next_cursor: null,
        projection_digest: digest("b"),
      },
    }),
    registry([{
      sectionId: "openzyme.science@1",
      sectionContractDigest,
      rendererId: "openzyme.science.renderer@1",
      rendererContractDigest,
      render(payload, identity) {
        return {
          attemptCount: payload.attempts.length,
          rendererId: identity.rendererId,
        };
      },
    }]),
    { expectedRendererCatalogDigest: digest("8") },
  );

  assert.deepEqual(shell.extensionRendering.renderedSections, {
    "openzyme.science@1": {
      attemptCount: 1,
      rendererId: "openzyme.science.renderer@1",
    },
  });
  assert.equal("attempts" in shell.core, false);
  assert.equal("scientific_terminal" in shell.core, false);
  assert.equal(shell.mutationAllowed, true);
});

test("missing or stale renderer identity blocks mutation without fallback", () => {
  const payload = projection({
    "openzyme.reporting@1": {
      section_contract_digest: digest("c"),
      payload: { reports: [] },
      next_cursor: null,
      projection_digest: digest("d"),
    },
  });
  const missing = buildCoreShellState(payload, registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });
  assert.equal(missing.mutationAllowed, false);
  assert.deepEqual(missing.extensionRendering.renderedSections, {});
  assert.equal(
    missing.extensionRendering.blockers[0].code,
    "extension_renderer_missing",
  );

  const staleCatalog = buildCoreShellState(payload, registry([], digest("e")), {
    expectedRendererCatalogDigest: digest("8"),
  });
  assert.equal(staleCatalog.mutationAllowed, false);
  assert.deepEqual(
    staleCatalog.extensionRendering.blockers.map((item) => item.code),
    ["renderer_catalog_drift", "extension_renderer_missing"],
  );
});

test("Core section rejects extension semantics while extension namespace permits them", () => {
  const invalid = projection();
  invalid.core.reports = [];
  assert.throws(
    () => buildCoreShellState(invalid, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    }),
    /core fields are closed/,
  );

  const extensionPayload = projection({
    "openzyme.reporting@1": {
      section_contract_digest: digest("f"),
      payload: { reports: [] },
      next_cursor: null,
      projection_digest: digest("0"),
    },
  });
  assert.doesNotThrow(() => buildCoreShellState(
    extensionPayload,
    registry([{
      sectionId: "openzyme.reporting@1",
      sectionContractDigest: digest("f"),
      rendererId: "openzyme.reporting.renderer@1",
      rendererContractDigest: digest("1"),
      render: () => ({ rendered: true }),
    }]),
    { expectedRendererCatalogDigest: digest("8") },
  ));
});

test("Core object subsection fields are closed", () => {
  const invalid = projection();
  invalid.core.workspace.legacy_status = [];
  assert.throws(
    () => buildCoreShellState(invalid, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    }),
    /core\.workspace fields are closed/,
  );
});

test("Python-parity forbidden Core tokens fail closed in generic records", () => {
  const forbiddenTokens = [
    "agentcapabilitylease",
    "agentcapabilityleaseid",
    "agentcapabilityleases",
    "alphafold",
    "aox",
    "arti" + "fact",
    "arti" + "factcatalog",
    "arti" + "factindex",
    "arti" + "factkind",
    "arti" + "facts",
    "arti" + "factset",
    "boundedstderr",
    "boundedstdout",
    "claimtoken",
    "compute",
    "context",
    "deliveryleasetoken",
    "docking",
    "fpocket",
    "hpc",
    "hpcstageref",
    "hpcworkspaces",
    "hmmer",
    "leasetoken",
    "privatecontext",
    "privatefailure",
    "reportdrafts",
    "reports",
    "research",
    "researchfiles",
    "revisionexecutions",
    "runtimeleasetoken",
    "scientificattempts",
    "scientificdeliverables",
    "scientificselections",
    "sessionleasetoken",
    "signalclaimtoken",
    "stderr",
    "stdout",
    "storageuri",
    "toolrequests",
    "traceback",
    "tracebacktext",
    "vina",
  ];
  const genericRecordLocations = [
    (payload, record) => { payload.core.conversation.messages = [record]; },
    (payload, record) => { payload.core.operations.command_receipts = [record]; },
  ];

  for (const fieldName of forbiddenTokens) {
    for (const placeRecord of genericRecordLocations) {
      const invalid = projection();
      placeRecord(invalid, { [fieldName]: "private-value" });
      assert.throws(
        () => buildCoreShellState(invalid, registry(), {
          expectedRendererCatalogDigest: digest("8"),
        }),
        new RegExp(`forbidden field.*${fieldName}`),
        fieldName,
      );
    }
  }
});

test("Python-parity forbidden Core fragments fail closed in generic records", () => {
  const forbiddenFragments = [
    "accesstoken",
    "credential",
    "hostpath",
    "lfsobjectlocator",
    "lfsobjectroot",
    "lfslocator",
    "loginalias",
    "privatekey",
    "privateref",
    "refreshtoken",
    "remoteroot",
    "repositoryroot",
    "schedulerhandle",
  ];
  const genericRecordLocations = [
    (payload, record) => { payload.core.conversation.messages = [record]; },
    (payload, record) => { payload.core.operations.command_receipts = [record]; },
  ];

  for (const fragment of forbiddenFragments) {
    const fieldName = `public_${fragment}_metadata`;
    for (const placeRecord of genericRecordLocations) {
      const invalid = projection();
      placeRecord(invalid, { [fieldName]: "private-value" });
      assert.throws(
        () => buildCoreShellState(invalid, registry(), {
          expectedRendererCatalogDigest: digest("8"),
        }),
        new RegExp(`forbidden field.*${fieldName}`),
        fieldName,
      );
    }
  }
});

test("closed public runtime turn and outcome summaries are accepted", () => {
  const payload = projection();
  payload.core.runtime.turn_commands = [runtimeTurnCommand()];
  payload.core.runtime.outcomes = [runtimeOutcomeReceipt()];

  const shell = buildCoreShellState(payload, registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });

  assert.equal(shell.contractBlocked, false);
  assert.equal(shell.core.runtime.turn_commands[0].message_count, 1);
  assert.equal(shell.core.runtime.outcomes[0].outcome.tool_request_count, 0);
  assert.equal("context" in shell.core.runtime.turn_commands[0], false);
  assert.equal("messages" in shell.core.runtime.outcomes[0].outcome, false);
  assert.equal("tool_requests" in shell.core.runtime.outcomes[0].outcome, false);
});

test("runtime projection rejects raw context, messages, tool requests and private fences", () => {
  const cases = [
    ["raw context", (payload) => {
      payload.core.runtime.turn_commands = [{
        ...runtimeTurnCommand(),
        context: { objective: "must-not-render" },
      }];
    }],
    ["raw command messages", (payload) => {
      payload.core.runtime.turn_commands = [{
        ...runtimeTurnCommand(),
        messages: [{ role: "system", content: "must-not-render" }],
      }];
    }],
    ["raw command tool requests", (payload) => {
      payload.core.runtime.turn_commands = [{
        ...runtimeTurnCommand(),
        tool_requests: [{ tool_name: "private.tool" }],
      }];
    }],
    ["runtime lease token", (payload) => {
      payload.core.runtime.turn_commands = [{
        ...runtimeTurnCommand(),
        runtime_lease_token: "private-runtime-lease",
      }];
    }],
    ["signal claim token", (payload) => {
      payload.core.runtime.turn_commands = [{
        ...runtimeTurnCommand(),
        signal_claim_token: "private-signal-claim",
      }];
    }],
    ["legacy raw command schema", (payload) => {
      payload.core.runtime.turn_commands = [{
        ...runtimeTurnCommand(),
        schema_version: "runtime_turn_command@2",
      }];
    }],
    ["turn command release drift", (payload) => {
      payload.core.runtime.turn_commands = [{
        ...runtimeTurnCommand(),
        release_digest: digest("0"),
      }];
    }],
    ["raw outcome messages", (payload) => {
      const receipt = runtimeOutcomeReceipt();
      receipt.outcome.messages = [{ role: "assistant", content: "must-not-render" }];
      payload.core.runtime.outcomes = [receipt];
    }],
    ["raw outcome tool requests", (payload) => {
      const receipt = runtimeOutcomeReceipt();
      receipt.outcome.tool_requests = [{ tool_name: "private.tool" }];
      payload.core.runtime.outcomes = [receipt];
    }],
    ["private failure traceback", (payload) => {
      const receipt = runtimeOutcomeReceipt({ failed: true });
      receipt.outcome.failure.traceback = "/private/path/runtime.py";
      payload.core.runtime.outcomes = [receipt];
    }],
    ["delivery lease token", (payload) => {
      const receipt = runtimeOutcomeReceipt();
      receipt.delivery_lease_token = "private-delivery-lease";
      payload.core.runtime.outcomes = [receipt];
    }],
  ];

  for (const [name, mutate] of cases) {
    const invalid = projection();
    mutate(invalid);
    assert.throws(
      () => buildCoreShellState(invalid, registry(), {
        expectedRendererCatalogDigest: digest("8"),
      }),
      /fields are closed|schema version is invalid|forbidden field|release identity drifted/,
      name,
    );
  }
});

test("closed runtime outcome consumption and failure observation are accepted", () => {
  const payload = projection();
  payload.core.runtime.outcome_consumptions = [runtimeOutcomeConsumption()];
  payload.core.failures.observations = [failureObservation()];

  const shell = buildCoreShellState(payload, registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });

  assert.equal(shell.contractBlocked, false);
  assert.equal(
    shell.core.runtime.outcome_consumptions[0].schema_version,
    "runtime_outcome_consumption_public@1",
  );
  assert.equal(
    shell.core.failures.observations[0].schema_version,
    "failure_observation@2",
  );
});

test("runtime outcome consumption rejects legacy, drifted and private fields", () => {
  const cases = [
    ["legacy schema", [runtimeOutcomeConsumption({
      schema_version: "runtime_outcome_consumption@2",
    })]],
    ["raw tool requests", [{
      ...runtimeOutcomeConsumption(),
      tool_requests: [{ tool_name: "private.tool" }],
    }]],
    ["claim token", [{
      ...runtimeOutcomeConsumption(),
      claim_token: "private-claim",
    }]],
    ["invalid digest", [runtimeOutcomeConsumption({
      outcome_digest: "outcome-digest",
    })]],
    ["invalid attempt", [runtimeOutcomeConsumption({ signal_attempt: 0 })]],
    ["Session drift", [runtimeOutcomeConsumption({ session_id: "session-2" })]],
    ["invalid continuation", [runtimeOutcomeConsumption({
      continuation_intent_id: "",
    })]],
    ["duplicate identity", [
      runtimeOutcomeConsumption(),
      runtimeOutcomeConsumption(),
    ]],
  ];
  for (const [name, consumptions] of cases) {
    const invalid = projection();
    invalid.core.runtime.outcome_consumptions = consumptions;
    assert.throws(
      () => buildCoreShellState(invalid, registry(), {
        expectedRendererCatalogDigest: digest("8"),
      }),
      /fields are closed|schema version|canonical SHA-256|positive integer|another Session|bounded identifier|duplicated/,
      name,
    );
  }

  const missing = projection();
  const incomplete = runtimeOutcomeConsumption();
  delete incomplete.consumed_at;
  missing.core.runtime.outcome_consumptions = [incomplete];
  assert.throws(
    () => buildCoreShellState(missing, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    }),
    /fields are closed/,
  );
});

test("failure observation rejects legacy and private diagnostic payloads", () => {
  const privateFields = [
    "traceback",
    "stdout",
    "stderr",
    "private_context",
    "tool_requests",
    "unexpected_field",
  ];
  for (const fieldName of privateFields) {
    const invalid = projection();
    invalid.core.failures.observations = [{
      ...failureObservation(),
      [fieldName]: fieldName === "tool_requests" ? [] : "must-not-render",
    }];
    assert.throws(
      () => buildCoreShellState(invalid, registry(), {
        expectedRendererCatalogDigest: digest("8"),
      }),
      /public failure observation fields are closed/,
      fieldName,
    );
  }

  const legacy = projection();
  legacy.core.failures.observations = [failureObservation({
    schema_version: "failure_observation@1",
  })];
  assert.throws(
    () => buildCoreShellState(legacy, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    }),
    /legacy failure observation is not public-compatible/,
  );
});

test("failure facts and identities enforce their public allowlists", () => {
  const cases = [
    ["traceback fact", failureObservation({ facts: { traceback: "secret" } })],
    ["stdout fact", failureObservation({ facts: { stdout: "secret" } })],
    ["tool requests fact", failureObservation({ facts: { tool_requests: [] } })],
    ["private identity", failureObservation({
      identities: { lease_token: "private-lease" },
    })],
    ["mapping fact", failureObservation({
      facts: { missing_ids: [{ private_context: "secret" }] },
    })],
    ["invalid classification", failureObservation({ failure_class: "exception" })],
    ["private path text", failureObservation({
      safe_summary: "Traceback stored at /home/operator/private.py",
    })],
    ["private cause field", failureObservation({
      cause_chain: [{
        type: "RuntimeError",
        code: "runtime_failure",
        message_digest: digest("6"),
        stderr: "secret",
      }],
    })],
  ];
  for (const [name, failure] of cases) {
    const invalid = projection();
    invalid.core.failures.observations = [failure];
    assert.throws(
      () => buildCoreShellState(invalid, registry(), {
        expectedRendererCatalogDigest: digest("8"),
      }),
      /fields are closed|non-public value|classification facts|public-safe text/,
      name,
    );
  }

  const duplicate = projection();
  duplicate.core.failures.observations = [failureObservation(), failureObservation()];
  assert.throws(
    () => buildCoreShellState(duplicate, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    }),
    /identity is duplicated/,
  );
});

test("verified projection change observation carries renderable facts", () => {
  const payload = projection();
  const projectionDigest = digest("f");
  const observation = buildFileWorkspaceV2ProjectionObservation({
    projection: payload,
    projectionDigest,
  });
  const shell = buildCoreShellState(payload, registry(), {
    expectedRendererCatalogDigest: digest("8"),
    projectionDigest,
  });

  const accepted = reduceCoreShellProjectionObservation(shell, observation);

  assert.equal(accepted.contractBlocked, false);
  assert.equal(accepted.projectionObservations.length, 1);
  assert.equal(
    accepted.projectionObservations[0].facts.readiness,
    "ready",
  );
  assert.equal(
    accepted.projectionObservations[0].facts.transcript_digest,
    payload.core.conversation.transcript.transcript_digest,
  );
  assert.equal(accepted.lastProjectionObservationId, projectionDigest);
});

test("release-drifted projection observation fails closed", () => {
  const payload = projection();
  const projectionDigest = digest("f");
  const observation = buildFileWorkspaceV2ProjectionObservation({
    projection: payload,
    projectionDigest,
  });
  observation.release_digest = digest("0");
  const shell = buildCoreShellState(payload, registry(), {
    expectedRendererCatalogDigest: digest("8"),
    projectionDigest,
  });

  const blocked = reduceCoreShellProjectionObservation(shell, observation);

  assert.equal(blocked.contractBlocked, true);
  assert.equal(blocked.mutationAllowed, false);
  assert.match(blocked.blockingError, /release identity drifted/);
});

test("stale projection observation blocks Core mutation instead of translating it", () => {
  const shell = buildCoreShellState(projection(), registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });
  const blocked = reduceCoreShellProjectionObservation(shell, {
    schema_version: "file_workspace_public@1",
    observation_id: "observation-old",
  });
  assert.equal(blocked.contractBlocked, true);
  assert.equal(blocked.mutationAllowed, false);
  assert.equal(blocked.refreshRequired, false);
});

test("renderer registry rejects duplicate section ownership", () => {
  const entry = {
    sectionId: "openzyme.science@1",
    sectionContractDigest: digest("2"),
    rendererId: "openzyme.science.renderer@1",
    rendererContractDigest: digest("3"),
    render: () => ({}),
  };
  assert.throws(
    () => registry([entry, entry]),
    /duplicated/,
  );
});

test("inactive or degraded plugin affordance stays visible but cannot dispatch", () => {
  for (const [state, blockerCode] of [
    ["blocked_dependency", "plugin_inactive"],
    ["blocked_qualification", "plugin_degraded"],
  ]) {
    const payload = projection();
    payload.core.tool_reflection.affordances = [{
      tool_name: "openzyme.science.inspect",
      tool_contract_digest: digest("1"),
      state,
      required_authorities: [],
      route_ids: [],
      route_refs: [],
      blockers: [{ code: blockerCode, requirement: null, target_id: null }],
    }];
    payload.core.tool_reflection.tool_exposure.deferred_tool_names = [
      "openzyme.science.inspect",
    ];
    const shell = buildCoreShellState(payload, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    });

    assert.equal(shell.mutationAllowed, true);
    assert.equal(shell.toolAffordances[0].state, state);
    assert.throws(
      () => requireAvailableTool(shell, "openzyme.science.inspect"),
      new RegExp(`${blockerCode}.*fallback_performed=false`),
    );
  }
});

test("available tool list and affordance state must agree exactly", () => {
  const payload = projection();
  payload.core.tool_reflection.available_tool_names = ["workspace.status"];
  assert.throws(
    () => buildCoreShellState(payload, registry(), {
      expectedRendererCatalogDigest: digest("8"),
    }),
    /available tool names differ/,
  );
});

test("available Deferred affordance is reflected but never callable", () => {
  const payload = projection();
  payload.core.tool_reflection.affordances = [{
    tool_name: "openzyme.science.inspect",
    tool_contract_digest: digest("1"),
    state: "available",
    required_authorities: [],
    route_ids: [],
    route_refs: [],
    blockers: [],
  }];
  payload.core.tool_reflection.tool_exposure.deferred_tool_names = [
    "openzyme.science.inspect",
  ];
  const shell = buildCoreShellState(payload, registry(), {
    expectedRendererCatalogDigest: digest("8"),
  });

  assert.deepEqual(shell.availableToolNames, []);
  assert.equal(shell.toolAffordances[0].tool_name, "openzyme.science.inspect");
  assert.throws(
    () => requireAvailableTool(shell, "openzyme.science.inspect"),
    /Deferred or Hidden.*fallback_performed=false/,
  );
});

test("packaged TypeScript contract snapshot names the exact @2 ownership split", async () => {
  const declaration = await readFile(
    new URL("../src/file_workspace_v2_types.d.ts", import.meta.url),
    "utf8",
  );
  for (const required of [
    "file_workspace_public@2",
    "LayeredReleaseIdentityV2",
    "FileWorkspaceV2Core",
    "RuntimeOutcomeConsumptionPublicV1",
    "FailureObservationPublicV2",
    "PublicToolAffordanceState",
    "RuntimeCommandStatusV1",
    "extensions: Record<string, FileWorkspaceV2ExtensionSection>",
  ]) {
    assert.equal(declaration.includes(required), true, required);
  }
  for (const forbidden of ["scientific_attempts", "reports:", "hpc_workspaces"] ) {
    assert.equal(declaration.includes(forbidden), false, forbidden);
  }
});
