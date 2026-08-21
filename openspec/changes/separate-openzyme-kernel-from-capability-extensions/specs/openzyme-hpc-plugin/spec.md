## ADDED Requirements

### Requirement: HPC target and executor workspace semantics are Plugin-owned
`openzyme-hpc` MUST own qualified targets, executor remote workspace provisioning/generation, owner-scoped credential requests, safe opaque workspace projection, source sync identity, retention and cleanup receipts. It MUST NOT define HMMER, Vina, AOX or other domain tool semantics, and Standard without HPC MUST remain usable.

#### Scenario: Provision an executor workspace
- **WHEN** an authorized executor requests a workspace on a bound qualified target
- **THEN** HPC records one owner/local-generation/remote-generation/target-bound workspace and returns only its safe owner view

#### Scenario: Another Agent requests the workspace binding
- **WHEN** a non-owner attempts to inspect or use the workspace
- **THEN** authorization fails without revealing login alias, remote root, credential or job state

### Requirement: HPC owns resource inventory and route contribution
HPC MUST publish immutable target inventory generations and capability-resolved workspace/compute routes through Extension SPI. It MUST bind every route to exact target/profile/provider/inventory/qualification identity and MUST NOT claim a software capability from an opaque digest or unqualified probe.

#### Scenario: Publish an HMMER-capable route
- **WHEN** a valid inventory contains the required HMMER version/operations and Compute provider contract
- **THEN** HPC contributes an exact route that the Kernel resolver may match to a domain requirement

#### Scenario: Software fact is absent
- **WHEN** target qualification proves workspace access but contains no required software fact
- **THEN** workspace operations may remain available while the domain compute route is blocked

### Requirement: HPC workspace tools are explicit and owner-bound
HPC MUST contribute `hpc.workspace.request`, `inspect`, `verify`, `sync_source`, `fs.read`, `fs.list`, `fs.mutate` and `exec`. All operations after request MUST require an opaque workspace ID and revalidate Session, owner, local/remote generation, target qualification and operation-specific AgentAuthorityLease.

#### Scenario: Execute in the exact remote workspace
- **WHEN** the owner invokes HPC exec with a current workspace ID and authority
- **THEN** the Plugin delegates to the declared WorkspaceProcessPort Adapter under one ControlledOperation

#### Scenario: Reuse stale workspace generation
- **WHEN** a call references a replaced local or remote generation
- **THEN** admission rejects it with no credential issuance or remote effect

### Requirement: SSH filesystem transfer and Slurm are separate Adapters
SSH process, SFTP filesystem and rsync/scp transfer mechanisms MUST live in declared HPC workspace Adapters. Scheduler submit/observe/cancel and Slurm-specific receipts MUST live in `openzyme-hpc-slurm` or a peer scheduler Adapter. Neither Adapter MAY add domain semantic tools or become active solely because its package is installed.

#### Scenario: Use a fake scheduler
- **WHEN** non-live qualification selects a deterministic scheduler Adapter
- **THEN** formal dispatch/observe/cancel/restart follows the same generic Compute/HPC contracts without SSH or Slurm imports

#### Scenario: Slurm response is invalid
- **WHEN** the Adapter cannot validate scheduler identity or response
- **THEN** it preserves effect certainty and does not fabricate a job ID, retry or report success

### Requirement: Login file credentials exclude scheduler authority
Every HPC login/file credential MUST be scoped to one owner workspace root, target, protocol, audience, generation and expiry and MAY authorize only declared SSH/SFTP/rsync/Git/LFS/file operations. Scheduler submit/observe/cancel MUST require a separate occurrence credential created by formal Compute admission.

#### Scenario: Login credential invokes sbatch
- **WHEN** a workspace exec attempts scheduler submission with its login credential
- **THEN** credential/admission policy rejects it and records no scheduler occurrence

### Requirement: HPC workspace lifecycle uses controlled effects and settlement
Provision, mutate/exec/transfer and cleanup effects MUST use Kernel ControlledOperation identities. Cleanup MUST verify unsettled job/effect state, revoke credentials, issue one cleanup intent and reconcile ambiguous responses before marking a workspace cleaned.

#### Scenario: Cleanup response is lost
- **WHEN** remote cleanup may have executed but no receipt returns
- **THEN** the same cleanup operation enters reconciliation and no replacement directory deletion is issued

### Requirement: HPC runner and public projection remain narrow
Runner and public contracts MUST use opaque handles and safe target/workspace/receipt facts. They MUST NOT expose Host paths, raw scheduler IDs/logs, runner config, credentials, other owners' locators or require expected outputs. `mcp-hpc-runner` MUST depend only on execution wire contracts.

#### Scenario: Build runner-only environment
- **WHEN** the runner is installed with its wire contract package
- **THEN** no Kernel, Host, Science, EnzymeDesign or broad platform Domain dependency is installed

### Requirement: HPC implementation and documentation align
HPC/SSH/Slurm/runner READMEs, target config, tool schemas, operator qualification, main architecture and `docs/v3/execution-pipeline-docs/` MUST describe the same Plugin/Adapter ownership, workspace tools, inventory, credential and scheduler separation implemented by source.

#### Scenario: Documentation still uses local workspace.exec for SSH
- **WHEN** current docs or prompts direct an executor to request HPC login through local `workspace.exec`
- **THEN** source-to-document qualification fails
