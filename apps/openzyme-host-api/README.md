# openzyme-host-api

V2 Host API contracts for OpenZyme.

## Scope

This app defines the Phase A Host-side contract for:

- query resources
- workflow commands
- workflow-aware projected stream events
- read-model payload shapes consumed by the Web UI

## Contract rules

- Resource and command identifiers reuse the domain and graph contracts.
- Workflow events are Host projections derived from LangGraph stream/update data, not replacements for LangGraph runtime stream modes.
- Read models remain projections over canonical business records and graph progress.
