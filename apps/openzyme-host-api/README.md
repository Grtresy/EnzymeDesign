# openzyme-host-api

V2 Host API app and contracts for OpenZyme.

## Scope

This app defines the Phase B Host-side API surface for:

- query resources
- workflow commands
- workflow-aware projected stream events
- read-model payload shapes consumed by the Web UI

## Contract rules

- Resource and command identifiers reuse the domain and graph contracts.
- Workflow events are Host projections derived from LangGraph stream/update data, not replacements for LangGraph runtime stream modes.
- Read models remain projections over canonical business records and graph progress.
- The stream endpoint emits projected workflow events for the UI and does not expose raw LangGraph transport chunks.

## Local Demo

1. `cd apps/openzyme-web-ui && npm run build`
2. `cd /home/grtresy/VSCodeRepo/EnzymeDesign && uv run python -m openzyme_host_api.demo`
3. Open `http://127.0.0.1:8000/ui/`

The demo preloads `proj_001` and uses sqlite, an in-memory checkpointer, and a fake execution adapter so you can exercise the Phase B closed loop without HPC setup.

### Real LLM Configuration

The demo can optionally use an OpenAI-compatible chat model for the LangChain structured-output path.

Use the repository-level environment file conventions described in [README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/README.md:39):

1. copy [`.env.example`](/home/grtresy/VSCodeRepo/EnzymeDesign/.env.example) to `.env`
2. set `OPENZYME_LLM_API_KEY=<your-api-key>`
3. keep or override the default Zhipu Coding settings as needed:
   - `OPENZYME_LLM_MODEL=glm-5.1`
   - `OPENZYME_LLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4`
   - `OPENZYME_LLM_TIMEOUT=60`
   - `OPENZYME_LLM_MAX_RETRIES=1`
   - `OPENZYME_LLM_TEMPERATURE=0`
4. run `uv run python -m openzyme_host_api.demo`

If no API key is set, the Host API demo keeps using the local deterministic fallback path.

## Local Evals

Run the routed workflow smoke evals locally:

1. `cd /home/grtresy/VSCodeRepo/EnzymeDesign`
2. `uv run python -m openzyme_host_api.evals`

By default the eval harness stays local and does not upload LangSmith results. To emit LangSmith traces for each seeded scenario:

1. set `OPENZYME_LANGSMITH_TRACING=true`
2. optionally set `OPENZYME_LANGSMITH_PROJECT=<project-name>`
3. run `uv run python -m openzyme_host_api.evals --upload-results`
