## 1. Persistence Setup

- [x] 1.1 Add the minimum Phase B relational schema and migration assets for projects, episodes, approvals, runs, and artifact records
- [x] 1.2 Implement repository modules or equivalent persistence services for the minimum Phase B business records
- [x] 1.3 Add repository-level tests that validate ownership links and canonical record access

## 2. Checkpointer And Runtime Assembly

- [x] 2.1 Add Postgres-backed LangGraph checkpointer bootstrap and configuration wiring
- [x] 2.2 Implement the shared runtime bootstrap or facade that binds repositories, checkpointer, and graph assembly inputs
- [x] 2.3 Add tests that validate episode-scoped thread configuration and durable checkpointer usage

## 3. Internal Seams

- [x] 3.1 Define internal execution-adapter and projection-loading interfaces consumed by later Phase B changes
- [x] 3.2 Document cross-change dependency expectations in the runtime foundation package or README
- [x] 3.3 Validate that the runtime foundation can support the graph-loop and Host API changes without redefining storage ownership
