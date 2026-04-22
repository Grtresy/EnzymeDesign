import { HostApiClient } from "./client.js";
import { WorkspaceController } from "./controller.js";
import {
  renderAppShell,
  renderComposerStatus,
  renderConversationHeader,
  renderInspector,
  renderInspectorContent,
  renderInspectorHeader,
  renderMainColumn,
  renderSessionTree,
  renderSidebar,
  renderSidebarStatus,
  renderV3Approvals,
  renderV3Conversation,
} from "./view.js";

const client = new HostApiClient(window.OPENZYME_HOST_API_BASE ?? "");
const appElement = document.querySelector("#app");
const controller = new WorkspaceController(client, repaint);

function ensureShell() {
  if (!document.querySelector("#sidebar-column-root")) {
    appElement.innerHTML = renderAppShell(controller.state);
  }
}

function setButtonDisabled(selector, disabled) {
  const button = document.querySelector(selector);
  if (button instanceof HTMLButtonElement) {
    button.disabled = disabled;
  }
}

function syncComposerScroll() {
  const list = document.querySelector(".chat-list");
  if (!(list instanceof HTMLElement)) {
    return;
  }
  const wasNearBottom = list.dataset.stickToBottom !== "false";
  if (wasNearBottom) {
    list.scrollTop = list.scrollHeight;
  }
}

function bindScrollableChatState() {
  const list = document.querySelector(".chat-list");
  if (!(list instanceof HTMLElement) || list.dataset.scrollBound === "true") {
    return;
  }
  list.addEventListener("scroll", () => {
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 48;
    list.dataset.stickToBottom = nearBottom ? "true" : "false";
  });
  list.dataset.scrollBound = "true";
  list.dataset.stickToBottom = "true";
}

function repaint() {
  ensureShell();
  const sidebarRoot = document.querySelector("#sidebar-column-root");
  const mainRoot = document.querySelector("#main-column-root");
  const inspectorRoot = document.querySelector("#inspector-column-root");
  if (!sidebarRoot || !mainRoot || !inspectorRoot) {
    appElement.innerHTML = renderAppShell(controller.state);
    bindActions();
    bindScrollableChatState();
    syncComposerScroll();
    return;
  }

  const sidebarStatus = document.querySelector("#sidebar-status-root");
  const sidebarTree = document.querySelector("#sidebar-tree-root");
  const sessionCount = document.querySelector("#session-count-root");
  if (!document.querySelector("#create-session-form")) {
    sidebarRoot.innerHTML = renderSidebar(controller.state);
  } else {
    if (sidebarStatus) {
      sidebarStatus.innerHTML = renderSidebarStatus(controller.state);
    }
    if (sidebarTree) {
      sidebarTree.innerHTML = renderSessionTree(controller.state);
    }
    if (sessionCount) {
      sessionCount.textContent = controller.state.sidebarBusy ? "Loading..." : `${controller.state.sessionSummaries.length}`;
    }
    setButtonDisabled("#create-session-submit", controller.state.createSessionBusy);
  }

  const hasWorkspace = Boolean(controller.state.workspace?.session);
  const messageForm = document.querySelector("#message-form");
  if (!hasWorkspace || !(messageForm instanceof HTMLFormElement)) {
    mainRoot.innerHTML = renderMainColumn(controller.state);
  } else {
    const conversationHeader = document.querySelector("#conversation-header-root");
    const conversationList = document.querySelector("#conversation-list-root");
    const approvalStack = document.querySelector("#approval-stack-root");
    const composerStatus = document.querySelector("#composer-status-root");
    if (conversationHeader) {
      conversationHeader.innerHTML = renderConversationHeader(controller.state);
    }
    if (conversationList) {
      conversationList.innerHTML = renderV3Conversation(controller.state.workspace);
    }
    if (approvalStack) {
      approvalStack.innerHTML = renderV3Approvals(controller.state.workspace, controller.state);
    }
    if (composerStatus) {
      composerStatus.innerHTML = renderComposerStatus(controller.state);
    }
    const messageInput = document.querySelector("#message-form textarea[name='message']");
    if (messageInput instanceof HTMLTextAreaElement) {
      messageInput.disabled = controller.state.messageBusy;
    }
    setButtonDisabled("#message-submit", controller.state.messageBusy);
  }

  const inspectorHeader = document.querySelector("#inspector-header-root");
  const inspectorContent = document.querySelector("#inspector-content-root");
  if (inspectorHeader && inspectorContent) {
    inspectorHeader.innerHTML = renderInspectorHeader(controller.state);
    inspectorContent.innerHTML = renderInspectorContent(controller.state);
  } else {
    inspectorRoot.innerHTML = renderInspector(controller.state);
  }

  bindActions();
  bindScrollableChatState();
  syncComposerScroll();
}

async function onSubmit(event) {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  if (form.id === "create-session-form") {
    event.preventDefault();
    const success = await controller.createSession({
      project_id: String(new FormData(form).get("project_id") ?? ""),
      title: String(new FormData(form).get("title") ?? "").trim() || null,
      objective: String(new FormData(form).get("objective") ?? ""),
    });
    if (success) {
      document.querySelector("#create-session-form")?.reset();
    }
    return;
  }
  if (form.id === "message-form") {
    event.preventDefault();
    const formData = new FormData(form);
    const success = await controller.sendMessage(String(formData.get("message") ?? ""));
    if (success) {
      document.querySelector("#message-form")?.reset();
    }
  }
}

async function onClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const sessionToggle = target.closest("[data-action='toggle-session']");
  if (sessionToggle instanceof HTMLElement) {
    controller.toggleSessionTree(sessionToggle.dataset.sessionId);
    return;
  }
  const sessionSelect = target.closest("[data-action='select-session']");
  if (sessionSelect instanceof HTMLElement) {
    await controller.selectSession(sessionSelect.dataset.sessionId, "conversation");
    return;
  }
  const sectionSelect = target.closest("[data-action='select-section']");
  if (sectionSelect instanceof HTMLElement) {
    const sessionId = sectionSelect.dataset.sessionId;
    const section = sectionSelect.dataset.section;
    if (controller.state.currentSessionId !== sessionId) {
      await controller.selectSession(sessionId, section);
      return;
    }
    controller.selectSection(section);
    return;
  }
  const approvalButton = target.closest("[data-v3-approval-decision]");
  if (approvalButton instanceof HTMLElement) {
    await controller.resolveApproval(approvalButton.dataset.approvalId, approvalButton.dataset.v3ApprovalDecision);
  }
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
