import {
  reduceFileWorkspaceV2ProjectionObservation,
  requireFileWorkspaceV2Projection,
} from "./file_workspace_v2_state.js";

export function buildCoreShellState(payload, rendererRegistry, options) {
  const projection = requireFileWorkspaceV2Projection(payload);
  const extensionRendering = rendererRegistry.resolve(projection, options);
  const residentReadiness = projection.core.session.resident_readiness.readiness;
  const mutationAllowed = extensionRendering.mutationAllowed;
  const residentReady = residentReadiness === "ready";
  const projectionObservations = structuredClone(
    options?.projectionObservations ?? [],
  );
  return {
    schemaVersion: projection.schema_version,
    release: projection.release,
    // The Core reducer owns only this clone. Extension payloads remain inside
    // renderer output and are never merged into canonical Core UI state.
    core: structuredClone(projection.core),
    toolAffordances: structuredClone(projection.core.tool_reflection.affordances),
    availableToolNames: structuredClone(
      projection.core.tool_reflection.available_tool_names,
    ),
    extensionRendering,
    residentReadiness,
    residentReady,
    contractBlocked: !mutationAllowed,
    mutationAllowed,
    messageAllowed: mutationAllowed && residentReady,
    runtimeDrainAllowed: mutationAllowed && residentReady,
    approvalDecisionAllowed: mutationAllowed && residentReady,
    blockingError: extensionRendering.blockers.map((item) => item.code).join(","),
    refreshRequired: false,
    currentProjectionDigest: options?.projectionDigest ?? null,
    projectionObservations,
    lastProjectionObservationId: projectionObservations.length
      ? projectionObservations[projectionObservations.length - 1].observation_id
      : null,
  };
}

export function reduceCoreShellProjectionObservation(state, observation) {
  return reduceFileWorkspaceV2ProjectionObservation(state, observation);
}
