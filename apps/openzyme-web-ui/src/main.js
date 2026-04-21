import { HostApiClient } from "./client.js";
import { WorkspaceController } from "./controller.js";
import {
  renderApp,
  renderFormPanel,
  renderV3Activity,
  renderV3Approvals,
  renderV3Capabilities,
  renderV3Conversation,
  renderV3Hero,
  renderV3Lanes,
  renderV3Outputs,
  renderV3TaskBoard,
} from "./view.js";

const client = new HostApiClient(window.OPENZYME_HOST_API_BASE ?? "");
const appElement = document.querySelector("#app");
const controller = new WorkspaceController(client, repaint);
let lastRenderKey = null;

function snapshotActiveField() {
  const active = document.activeElement;
  if (!(active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement)) {
    return null;
  }
  if (!appElement.contains(active)) {
    return null;
  }
  if (active.id) {
    return {
      selector: `#${active.id}`,
      value: active.value,
      selectionStart: active.selectionStart,
      selectionEnd: active.selectionEnd,
    };
  }
  if (active.name && active.form?.id) {
    return {
      selector: `#${active.form.id} [name="${active.name}"]`,
      value: active.value,
      selectionStart: active.selectionStart,
      selectionEnd: active.selectionEnd,
    };
  }
  return null;
}

function restoreActiveField(snapshot) {
  if (!snapshot) {
    return;
  }
  const field = document.querySelector(snapshot.selector);
  if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement)) {
    return;
  }
  field.value = snapshot.value;
  field.focus();
  if (
    typeof snapshot.selectionStart === "number" &&
    typeof snapshot.selectionEnd === "number"
  ) {
    field.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
  }
}

function renderKey(state) {
  if (!state.workspace?.session) {
    return "empty";
  }
  return `v3:${state.workspace.session.session_id}`;
}

function applyV3Patch(state) {
  const workspace = state.workspace;
  if (!workspace?.session) {
    return false;
  }
  const formRoot = document.querySelector("#form-panel-root");
  const hero = document.querySelector("#v3-hero-panel");
  const conversation = document.querySelector("#v3-conversation-list");
  const approvals = document.querySelector("#v3-approval-stack");
  const taskBoard = document.querySelector("#v3-task-board");
  const laneBoard = document.querySelector("#v3-lane-board");
  const activity = document.querySelector("#v3-activity-feed");
  const outputs = document.querySelector("#v3-outputs");
  const capabilities = document.querySelector("#v3-capabilities");
  const messageInput = document.querySelector("#message-form input[name='message']");
  const messageButton = document.querySelector("#message-form button[type='submit']");
  if (
    !formRoot ||
    !hero ||
    !conversation ||
    !approvals ||
    !taskBoard ||
    !laneBoard ||
    !activity ||
    !outputs ||
    !capabilities ||
    !(messageInput instanceof HTMLInputElement) ||
    !(messageButton instanceof HTMLButtonElement)
  ) {
    return false;
  }
  formRoot.innerHTML = renderFormPanel(state);
  hero.innerHTML = renderV3Hero(workspace);
  conversation.innerHTML = renderV3Conversation(workspace);
  approvals.innerHTML = renderV3Approvals(workspace, state);
  taskBoard.innerHTML = renderV3TaskBoard(workspace);
  laneBoard.innerHTML = renderV3Lanes(workspace);
  activity.innerHTML = renderV3Activity(workspace);
  outputs.innerHTML = renderV3Outputs(workspace);
  capabilities.innerHTML = renderV3Capabilities(workspace);
  messageInput.disabled = state.busy;
  messageButton.disabled = state.busy;
  return true;
}

function repaint() {
  const nextRenderKey = renderKey(controller.state);
  if (lastRenderKey === nextRenderKey && nextRenderKey.startsWith("v3:")) {
    if (applyV3Patch(controller.state)) {
      bindActions();
      return;
    }
  }
  const activeField = snapshotActiveField();
  appElement.innerHTML = renderApp(controller.state);
  bindActions();
  restoreActiveField(activeField);
  lastRenderKey = nextRenderKey;
}

async function handleCreate(formData) {
  await controller.createSession({
    project_id: formData.get("project_id"),
    objective: formData.get("objective"),
  });
}

async function handleMessage(formData) {
  await controller.sendMessage(String(formData.get("message") ?? ""));
}

async function handleApproval(decision) {
  await controller.resolveApproval(decision);
}

async function onSubmit(event) {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  if (form.id === "create-session-form") {
    event.preventDefault();
    await handleCreate(new FormData(form));
    return;
  }
  if (form.id === "message-form") {
    event.preventDefault();
    await handleMessage(new FormData(form));
  }
}

async function onClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const approvalButton = target.closest("[data-v3-approval-decision]");
  if (!(approvalButton instanceof HTMLElement)) {
    return;
  }
  await handleApproval(approvalButton.dataset.v3ApprovalDecision);
}

function bindActions() {
  if (appElement.dataset.actionsBound === "true") {
    return;
  }
  appElement.addEventListener("submit", (event) => {
    void onSubmit(event);
  });
  appElement.addEventListener("click", (event) => {
    void onClick(event);
  });
  appElement.dataset.actionsBound = "true";
}

repaint();
void controller.bootstrap();
