# openzyme-reporting-extension Specification

## Purpose
定义 Reporting Plugin 对报告状态、revision-bound 内容、renderer、validator、projection 与失败语义的独立所有权。
## Requirements
### Requirement: Reporting owns report-specific state and policy
`openzyme-reporting` MUST own report draft, report record/version, section/format schema, render/validation receipt, report-specific projection and report finish validator. Kernel MUST retain only generic revision/path/evidence references and MUST NOT expose report-specific repositories or top-level Core fields.

#### Scenario: Create a report draft
- **WHEN** an authorized Agent invokes a Reporting tool under an enabled Reporting manifest
- **THEN** the draft is written in the Reporting namespace and linked only to authorized Core identities through public references

#### Scenario: Reporting is not installed
- **WHEN** Standard activates without Reporting
- **THEN** Core Session/Task/workspace/publication functions remain available and no report repository or schema is initialized

### Requirement: Report content is file-native and revision-bound
Canonical report content MUST reside in an Agent workspace and be shared through an immutable PublishedRevision and RevisionPathRef. Reporting state MAY store bounded metadata, lifecycle and validation facts but MUST NOT duplicate the report body, invent a storage URI or treat a dirty private file as published content.

#### Scenario: Publish a Markdown report
- **WHEN** an Agent explicitly publishes a clean revision containing the report and registers its RevisionPathRef with Reporting
- **THEN** the report record binds the exact publication/path/content identity and remains stable after later private edits

#### Scenario: Register a dirty private path
- **WHEN** a caller provides only a current private workspace path or uncommitted content
- **THEN** Reporting rejects publication registration and does not auto-commit, copy or publish the file

### Requirement: Renderers and format validators are extension components
Markdown, HTML, PDF or other report renderers and section validators MUST be declared by Reporting or a Reporting sub-extension with exact tool/worker/schema identities. Rendering MUST use controlled process/effect ports when needed and MUST NOT become a Kernel dependency.

#### Scenario: Render with a declared worker
- **WHEN** the active Reporting manifest declares a renderer and a valid report source revision
- **THEN** the worker produces a bounded result linked to exact source/output revision identities and its worker/catalog digest

#### Scenario: Renderer is missing or drifts
- **WHEN** a Session expects a renderer absent from or mismatched with the active bundle
- **THEN** render admission fails before process execution and no alternative format is selected

### Requirement: Report lifecycle is separate from workspace publication and Task terminal
Draft completion, file publication, render success, report validation and report business publication MUST remain distinct Reporting/Kernel facts. None MAY automatically complete a Task; only the authorized Task owner's explicit `task.finish` can request terminal transition.

#### Scenario: Valid report is published
- **WHEN** Reporting records a valid published report and no Task finish command occurs
- **THEN** the report becomes available in its extension projection while the Task state is unchanged

#### Scenario: Task finish requires a report
- **WHEN** the Task owner calls `task.finish` and the bound Reporting validator verifies the exact report version/revision/path
- **THEN** the validator returns acceptance and Kernel independently applies the Task terminal mutation

### Requirement: Reporting validator is bounded and read-only for Core
The Reporting finish validator MUST consume an immutable finish context and Reporting namespace state, return a closed receipt or rejection, and perform no Core mutation, rendering, publication or external I/O while the Core Unit of Work is open.

#### Scenario: Required report version is absent
- **WHEN** finish context requires a specific report contract/version that Reporting cannot resolve
- **THEN** the validator returns a typed missing-report rejection and the entire finish mutation remains unapplied

#### Scenario: Validator attempts an external render
- **WHEN** validation would require generating or fetching content during Task finish
- **THEN** it rejects the precondition and instructs the Agent to perform the explicit Reporting action first

### Requirement: Reporting projection is namespaced and bounded
`file_workspace_public@2` MUST expose Reporting data only under the exact Reporting extension contract ID. The section MUST contain bounded metadata and authorized RevisionPathRefs and MUST support stable pagination; Core projection and Core UI MUST NOT infer report fields from extension events.

#### Scenario: Read Reporting projection
- **WHEN** an authorized caller reads a Session pinned to Reporting
- **THEN** report drafts/records/validation facts appear only in the Reporting section with no file body, Host path or renderer-private log

#### Scenario: Reporting is removed from a compatible historical view
- **WHEN** a new Session bundle omits Reporting
- **THEN** the section is absent and Core projection shape remains otherwise unchanged

### Requirement: Reporting failures preserve exact phase and no fallback
Draft, publication-link, render, validation and projection failures MUST use the common structured failure envelope and MUST NOT auto-publish a private file, choose another renderer, weaken a schema, reopen an approval or finish a Task.

#### Scenario: PDF rendering fails
- **WHEN** a declared PDF renderer exits unsuccessfully
- **THEN** Reporting records the exact render failure and source identity, exposes a safe diagnostic and creates no successful report version or Task transition

### Requirement: Reporting source and documentation move out of Core together
Report repositories, tools, Host routes, UI renderers, tests and documentation MUST identify `openzyme-reporting` as their owner. Core/Standard documentation MUST describe only the extension seam and MUST NOT retain obsolete top-level report schema or commands.

#### Scenario: Old report repository remains exported by Kernel
- **WHEN** source or public import inspection finds a report-specific repository exported from `openzyme-kernel`
- **THEN** the Reporting extraction remains incomplete

#### Scenario: README and routes match the manifest
- **WHEN** Reporting migration is accepted
- **THEN** its README, route/tool reference, manifest catalogs and executable registration expose the same exact surfaces and versions
