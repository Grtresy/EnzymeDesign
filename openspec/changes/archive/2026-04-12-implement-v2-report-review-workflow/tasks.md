## 1. Canonical Report Persistence

- [x] 1.1 Add report-domain and runtime persistence support for canonical report records and artifact linkage
- [x] 1.2 Add repository and migration coverage for querying reports by episode and report identifier

## 2. Report Review Graph Integration

- [x] 2.1 Implement the `report_review` subgraph and the execution-to-report handoff contract
- [x] 2.2 Extend the top-level supervisor to route `execution -> report_review -> completed` on one episode thread
- [x] 2.3 Add graph tests that validate final completion only occurs after report review finishes

## 3. Host Report Projections

- [x] 3.1 Replace Host report placeholders with canonical report projections and report query behavior
- [x] 3.2 Emit report-availability workflow events from report projection changes
- [x] 3.3 Add Host integration tests that validate report availability after routed workflow completion
