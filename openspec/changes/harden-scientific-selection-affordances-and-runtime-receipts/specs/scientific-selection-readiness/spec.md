## ADDED Requirements

### Requirement: Selection head resolution preserves one lifecycle truth
The scientific selection repository SHALL keep the selection head as a CAS identity/version pointer and SHALL resolve its lifecycle state from the referenced canonical `ScientificChainSelection`. A resolved head MUST verify attempt, selection, and revision identity in one repository read model; the system MUST NOT copy selection lifecycle state into the head as a second truth.

#### Scenario: Resolve a draft or sealed head
- **WHEN** an attempt head references an existing draft or sealed selection with matching attempt and revision
- **THEN** the resolved head exposes the pointer version and the referenced selection's canonical lifecycle state

#### Scenario: Resolve an attempt without a head
- **WHEN** an attempt has not started a selection revision
- **THEN** head resolution returns no head without inventing a draft selection or runtime warning

#### Scenario: Detect an invalid head reference
- **WHEN** a head points to a missing selection or mismatched attempt/revision
- **THEN** mutation paths fail closed with a stable integrity error and runtime consistency projects explicit attention instead of raising a language-level attribute error

### Requirement: One pure evaluator defines selection readiness
The control plane SHALL evaluate an exact selection from its resolved head, complete occurrence universe, dispositions, effect adoptions, materializations, workflow contract, executions, results, authority, and active ownership facts without performing a mutation. Selection inspection, seal validation, closure revalidation, and consistency projection MUST consume this same evaluation and stable issue taxonomy.

#### Scenario: Evaluate an incomplete adopted chain
- **WHEN** every occurrence has a disposition but one adopted occurrence lacks its matching effect adoption
- **THEN** evaluation reports `selection_adoption_incomplete`, identifies the bounded missing operation, and returns `seal_ready=false`

#### Scenario: Evaluate an unknown effect
- **WHEN** any occurrence is dispatch-in-doubt or otherwise has unresolved external effect
- **THEN** evaluation reports the unknown-effect blocker and both seal and closure reject the same selection

#### Scenario: Seal exactly the evaluated state
- **WHEN** evaluation has no issues and the expected universe/head identities still match at mutation time
- **THEN** seal may persist the immutable selection while any intervening state change causes CAS or universe validation failure

#### Scenario: Keep readiness separate from agent intent
- **WHEN** evaluation returns `seal_ready=true`
- **THEN** the Host does not automatically seal, close the attempt, finish the task, or recommend that the agent do so

### Requirement: Scientific selection inspection is bounded and state specific
`scientific.attempt.inspect` SHALL support exact attempt/selection filtering and stable bounded occurrence paging for detailed contract and readiness facts. `world.inspect` and composite workspace projections SHALL expose only bounded attempt/head, gap-count, and blocker summaries. Inspection MUST NOT require the agent to join a head record manually with a separate selection list.

#### Scenario: Inspect one selection page
- **WHEN** an agent requests a valid selection with a bounded limit and optional cursor
- **THEN** the result identifies the exact attempt, head, selection state, contract digest, page identity, occurrence facts, current disposition/adoption, compatible roles, issues, and readiness summary

#### Scenario: Continue occurrence paging
- **WHEN** a selection universe exceeds one inspection page
- **THEN** stable ordering and an opaque next cursor allow every occurrence to be observed exactly once without embedding the complete universe in an error or `world.inspect`

#### Scenario: Inspect through world summary
- **WHEN** an agent requests scientific facts through `world.inspect`
- **THEN** it receives bounded counts and blocker codes plus exact attempt/selection references, without detailed bulk occurrence payloads or recommended actions

#### Scenario: Reject a cross-session selection filter
- **WHEN** an actor requests an attempt or selection outside the current session/task authority
- **THEN** inspection rejects or hides the identity without disclosing another session's scientific state

### Requirement: Operation adoption is one explicit atomic agent command
The model-visible `scientific.operation.adopt` command SHALL require the agent to provide the exact current selection, occurrence, workflow role, reason code, and idempotency key. After validating the current head, universe, terminal-known result, approval/effect facts, and workflow contract, the Host SHALL atomically create one adopted disposition and one matching effect adoption under the same normalized request identity.

