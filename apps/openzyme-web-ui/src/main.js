import { HostApiV2Client } from "./client.js";
import { WorkspaceControllerV2 } from "./controller.js";
import { ExtensionRendererRegistry } from "./extension_renderer_loader.js";
import { renderApp } from "./view.js";

const appElement = document.querySelector("#app");

function requireConfiguration() {
  const config = window.OPENZYME_WEB_UI_V2;
  if (!config || typeof config !== "object") {
    throw new Error("Distribution did not inject OPENZYME_WEB_UI_V2 exact contract configuration");
  }
  if (!config.release || !config.rendererCatalogDigest) {
    throw new Error("Web UI release or renderer catalog identity is missing");
  }
  const params = new URLSearchParams(window.location.search);
  const sessionId = config.sessionId ?? params.get("session_id") ?? "";
  return { ...config, sessionId };
}

function gestureIdentity(kind) {
  const value = globalThis.crypto?.randomUUID?.();
  if (!value) throw new Error("Web Crypto randomUUID is required for mutation identity");
  return `web-ui:${kind}:${value}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderStartupFailure(error) {
  appElement.innerHTML = `<main class="app-shell"><section class="error-banner" role="alert"><h1>OpenZyme UI is non-operational</h1><p>${escapeHtml(error.message ?? error)}</p><p>No legacy workspace fallback was attempted.</p></section></main>`;
}

try {
  const config = requireConfiguration();
  const rendererRegistry = new ExtensionRendererRegistry({
    rendererCatalogDigest: config.rendererCatalogDigest,
    entries: window.OPENZYME_EXTENSION_RENDERERS ?? [],
  });
  const client = new HostApiV2Client({
    baseUrl: window.OPENZYME_HOST_API_BASE ?? "",
    expectedRelease: config.release,
    authToken: config.authToken ?? null,
  });
  const controller = new WorkspaceControllerV2({
    client,
    rendererRegistry,
    expectedRendererCatalogDigest: config.rendererCatalogDigest,
    onChange: repaint,
  });

  function repaint() {
    appElement.innerHTML = renderApp(controller.state);
  }

  appElement.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.id !== "message-form") return;
    event.preventDefault();
    const message = String(new FormData(form).get("message") ?? "");
    void controller.sendMessage(message, gestureIdentity("message"));
  });

  appElement.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.closest("[data-action='refresh']")) {
      void controller.refresh();
    }
    if (target.closest("[data-action='runtime-drain']")) {
      void controller.drainRuntime({}, gestureIdentity("runtime-drain"));
    }
  });

  window.addEventListener("beforeunload", () => controller.close(), { once: true });
  repaint();
  void controller.bootstrap(config.sessionId);
} catch (error) {
  renderStartupFailure(error);
}
