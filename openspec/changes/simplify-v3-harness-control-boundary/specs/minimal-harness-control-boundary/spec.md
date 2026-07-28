## ADDED Requirements

### Requirement: Ordinary known-effect rejection remains inside the agent turn
The Harness MUST return an ordinary tool or domain rejection with
`effect_certainty=no_effect|terminal_known` to the agent as structured result evidence and MUST
NOT create a second turn-local recovery obligation, reject the agent's later narration, or convert
the source occurrence to boundary-fatal solely because the agent did not perform a recognized
follow-up action.

#### Scenario: Agent ends after a no-effect validation rejection
- **WHEN** an internal agent receives a no-effect validation rejection and then returns prose without another mutation
- **THEN** the turn may complete, the task remains unchanged, and the runtime does not emit `agent_turn_recovery_unresolved`

#### Scenario: Agent inspects state after a rejection
- **WHEN** an internal agent receives an ordinary rejection and then successfully executes any authorized read
- **THEN** the read result is returned normally without requiring a causal settlement relation to the earlier rejection

#### Scenario: Agent corrects the original call
- **WHEN** the agent successfully retries the same tool with corrected arguments
- **THEN** the successful result stands on its own and no recovery-settlement event or matcher is required

#### Scenario: Model step budget ends after ordinary failures
- **WHEN** a bounded turn reaches its existing step limit after only known-effect ordinary failures
- **THEN** the Harness returns its ordinary max-step outcome and does not replace it with boundary-fatal recovery failure

### Requirement: Turn occurrence and business task state remain orthogonal
The system MUST interpret a completed or bounded agent turn only as settlement of that runtime
occurrence. It MUST NOT infer task completion, failure, cancellation, blocking, scientific success,
or report readiness from narration, turn completion, runtime idle, or step exhaustion.

#### Scenario: Turn completes while task remains open
- **WHEN** an agent turn returns normally without calling a task terminal tool
- **THEN** the source occurrence may be terminal while the task preserves its canonical nonterminal state

#### Scenario: Agent explicitly exits a task
- **WHEN** an authorized agent calls `task.finish` with a valid terminal command
- **THEN** task business state changes through that command independently of the Harness turn status

### Requirement: Strategy bookkeeping does not create a second control plane
The active product path MUST NOT require a failure hypothesis table, failure recovery disposition,
condition subscription, synthetic recovery signal, or exact recovery matcher to represent an
agent's choice to inspect, wait, retry, ask for help, or stop.

#### Scenario: Blocked dependency is already represented
- **WHEN** `task.delegate` observes open canonical `blocked_by` dependencies
- **THEN** it returns a structured no-effect readiness result and does not require a second failure condition subscription

#### Scenario: Dependency later completes
- **WHEN** a real task, protocol, approval, engine, or user event occurs after an earlier blocked delegation
- **THEN** normal source-bound runtime signaling may wake an agent without consulting a failure recovery disposition

### Requirement: Boundary-fatal failures remain fail closed
The system MUST still terminate or suspend the current owner according to the existing typed
contracts for unknown external effect, dispatch-in-doubt, invalid authority, permission denial at
an ownership boundary, stale fencing, integrity/provenance violation, unsafe continuation identity,
and mutation closure failure. Removing strategy recovery machinery MUST NOT convert any such
boundary failure into an ordinary successful turn.

#### Scenario: External dispatch outcome is unknown
- **WHEN** a controlled operation cannot prove whether an external effect occurred
- **THEN** the current ownership fails closed and no automatic retry or replacement work is admitted

#### Scenario: Late fenced writer returns
- **WHEN** a stale runtime, continuation, or mutation writer attempts a canonical write
- **THEN** the write remains rejected and the source boundary records the existing typed fatal diagnostic

### Requirement: Workflow policy cannot veto ordinary narration
Composition-specific workflow policy MUST NOT intercept, discard, or retry an otherwise valid
assistant response in order to force a particular delegation, report handoff, inspection, or close
sequence. Mutation-owning domain commands and final acceptance evaluation MAY reject incomplete or
unauthorized state without treating narration as mutation.

#### Scenario: AOX response arrives before closure is complete
- **WHEN** the model returns assistant text while canonical AOX closure prerequisites remain incomplete
- **THEN** the text is handled by the normal conversation boundary while the attempt remains nonterminal and ineligible for acceptance

#### Scenario: Unauthorized close is attempted
- **WHEN** an actor calls the close command without required authority or canonical domain prerequisites
- **THEN** the close mutation is rejected without effect and the ordinary response path is not globally vetoed
