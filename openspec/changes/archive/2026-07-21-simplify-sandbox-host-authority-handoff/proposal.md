## Why

An attached sandbox can outlive the agent turn that created it, but its Host callbacks can still retain that expired turn's session lease or an untyped repository escape hatch.  The r41-r44 campaign exposed this boundary one operation at a time; before another live campaign, the authority handoff and the campaign's observation path need one explicit, composition-root-tested contract.

Architecture proposal: [`architecture-proposals/sandbox-host-authority-handoff.md`](architecture-proposals/sandbox-host-authority-handoff.md). It is archived with this change under `architecture-proposals/`.

## What Changes

- Introduce a typed sandbox-to-Host call context and gateway so session-turn, durable execution, continuation-delivery, and mutation-writer authority are explicit and cannot be substituted for one another.
- Require an attached sandbox that resumes after continuation delivery to keep using the current sandbox-process Host authority for later non-effect SDK calls, including `hpc.fetch_outputs`, without reviving the originating agent lease.
- Add a bounded, read-only runtime barrier projection for campaign/operator observation; it derives existing canonical state and creates no workflow truth or mutation authority.
- Split the AOX campaign driver around that projection, then remove direct database coordination helpers after equivalent behavior is covered by focused and file-backed lifecycle tests.
- Preserve historical r41-r44 evidence and legacy reads while stopping new code from depending on the weak callback/repository injection path.

## Capabilities

### New Capabilities

- `sandbox-host-authority`: Defines the typed sandbox Host gateway, authority separation, process-lifetime handoff, and bounded read-only runtime barrier.

### Modified Capabilities

- `runtime-continuation`: Requires a delivered attached continuation to remain usable for subsequent SDK calls under sandbox-process authority after the originating agent lease is released.
- `controlled-operation-execution`: Requires Host calls made by a durable execution or attached sandbox to resolve repositories and mutation writers from their explicit call context rather than an optional untyped override.

## Impact

- Affects the Host API composition root, teammate/sandbox supervision, execution-engine callback surface, runtime repositories/projections, and the AOX live campaign driver.
- Adds composition-root and fault-matrix regression coverage spanning lease release, durable execution, continuation delivery, and post-resume output fetch.
- Updates V3 architecture and execution-pipeline documentation.  No public workflow state or external effect is added, and live campaign admission remains paused until the new gates pass.
