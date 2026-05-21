# openzyme-research

Research adapter seam for the OpenZyme V3 capability engine.

## Scope

- normalized research-unit inputs and outputs for capability engines
- a provider-agnostic `ResearchAdapter` protocol consumed by engine code
- a first `TavilyResearchAdapter` that normalizes Tavily search results into canonical research findings

## Notes

- Tavily remains adapter-local. Graph/runtime code only sees `ResearchUnitResult`.
- The `tavily` extra is optional so tests can run without network access or a configured API key.
