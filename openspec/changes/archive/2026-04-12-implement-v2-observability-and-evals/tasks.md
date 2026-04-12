## 1. Tracing Foundation

- [x] 1.1 Add LangSmith dependency and configuration hooks for selective or environment-driven tracing
- [x] 1.2 Define the standard trace metadata and tags for project, episode, phase, and approval or report context

## 2. Runtime And Host Integration

- [x] 2.1 Wire Host request handling and workflow invocation paths to emit correlated traces
- [x] 2.2 Add trace continuity for resume or approval actions through the routed workflow path
- [x] 2.3 Add focused tests or smoke checks that validate tracing hooks do not break normal workflow execution

## 3. Local Evaluation Harness

- [x] 3.1 Add a local eval runner and a small seeded scenario set for routed workflow coverage
- [x] 3.2 Add report-aware evaluation checks once report-review outputs are available
- [x] 3.3 Document and test how developers run local evals with and without LangSmith upload
