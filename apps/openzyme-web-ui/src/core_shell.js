import {
  reduceFileWorkspaceV2CoreEvent,
  requireFileWorkspaceV2Projection,
} from "./file_workspace_v2_state.js";

export function buildCoreShellState(payload, rendererRegistry, options) {
  const projection = requireFileWorkspaceV2Projection(payload);
  const extensionRendering = rendererRegistry.resolve(projection, options);
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
    contractBlocked: !extensionRendering.mutationAllowed,
    mutationAllowed: extensionRendering.mutationAllowed,
    blockingError: extensionRendering.blockers.map((item) => item.code).join(","),
    refreshRequired: false,
    lastEventId: null,
  };
}

export function reduceCoreShellEvent(state, event) {
  return reduceFileWorkspaceV2CoreEvent(state, event);
}
