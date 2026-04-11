function ensureWorkspace(workspace) {
  if (!workspace || !workspace.workflow) {
    throw new Error("workspace projection is required");
  }
}

function mergeById(items, nextItem, idField) {
  const index = items.findIndex((item) => item[idField] === nextItem[idField]);
  if (index === -1) {
    return [...items, nextItem];
  }
  const clone = items.slice();
  clone[index] = nextItem;
  return clone;
}

export function reduceWorkspaceWithEvent(workspace, event) {
  ensureWorkspace(workspace);
  const next = structuredClone(workspace);

  switch (event.event_type) {
    case "workflow.phase_changed":
      next.workflow.current_phase = event.phase;
      next.workflow.updated_at = event.updated_at;
      return next;
    case "workflow.progress_updated":
      next.workflow.progress = event.progress;
      next.workflow.updated_at = event.updated_at;
      return next;
    case "workflow.interrupt_pending":
      next.workflow.pending_interrupt = event.interrupt;
      next.workflow.updated_at = event.updated_at;
      return next;
    case "workflow.approval_pending":
      next.workflow.pending_approval = event.approval;
      next.pending_actions = mergeById(next.pending_actions, event.approval, "approval_id");
      return next;
    case "workflow.run_status_changed":
      next.runs = mergeById(next.runs, event.run, "run_id");
      return next;
    case "workflow.artifact_available":
      next.artifacts = mergeById(next.artifacts, event.artifact, "artifact_id");
      return next;
    case "workflow.report_available":
      next.report = event.report;
      return next;
    default:
      return next;
  }
}

export function buildInitialViewState() {
  return {
    currentEpisodeId: "",
    workspace: null,
    errorMessage: "",
    busy: false,
  };
}
