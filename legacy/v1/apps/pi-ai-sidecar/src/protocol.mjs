import { readFileSync } from "node:fs";
import readline from "node:readline";

import { SidecarError } from "./errors.mjs";
import { executeOperation } from "./provider.mjs";
import { validateRequest } from "./schemas.mjs";

export async function handleRequest(rawRequest, sidecarConfig) {
  let request;
  try {
    request = validateRequest(rawRequest);
  } catch (error) {
    return buildErrorResponse(rawRequest?.requestId, rawRequest?.operation, sidecarConfig, new SidecarError("invalid-request", String(error?.message || error)));
  }

  try {
    const result = await executeOperation(request, sidecarConfig);
    return {
      requestId: request.requestId,
      operation: request.operation,
      ok: true,
      result,
      provenance: buildProvenance(sidecarConfig),
    };
  } catch (error) {
    return buildErrorResponse(request.requestId, request.operation, sidecarConfig, error);
  }
}

export async function serve(readable, writable, sidecarConfig) {
  const lineReader = readline.createInterface({
    input: readable,
    crlfDelay: Infinity,
  });
  for await (const line of lineReader) {
    if (!line.trim()) {
      continue;
    }
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch (error) {
      writable.write(
        `${JSON.stringify(buildErrorResponse(null, null, sidecarConfig, new SidecarError("invalid-request", "Request body must be valid JSON.")))}\n`
      );
      continue;
    }
    const response = await handleRequest(parsed, sidecarConfig);
    writable.write(`${JSON.stringify(response)}\n`);
  }
}

function buildErrorResponse(requestId, operation, sidecarConfig, error) {
  const normalized = error instanceof SidecarError ? error : new SidecarError("internal", String(error?.message || error));
  return {
    requestId: typeof requestId === "string" ? requestId : null,
    operation: typeof operation === "string" ? operation : null,
    ok: false,
    error: {
      category: normalized.category,
      summary: normalized.summary,
      retryable: normalized.retryable,
      backend: sidecarConfig.backend,
      provider: sidecarConfig.provider,
      model: sidecarConfig.model,
    },
    provenance: buildProvenance(sidecarConfig),
  };
}

function buildProvenance(sidecarConfig) {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf-8"));
  return {
    backend: sidecarConfig.backend,
    provider: sidecarConfig.provider,
    model: sidecarConfig.model,
    sidecar: {
      name: pkg.name,
      version: pkg.version,
    },
  };
}
