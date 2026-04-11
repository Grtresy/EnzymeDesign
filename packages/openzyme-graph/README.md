# openzyme-graph

V2 LangGraph supervisor and subgraph contracts for OpenZyme.

## Scope

This package defines the Phase A graph-side contract for:

- LangGraph runtime state schema
- fixed phase enum
- durable resume anchors
- subgraph entry/exit contracts
- Host-facing interrupt and approval envelopes
- structured progress projection

## Fixed phases

- `intake`
- `research`
- `design`
- `execution`
- `report_review`

## Cross-package rules

- `thread_id = episode_id`
- graph state stays execution-local and does not own canonical business records
- node-level HITL should map to LangGraph `interrupt()` and `Command(resume=...)`
- Host/API/UI may project graph state and interrupts, but they do not replace LangGraph runtime primitives
