# openzyme-web-ui

V2 Web UI contract notes and read-model schema for OpenZyme.

## Scope

This directory does not yet contain the React implementation.
Phase A only establishes the minimum UI-facing contracts needed for:

- workflow pane
- pending interrupt and approval summaries
- run and artifact panels
- report visibility

See [contracts/read_models.json](./contracts/read_models.json) for the minimum projection fields.
These fields are projection contracts over Host/API data, not raw LangGraph runtime state.
