import test from "node:test";
import assert from "node:assert/strict";
import { Readable } from "node:stream";
import { Writable } from "node:stream";

import { handleRequest, serve } from "../src/protocol.mjs";

test("sidecar serves structured JSONL success responses", async () => {
  const output = await runServe(
    {
      backend: "llm-sidecar",
      provider: "fake",
      model: "fake-structured-agent",
      timeoutSeconds: 1,
      allowFallback: true,
      fakeMode: "success",
    },
    [
      {
        requestId: "req-1",
        operation: "propose_candidate_actions",
        backend: { name: "llm-sidecar" },
        context: {
          state: {
            episode_id: "0001",
            objective: "Improve binding",
          },
        },
      },
    ]
  );

  assert.equal(output.length, 1);
  assert.equal(output[0].ok, true);
  assert.equal(output[0].provenance.provider, "fake");
  assert.equal(output[0].result[0].kind, "tool");
});

test("sidecar rejects invalid structured output", async () => {
  const response = await handleRequest(
    {
      requestId: "req-2",
      operation: "select_action",
      backend: { name: "llm-sidecar" },
      context: {
        state: {
          episode_id: "0001",
          objective: "Improve binding",
        },
        candidates: [],
      },
    },
    {
      backend: "llm-sidecar",
      provider: "fake",
      model: "fake-structured-agent",
      timeoutSeconds: 1,
      allowFallback: true,
      fakeMode: "invalid-structure",
    }
  );

  assert.equal(response.ok, false);
  assert.equal(response.error.category, "schema-validation");
});

test("sidecar maps provider timeouts to retryable timeout errors", async () => {
  const response = await handleRequest(
    {
      requestId: "req-3",
      operation: "summarize_observation",
      backend: { name: "llm-sidecar" },
      context: {
        state: {
          episode_id: "0001",
          objective: "Improve binding",
        },
        observation: {
          summary: "Tool finished",
        },
      },
    },
    {
      backend: "llm-sidecar",
      provider: "fake",
      model: "fake-structured-agent",
      timeoutSeconds: 0.01,
      allowFallback: true,
      fakeMode: "timeout",
    }
  );

  assert.equal(response.ok, false);
  assert.equal(response.error.category, "timeout");
  assert.equal(response.error.retryable, true);
});

test("sidecar maps provider failures to normalized categories", async () => {
  const response = await handleRequest(
    {
      requestId: "req-4",
      operation: "derive_design_contract",
      backend: { name: "llm-sidecar" },
      context: {
        state: {
          episode_id: "0001",
          objective: "Improve binding",
        },
      },
    },
    {
      backend: "llm-sidecar",
      provider: "fake",
      model: "fake-structured-agent",
      timeoutSeconds: 1,
      allowFallback: true,
      fakeMode: "provider-error",
    }
  );

  assert.equal(response.ok, false);
  assert.equal(response.error.category, "provider-unavailable");
  assert.equal(response.error.retryable, true);
});

async function runServe(config, requests) {
  let buffer = "";
  const writable = new Writable({
    write(chunk, _encoding, callback) {
      buffer += chunk.toString();
      callback();
    },
  });
  const input = Readable.from(requests.map((item) => `${JSON.stringify(item)}\n`));
  await serve(input, writable, config);
  return buffer
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}
