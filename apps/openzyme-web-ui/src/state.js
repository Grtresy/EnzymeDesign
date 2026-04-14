function ensureWorkspace(workspace) {
  if (!workspace || !workspace.workflow) {
    throw new Error("workspace projection is required");
  }
  workspace.research ??= {
    status: "idle",
    completion_reason: null,
    clarification_question: null,
    summary: null,
    evidence: [],
    source_refs: [],
    unresolved_gaps: [],
    turns: [],
  };
  workspace.design ??= {
    candidates: [],
    rankings: [],
    selected_candidate: null,
  };
  workspace.report ??= null;
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
    case "workflow.summary_updated":
      next.workflow.summary = event.summary;
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
    case "workflow.evidence_updated":
      next.research = event.research;
      return next;
    case "workflow.research_turn_recorded":
      next.research.turns = mergeById(next.research.turns ?? [], event.turn, "created_at");
      return next;
    case "workflow.candidate_updated":
      next.design = event.design;
      return next;
    case "workflow.selected_candidate_changed":
      next.design.selected_candidate = event.selected_candidate;
      return next;
    case "workflow.report_available":
      next.report = event.report;
      next.workflow.summary = {
        ...(next.workflow.summary ?? {}),
        report_id: event.report.report_id,
        report_status: event.report.status,
      };
      return next;
    default:
      return next;
  }
}

export function buildInitialViewState() {
  return {
    projects: [],
    episodes: [],
    currentProjectId: "",
    currentEpisodeId: "",
    workspace: null,
    errorMessage: "",
    busy: false,
  };
}
