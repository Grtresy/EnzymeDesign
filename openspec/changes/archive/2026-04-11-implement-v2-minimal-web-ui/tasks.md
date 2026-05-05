## 1. Frontend Scaffold

- [x] 1.1 Create the initial frontend project structure and toolchain for `apps/openzyme-web-ui`
- [x] 1.2 Add a thin Host API client layer for query, command, and workflow stream access
- [x] 1.3 Add basic test and build wiring for the new frontend project

## 2. Episode Workspace

- [x] 2.1 Implement the minimum episode workspace shell for workflow, pending actions, runs, and artifacts
- [x] 2.2 Implement create episode, resume, and approval/rejection interactions against the Host command surface
- [x] 2.3 Wire the workspace to Host workflow events so progress updates without a full reload

## 3. Validation

- [x] 3.1 Add frontend tests for the minimum episode workspace rendering and action flows
- [x] 3.2 Validate that the UI consumes Host projections without inventing a second state model
- [x] 3.3 Verify the browser closed loop from episode creation through execution output visibility
