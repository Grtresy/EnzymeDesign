# openzyme-web-ui

Minimal Phase B Web UI for OpenZyme.

## Scope

This directory now contains the first browser-facing workspace shell for Phase B:

- create episode
- workflow pane for top-level `intake` / `design` / `report_review`
- pending interrupt and approval summaries
- evidence, run, and artifact panels that belong to the design workspace
- Host projection stream consumption

## Development

- `npm test`
- `npm run build`

See [contracts/read_models.json](./contracts/read_models.json) for the minimum projection fields.
The browser consumes Host workspace projections and Host workflow events directly; it does not rebuild raw LangGraph state in the client.
Research and execution are treated as design-owned capabilities reflected in workspace panes and events, not as independent top-level phases in the browser shell.
