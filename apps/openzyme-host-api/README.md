# openzyme-host-api

V3 Host API app for OpenZyme.

## Scope

This app exposes the V3 Host-side API surface for:

- session creation and workspace queries
- message ingress and explicit `runtime/drain`
- task board, lane, approval, and debug endpoints
- V3 session events consumed by the Web UI

## Local Workflow Evals

Run the V3 workflow smoke eval locally:

1. `cd /home/grtresy/VSCodeRepo/EnzymeDesign`
2. `uv run python -m openzyme_host_api.evals`

The eval harness uses an ephemeral sqlite database and deterministic execution/research adapters. It is the supported local regression path for the V3 Host API loop.

### Real LLM Configuration

The local eval path can optionally use an OpenAI-compatible chat model.

Use the repository-level environment file conventions described in [README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/README.md:39):

1. copy [`.env.example`](/home/grtresy/VSCodeRepo/EnzymeDesign/.env.example) to `.env`
2. set `OPENZYME_LLM_API_KEY=<your-api-key>`
3. keep or override the default Zhipu Coding settings as needed:
   - `OPENZYME_LLM_MODEL=glm-5.1`
   - `OPENZYME_LLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4`
   - `OPENZYME_LLM_EXTRA_BODY=<optional-json-object>`
   - `OPENZYME_LLM_MAX_TOKENS=<optional-output-cap>`
   - `OPENZYME_LLM_TIMEOUT=60`
   - `OPENZYME_LLM_MAX_RETRIES=1`
   - `OPENZYME_LLM_TEMPERATURE=0`
   - `OPENZYME_LLM_STRUCTURED_OUTPUT_METHOD=function_calling`
4. run `uv run python -m openzyme_host_api.evals`

If no API key is set, the local eval harness keeps using the deterministic fallback path.
For the current Zhipu OpenAI-compatible endpoint, `function_calling` is the recommended structured-output strategy. If the provider requires extra request payload fields, set them through `OPENZYME_LLM_EXTRA_BODY`.

By default the eval harness stays local and does not upload LangSmith results. To emit LangSmith traces:

1. set `OPENZYME_LANGSMITH_TRACING=true`
2. optionally set `OPENZYME_LANGSMITH_PROJECT=<project-name>`
3. run `uv run python -m openzyme_host_api.evals --upload-results`

## Live Integration Suites

For real-provider tests, keep the environment rules from the repository-level [README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/README.md:39) and enable the relevant `.env.test` flags:

- `OPENZYME_TEST_ENABLE_LIVE_LLM=true`
- `OPENZYME_TEST_ENABLE_LIVE_TAVILY=true`
- `OPENZYME_TEST_ENABLE_LIVE_HPC=true`
- `OPENZYME_TEST_ENABLE_LIVE_E2E=true`
- `OPENZYME_TEST_ENABLE_QUALITY_EVAL=true`
- `OPENZYME_TEST_LIVE_LLM_*` if you want a separate timeout/retry budget for real-provider LLM smoke tests

Useful commands:

1. `uv run pytest -m "integration and live_llm"`
2. `uv run pytest -m "integration and live_e2e"`
3. `uv run pytest -m quality_eval`

## V3 `/ui` fpocket Smoke Test

For a manual Host API plus HPC smoke test:

1. start the Host API with `OPENZYME_EXECUTION_BACKEND=hpc`
2. open `http://127.0.0.1:8000/ui/`
3. use session `sess_executor_demo`
4. send `对 art_eval_structure 运行 fpocket 并返回结果`
5. approve the fpocket execution request

Expected result: the chat shows the executor's fpocket result summary with output artifact references, and the workspace/Inspector shows the fpocket output artifacts. It should not show `Execution finished: Pipeline sandbox completed.` The seeded `art_eval_structure` points at the bundled `fixtures/fpocket/1ubq.pdb` fixture and carries `format=pdb` metadata for fpocket validation.