#### Scenario: Adopt a valid occurrence
- **WHEN** an agent explicitly adopts a same-attempt successful terminal-known occurrence into a compatible role
- **THEN** one transaction commits the exact adopted disposition and matching effect adoption and returns both canonical identities

#### Scenario: Reject an invalid role without partial state
- **WHEN** the requested role is undeclared or incompatible with the occurrence
- **THEN** the command returns exact allowed/compatible role facts with `mutation_applied=false` and neither canonical row exists

#### Scenario: Roll back a second-record failure
- **WHEN** disposition insertion succeeds inside the transaction but effect-adoption insertion fails
- **THEN** the transaction rolls back and inspection observes neither half of the requested adoption

#### Scenario: Replay an identical adoption
- **WHEN** the same actor repeats the same idempotency key and normalized request
- **THEN** the Host returns the same disposition and adoption identities without adding another row

#### Scenario: Detect a partial replay state
- **WHEN** replay lookup finds only one of the two expected canonical rows or a mismatched request digest
- **THEN** the Host raises a stable integrity conflict and does not synthesize or repair the missing half

### Requirement: New selections cannot use the legacy two-step adopted path
For contracts active under this capability, `scientific.operation.disposition` SHALL accept only `failed`, `superseded`, or `abandoned`, and the legacy `scientific.effect.adopt` command MUST NOT be model visible or mutate a new-contract selection. Frozen readers and explicit compatibility tests MAY retain old records without granting new authority.

#### Scenario: Try to write an adopted disposition directly
- **WHEN** an agent calls `scientific.operation.disposition` with `kind=adopted` for a new-contract selection
- **THEN** the Host rejects the call as no-effect and directs observation to the atomic command contract without choosing an occurrence or role

#### Scenario: Try to call the legacy adoption tool
- **WHEN** a model requests `scientific.effect.adopt` on the new tool surface
- **THEN** normal tool visibility/unknown-tool handling rejects it without dispatch or mutation

#### Scenario: Read historical split records
- **WHEN** a historical selection contains separately recorded adopted disposition and effect adoption
- **THEN** historical inspection and verification preserve those exact records without rewriting them as a new atomic command

### Requirement: Selection errors return precondition facts rather than fallback decisions
Scientific selection/adoption/seal rejections SHALL use stable error codes and bounded public-safe details that identify the exact head/selection version, requested operation/role, current disposition/adoption, allowed and compatible roles, missing ids or blocker codes, retry boundary, and whether mutation occurred. Errors MUST NOT auto-correct parameters, choose a replacement, create another selection/attempt, or emit `recommended_actions`.

#### Scenario: Request adoption before an exact precondition
- **WHEN** a command lacks a required current-head, universe, terminal-result, approval, or contract fact
- **THEN** the rejection identifies the failed precondition and confirms no mutation without performing a fallback

#### Scenario: Reject sealing with multiple gaps
- **WHEN** a selection has more than one missing disposition, adoption, or blocker
- **THEN** the bounded evaluation reports stable counts and an ordered bounded set of ids/codes instead of exposing bulk private state or only the first accidental exception

### Requirement: Known failures remain selectable history while unknown effects block
A known terminal/no-effect occurrence MAY receive a legal `failed`, `superseded`, or `abandoned` disposition within the same authorized formal attempt, and another same-attempt occurrence MAY be explicitly adopted for the role. Unknown effect, active process/writer/continuation, missing disposition authority, cross-attempt reuse, or authority/resource breach MUST block dispatch eligibility, selection seal, or closure as applicable.

#### Scenario: Repair a role after a known no-effect failure
- **WHEN** one operation fails with known no effect and a later same-attempt occurrence validly satisfies the same role
- **THEN** the agent can disposition the failure and atomically adopt the replacement without hiding either occurrence

#### Scenario: Try to dispose away an unknown effect
- **WHEN** an occurrence has dispatch-in-doubt effect certainty
- **THEN** no disposition or successful replacement can make the selection sealable until exact reconciliation closes the effect

#### Scenario: Try to reuse another attempt
- **WHEN** an otherwise matching operation or artifact belongs to another formal, probe, fault, campaign, or historical attempt
- **THEN** adoption and materialization fail closed regardless of equal bytes or role compatibility
