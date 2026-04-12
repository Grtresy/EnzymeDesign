import { HostApiClient } from "./client.js";
import { WorkspaceController } from "./controller.js";
import { renderApp } from "./view.js";

const client = new HostApiClient(window.OPENZYME_HOST_API_BASE ?? "");
const appElement = document.querySelector("#app");
const controller = new WorkspaceController(client, repaint);

function repaint() {
  appElement.innerHTML = renderApp(controller.state);
  bindActions();
}

async function handleCreate(formData) {
  await controller.createEpisode({
    project_id: formData.get("project_id"),
    objective: formData.get("objective"),
  });
}

async function handleProjectSelection(projectId) {
  await controller.selectProject(projectId);
}

async function handleEpisodeSelection(episodeId) {
  await controller.selectEpisode(episodeId);
}

async function handleResume() {
  if (!controller.state.currentEpisodeId) {
    return;
  }
  await controller.resumeEpisode({ approved: true });
}

async function handleApproval(decision) {
  if (!controller.state.currentEpisodeId || !controller.state.workspace?.workflow?.pending_approval?.approval_id) {
    return;
  }
  await controller.resolveApproval(decision);
}

function bindActions() {
  const form = document.querySelector("#create-episode-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await handleCreate(new FormData(form));
  });

  document.querySelector('[data-action="resume"]')?.addEventListener("click", handleResume);
  document.querySelector('[data-action="approve"]')?.addEventListener("click", async () => {
    await handleApproval("approved");
  });
  document.querySelector('[data-action="reject"]')?.addEventListener("click", async () => {
    await handleApproval("rejected");
  });
  document.querySelector("#project-select")?.addEventListener("change", async (event) => {
    await handleProjectSelection(event.target.value);
  });
  document.querySelectorAll("[data-episode-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await handleEpisodeSelection(button.dataset.episodeId);
    });
  });
}

repaint();
void controller.bootstrap();
