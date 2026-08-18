# Architecture invariant registry schema v2

## Identity and byte contract

The only current registry path is
`docs/v3/architecture-qualification/invariant-registry.json`. Its top-level
`schema_id` is `openzyme_v3_architecture_invariant_registry@2`, its `registry_id`
is `openzyme_v3_architecture_invariants`, and its only profile is
`local_single_process_file_sqlite@1`.

The file is strict UTF-8 JSON with:

- no BOM, duplicate object key, `NaN`, `Infinity`, unknown field, or symbolic link;
- object keys sorted lexicographically, compact `,` and `:` separators, and
  `ensure_ascii=true`;
- arrays whose contract is a set stored in sorted unique order;
- exactly one terminal LF and no other insignificant whitespace;
- a digest computed over the complete stored bytes, including the LF.

Any byte, source, selection, or closure drift invalidates the registry before a
scenario may be counted as satisfied.

Closed P0 history uses the separate canonical sidecar
`docs/v3/architecture-qualification/p0-closures.json` with schema
`openzyme_v3_architecture_p0_closures@1`. Its own source bytes are listed in
`implementation_files`, so registry/test/implementation identity and the pure
verifier bind it without adding mutable historical state to the invariant registry.
Every record is closed, sorted by `p0_id`, and binds the baseline report payload
digest, original red scenario, invariant/P0/trigger ids, focused change ref and a
full closure commit that must be an ancestor of current HEAD. A regressed invariant
is emitted as open again; a historical closure ref can never waive current red or
unproven evidence.

## Closed top-level object

The exact top-level fields are:

| Field | Contract |
| --- | --- |
| `schema_id` | Exact schema identity above. |
| `registry_id` | Exact registry identity above. |
| `profile` | Exact-six-field local profile object. |
| `required_families` | Exact twelve-family schema-v2 set. |
| `required_scenario_ids` | Exact set of scenario records in this document. |
| `implementation_files` | Readable, non-symlink, repository-relative files bound into implementation identity. |
| `owner_constraint_registry` | Exact path/schema/id/content-digest binding for the closed owner/constraint registry. |
| `external_ports` | Non-empty sorted closed port declarations. |
| `p0_triggers` | Exact schema-v1 automatic P0 trigger declarations. |
| `boundary_relations` | Non-empty symbolic owner and seam relations; never numeric duplicate truth. |
| `invariants` | Sorted closed invariant records. |
| `scenarios` | Sorted closed scenario records. |

The profile fields are exactly `profile_id`, `trust_boundary`, `database_mode`,
`process_model`, `claims`, and `excludes`. Their v1 authority values are
`trusted_host`, `file_sqlite`, and `single_process`; claims and exclusions must be
explicit non-empty sorted sets.

## External ports and P0 triggers

An external-port record has exactly `port_id`, `production_seams`,
`qualification_mode`, and `effect_ledger_required`. Mode is one of
`controlled_adapter`, `forbidden`, or `local_fault_process`. A controlled adapter
always requires a canonical effect ledger and remains
`qualification_fixture_non_cutover`.

The exact automatic P0 trigger ids are:

- `admission-bypass`;
- `authority-drift`;
- `duplicate-effect-or-approval`;
- `false-success`;
- `unbounded-progress`;
- `unverifiable-evidence`.

Each trigger record has exactly `trigger_id` and `description`. Human review may
raise severity but cannot make an automatically triggered P0 admissible.

## Boundary relations

A boundary record has exactly `boundary_id`, `owner`, and `seams`. `owner` contains
exactly `module`, `symbol`, and `source_file`. Each seam adds exactly one `relation`,
which is `equal` or `less_than_or_equal`. Source files must be readable regular files
inside the repository. Runtime qualification resolves the owner symbol and derives
`limit-1`, `limit`, and `limit+1`; the registry never stores the integer value.

## Invariants and scenarios

An invariant record contains exactly:

- `invariant_id`, `family`, `title`, and `owner_boundary`;
- `contract_refs` and the exact local `profile_ids`;
- one `failure_class` from `boundary`, `integrity`, `liveness`, or `safety`;
- non-empty `p0_trigger_ids` and `scenario_ids`.

The exact v2 families are `authority-composition`, `boundary-scale`,
`bounded-terminal-convergence`, `evidence-projection`, `identity-semantics`,
`operator-retirement`, `reconciliation`, `restart-fencing`,
`strategy-neutrality`, `supervisor-progress`, `wire-contract`, and `world-fidelity`.

The owner registry binding has exactly `path`, `schema_id`, `registry_id`, and
`content_digest`. It MUST resolve to the canonical
`openzyme_v3_harness_owner_constraint_registry@1` bytes. Product code does not load
this registry; it is repository qualification evidence that closes ownership,
consumers, compatibility, error/effect semantics, and forbidden policy/fallback edges.

`strategy-neutrality` scenarios compare bounded legal trace transformations rather
than exact transcripts. `world-fidelity` scenarios bind the earliest typed cause,
wrappers, source/effect identity, public visibility, and forbidden effects. A scripted
reachability scenario cannot substitute for either family.

A scenario record contains exactly:

- `scenario_id`, `family`, `test_selector`, and `source_files`;
- `external_port_ids`, `fault_points`, `boundary_ids`, and `provenance_refs`;
- `selections`, which must include `full` and may also include
  `premerge_subset`;
- `budgets`, with exact non-negative integer `max_steps`, `max_ticks`,
  `max_state_version_delta`, `max_event_delta`, `max_effect_count`, and positive
  `deadline_seconds` fields.

The selector must name one declared source file. Every invariant has at least one
scenario; every scenario is referenced by at least one same-family invariant; every
referenced port, boundary, trigger, profile, contract, source, and implementation
file exists in the same closed registry. Pytest collection closure adds the further
requirement that every stable scenario id is collected and executed exactly once.

The current cutover closure additionally requires these source-bound scenario ids;
renaming or omitting one invalidates the registry before execution:

- `reconciliation.workspace-job-response-loss`;
- `world-fidelity.diagnostic-publication-cleanup`;
- `evidence-projection.fresh-offline-deployment-proof`;
- `identity-semantics.scientific-file-finalization`;
- `operator-retirement.web-ui-file-workspace`.

An empty external-port or boundary-relation set is not a valid declaration of
absence. The profile must state the process seam and the scale relationships it
actually exercises so that a missing declaration cannot silently widen a claim.
