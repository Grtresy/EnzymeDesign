## 1. Supervisor Graph Assembly

- [x] 1.1 Add the top-level supervisor graph that routes `intake`, `research`, `design`, and `execution` on one `episode_id` thread
- [x] 1.2 Define and implement explicit supervisor-to-subgraph handoff mapping for intake, research, design, and execution
- [x] 1.3 Add supervisor graph tests that validate routed multi-phase execution and same-thread resume behavior

## 2. Host And Demo Integration

- [x] 2.1 Point Host API dependencies and service entrypoints at the unified supervisor graph builder
- [x] 2.2 Update local demo and workspace projection loading so product-facing paths use the supervisor graph by default
- [x] 2.3 Add Host integration tests that validate create/resume/approval flows across routed phases through the unified supervisor graph
