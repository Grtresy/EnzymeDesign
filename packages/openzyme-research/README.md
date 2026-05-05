# openzyme-research

Phase C research adapter seam for OpenZyme.

## Scope

- normalized research-unit inputs and outputs for LangGraph worker nodes
- a provider-agnostic `ResearchAdapter` protocol consumed by graph code
- a first `TavilyResearchAdapter` that normalizes Tavily search results into canonical research findings

## Notes

- Tavily remains adapter-local. Graph/runtime code only sees `ResearchUnitResult`.
- The `tavily` extra is optional so tests can run without network access or a configured API key.
