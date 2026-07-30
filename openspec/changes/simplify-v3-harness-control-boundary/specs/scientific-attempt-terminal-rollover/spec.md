## ADDED Requirements

### Requirement: Terminal rollover does not require assistant-response veto
Scientific attempt rollover MUST be driven by canonical closure intent, immutable lifecycle,
mutation-scope settlement, and process retirement. Composition MUST NOT require an
assistant-response precondition that discards ordinary narration. The close command MUST NOT
require, persist, or atomically bind companion assistant text. Domain-specific close eligibility
MAY require an explicit typed validation receipt, but that receipt MUST be independent of ordinary
conversation messages and MUST NOT become a global veto over narration.

#### Scenario: Response precedes close request
- **WHEN** a model produces ordinary response text before an authorized close command is accepted
- **THEN** the message may persist, the attempt remains nonterminal until canonical close facts exist, and the Harness does not fail the turn for response ordering; a later close carries only its canonical closure inputs and any required typed receipt

#### Scenario: Close request precedes final projection
- **WHEN** an authorized close command persists canonical intent while later finalization work remains
- **THEN** the existing rollover and quiescence boundaries complete independently of a global narration veto

#### Scenario: Final acceptance lacks required product facts
- **WHEN** the task/report/selection/closure evidence is incomplete at collection time
- **THEN** the attempt remains ineligible without rewriting the preceding agent turn as a Harness boundary failure
