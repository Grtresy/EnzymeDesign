## MODIFIED Requirements

连续源码实现阶段只允许建立 control-plane-only candidate gateway。正式 gateway
替换与 public activation 必须等待 combined final source 的统一非 live 验收。

### Requirement: The typed gateway is the only engine-facing sandbox callback boundary
The control server MUST invoke a typed `SandboxHostGateway` with its current `SandboxHostCallContext` only for a closed set of canonical control-plane effects, including approval, workspace publication, controlled external-job records, continuation settlement, protocol/task mutations, and bounded runtime inspection. A control-plane adapter or durable execution callback MUST bind repository access to that supplied context. The gateway MUST NOT proxy ordinary file CRUD, artifact/catalog operations, source snapshots, native network transfer, Git/Git LFS transport, SSH, scp, rsync, HPC staging, or output fetch. The production path MUST NOT choose authority through reflected bound methods, `Callable[..., ...]`, competing repository-scope factories, or an optional `Any` repository parameter.

#### Scenario: Publish through the process context
- **WHEN** an attached sandbox requests `workspace.publish` for an exact clean revision
- **THEN** the gateway admits the canonical publication effect through the exact sandbox-process context and its explicit publication mutation authority

#### Scenario: Use native file and network tools
- **WHEN** an agent with the required capability lease reads a file or invokes Git, curl, SSH, scp, or rsync
- **THEN** the native process operates directly in the capsule without a `SandboxHostGateway` file or transfer callback

#### Scenario: Omit the Host context for a control-plane effect
- **WHEN** production code attempts to invoke a gateway control-plane operation without an explicit Host context
- **THEN** the call is rejected by the typed interface rather than falling back to engine creation-time repositories or a file/transfer proxy

#### Scenario: Durable worker invokes an external-job adapter
- **WHEN** a durable execution worker calls the engine adapter for a controlled external job
- **THEN** it supplies a durable-execution context whose execution identity matches the controlled-operation write fence

### Requirement: Mutation authority is explicit and independently fenced
Every canonical mutation made during a sandbox Host call MUST be covered by an explicitly registered mutation writer appropriate to the resource category. A sandbox-process writer MUST open only the bounded child writer required by a declared control-plane effect such as publication intent or protocol/task mutation. Native filesystem, Git, Git LFS, network, SSH, scp, and rsync operations MUST NOT acquire an artifact-publisher, file-proxy, staging, or output-fetch mutation writer. A valid mutation writer MUST NOT substitute for a session, execution, capability, or continuation fence, and those authorities MUST NOT substitute for mutation authority.

#### Scenario: Create a publication intent
- **WHEN** `workspace.publish` admits an exact clean revision from an attached sandbox
- **THEN** the canonical publication records are written under the bounded publication writer derived for that declared effect

#### Scenario: Perform a private native transfer
- **WHEN** an agent downloads or uploads bytes within its capability lease without publishing
- **THEN** no canonical artifact, file-proxy, stage, output-fetch, or publication mutation writer is opened

#### Scenario: Mutation scope freezes after process context creation
- **WHEN** the current mutation generation is fenced before a later sandbox control-plane callback commits
- **THEN** the canonical commit is rejected even if the sandbox process identity, capability lease, and any other owner authority remain valid
