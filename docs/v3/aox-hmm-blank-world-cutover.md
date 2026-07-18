# AOX/HMM blank-world cutover evidence contract

Status: implementation and offline gates in progress; local Live cutover remains **NO-GO** until two real positive attempts and one real controlled fault attempt are sealed and verified on one commit/config identity.

This document describes the operator/evidence boundary implemented by `openzyme_host_api.aox_cutover_evidence`. It does not turn the historical S15 fixture into live evidence and does not authorize seeded state, cached scientific outputs, the reference notebook, or copied reference results as attempt inputs.

## Fixed scope

- Runtime remains single-process SQLite and the runner remains trusted-Host-only.
- Scientific failures are fail closed; an honest no-hit/no-candidate outcome may publish a healthy empty report but cannot claim discovery.
- The formal workflow uses `aox_motif_rule_score@1`, canonical real-sequence similarity, `cdhit_cluster_membership@1`, and digest-pinned workflow/image/SDK identities.
- The target fixed MICU policy is exactly 500,000,000 cumulative input+output tokens; prior usage remains charged and campaign setup never resets it. An existing legacy ledger continues to enforce its stored 100M limit until the operator explicitly runs `uv run python -m openzyme_runtime.live_token_ledger_cli --migrate-legacy-fixed-policy`. Summary, reservation, and campaign startup never reinterpret it. That transaction raises only the exact legacy fixed policy, preserves all attempt rows, is idempotent at 500M, and rejects caller-selected lower limits. The cumulative ledger is read before and after every attempt.
- A bounded known-positive provider/HPC probe is separate from formal artifacts. Probe artifacts cannot enter formal operations or the published report.

## Current pre-live harness closure

The latest non-eligible live attempt remains **NO-GO**. It exposed five narrow
cutover-driver/harness gaps that are now explicit gates for the next campaign:

- `world.inspect(sections=["capabilities"], task_id=..., limit=...)` binds a
  teammate to its current task (a mismatch is a typed error), while preserving
  the existing explicit master session view. The facts page is newest-first,
  capped at 20 invocations, eight refs per related kind and 64 KiB of serialized
  facts. It exposes invocation identity/status/timestamps and closed opaque refs,
  never full document bodies, output payloads, evidence bodies, or source text.
  Narrow-column repository reads, lazy section hydration and cursor pagination
  remain the separate proposal
  [bounded capability facts query](architecture-proposals/bounded-capability-facts-query.md);
- every formal collector reconstructs the durable delegation request. The
  executor must carry exactly the campaign workflow ref and complete manifest
  snapshot, while researcher and reporter carry no workflow binding. The
  bundle carries a closed public request projection with task/role/agent,
  instructions digest and workflow fields but no raw instructions. The offline
  verifier recomputes request-projection and manifest content/core digests and
  binds the projected agent to the task assignment;
- the formal executor is told the exact installed AOX SDK callables, provider
  transcript suffixes, runner-owned output paths and `fetch_refs` binding rule.
  Approximate reimplementations, positional artifact guesses and sentinel
  outputs are forbidden;
- a legitimate zero-record FASTA requires exact zero bytes and the typed
  `fasta_zero_records@1` validation profile with a stable empty reason and
  versioned derivation contract. Its catalog validation receipt is sealed and
  recomputed offline. Generic empty FASTA or sentinel text fails;
- a pipeline source snapshot is sealed as canonical
  `openzyme_sealed_source_tree@1`, with safe sorted relative paths, per-file
  bytes/digests and a recomputed tree digest. It must retain `kind=code`, and
  every UTF-8 source file is public-safety checked after base64 decoding. A
  source directory is never read as if it were a regular artifact file.

These are small correctness fixes. The larger need for one registry that
projects scientific callables, canonical serializers, agent-facing facts and
receipts is proposal-only in
[versioned scientific calculation capability projection](architecture-proposals/versioned-scientific-calculation-capability-projection.md)
and is not implemented in this goal.

The first real post-closure campaign on commit `fbce624` remained strict
**NO-GO**. Attempt `positive-b6fa75b20b554cd286a2fd2111257f42` sealed a
structurally valid non-eligible bundle but stopped after the executor discarded
the valid value returned by `ws.stage_artifact(...)` and hand-built a malformed
MAFFT input descriptor. The run also exposed a cleanup-stage top-level blocker;
code-path reconstruction plus a deterministic regression showed that cleanup
could mask an earlier coordination blocker. The next pin therefore adds these
small harness corrections without changing scientific acceptance:

- supervised `bio_tools.*` rejects a malformed input locally with
  `hpc_stage_ref_required` and directs the agent to pass the exact
  `ws.stage_artifact(...)` return value; the Host remains authoritative for
  workspace ownership, artifact authorization and complete S11/S12 binding;
- the live prompt fixes one canonical research/execution/report task-id family.
  Every master wake reconciles that set: it may create a missing canonical
  member and advance an existing member, but cannot invent another/suffixed
  task id. This is a campaign-local idempotency guard, not a replacement for
  the proposal-only
  [request-lineage workflow authority](architecture-proposals/request-lineage-workflow-authority.md)
  design;
- drain failure arbitration preserves `drain command > earlier coordination >
  cleanup-only`; cleanup is still attempted fail closed and only its safe
  failure type may be attached as secondary diagnostic metadata.

None of these corrections turns the failed attempt into cutover evidence. A
fresh commit/config pin and fresh blank roots are required for the two positive
attempts and controlled fault proof below.

The next real campaign on commit `6c828d9e` also remained strict **NO-GO**.
Attempt `positive-2ec8aa40c2a4476b8347442550f5ee43` sealed and offline-verified
bundle digest
`sha256:5f23469a3ad137e9724581f4ff1b2c2908de7d21ef3556c1158af943cf5e3498`,
but its independent probe stopped before formal execution. Real NCBI and
UniProt fetches, MAFFT and hmmbuild completed; the runner's private diagnostic
proved that the subsequent SSH connection timed out before the CD-HIT payload
started. The legacy runner regex did not match that OpenSSH timeout wording;
then the absent success-only toolchain marker overwrote the primary nonzero
remote failure, and the Host finally collapsed the unknown runner code to
non-retryable `nonzero_exit`. That three-layer loss of failure identity is
corrected by matching the observed wording, preserving a primary remote
failure whenever the remote command is nonzero, splitting connection timeouts
as `SSH_CONNECTION_TIMEOUT`, and projecting runner transport failures as
retryable `hpc_runner_timeout` or `hpc_runner_unavailable`. A zero-exit command
with a missing or malformed identity marker still fails closed as
`TOOLCHAIN_IDENTITY_MISSING`. Retryability remains an agent-visible fact only:
no operation is automatically replayed, no backend fallback is selected, and
the failed attempt remains non-eligible. The campaign ledger closed at
17,121,634 charged tokens against the fixed 500,000,000 limit with zero
breaches.

A fresh campaign on commit `9778da0` then crossed the earlier runner blocker
but remained strict **NO-GO**. Its known-positive real provider/HPC probe
completed, formal research returned ten PubMed records, and Chrome approved the
first formal NCBI controlled operation through the canonical Web UI. During the
same in-flight drain a later MAFFT approval became durable only after the
public coordinator had entered its failure path. The old driver polled cleanup
for a separate fixed 15-second window, stopped before that approval appeared,
then waited indefinitely for the drain that was synchronously waiting for the
unresolved approval. The pending approval was already present in the public
workspace projection, but the Web UI remained on its last event-triggered
snapshot because `approval.requested` is currently backfilled only after the
drain returns. The operator terminated the hung attempt; it has no sealed
eligible bundle and cannot be reused as either positive evidence or fault
evidence. Its real calls remain charged: the persistent ledger is now
19,439,010 / 500,000,000 tokens with zero breaches.

The correction is deliberately local. After any coordination failure, the
driver preserves that original failure, rejects every later unresolved
approval through the public API, and continues reconciliation until the
already-bound attempt deadline or drain retirement. A transient cleanup read or
resolve error is retained only as safe secondary diagnostics and retried with
the same idempotency key; it never authorizes continued science. The Web UI
keeps SSE as its prompt refresh path but also performs a low-frequency,
single-flight read of the current canonical workspace. Session/version guards
and abortable request generations prevent an old response from overwriting a
newly selected session, mutation response or newer SSE reducer state; a hung
old-session read cannot starve the next session. This does
not add a second truth store or claim bounded process supervision; permanent
worker retirement remains the separate process-isolation proposal.

The next fresh campaign on commit `cde88dd` again remained strict **NO-GO**.
Its real known-positive probe completed and the formal path entered research and
execution, so it crossed the previous SSH/HPC transport blocker. However, the
first real Chrome selection of the formal session exposed a browser-only timer
receiver bug in the new reconciliation path: the controller stored
`window.setTimeout` as an instance property and invoked it with the controller
as its receiver, producing `Illegal invocation`. No approval was accepted and
no eligible bundle or browser observation receipt was sealed. The operator
terminated the disqualified attempt rather than spend more MICU/HPC resources.
Its persistent ledger snapshot is 22,377,359 / 500,000,000 charged tokens with
zero breaches; the interrupted in-flight call remains conservatively charged
as an estimated reservation. Timer hooks are now invoked through detached
wrappers, with a receiver-sensitive regression test. This failed campaign is
diagnostic evidence only and cannot be reused by the next fresh pin.

The following r11 campaign pinned commit
`093c573e0a8f4980d206c708fc60bfcbe7ff14a7` and config digest
`sha256:8e0ce95c21e13d9397586df7fc5bbf52a77246418b075e182024e3dc07487011`,
but also remained strict **NO-GO**. Its real known-positive probe completed all
six controlled operations, the formal researcher preserved real PubMed
evidence, and the same-process Chrome UI resolved the first formal approval.
That initially approved NCBI operation then failed for the real, LLM-readable
reason `provider_output_path_invalid`: the executor supplied relative
`providers/ncbi_aox_reference` rather than the required
`/workspace/output/providers/ncbi_aox_reference`. The agent corrected the
argument and opened a new approval, but event replay also returned an activity
backfill for the earlier approval under the same `approval.resolved` event type.
The canonical command event carried a closed `decision=approved`; the activity
projection echo carried `status=approved` and no `decision`. The r11 driver
mistook that projection echo for a rejection, entered coordination cleanup and
explicitly rejected the corrected pending operation. The resulting attempt
bundle still passed offline integrity verification at
`sha256:3610fc0c9841fd8426111a0c94dfc1def7167e263ef535b5b355c412a4c18260`,
while remaining non-eligible; the campaign sealed the NO-GO decision
`sha256:b80a803bef6af527e723a0fc0e8e87b672016a32dcea6d648d6b148daac88057`.
The persistent ledger closed at 28,150,263 / 500,000,000 charged tokens with
zero breaches. r11 is diagnostic evidence only: neither its bundle, roots nor
browser interaction can be reused by a fresh positive attempt.

The subsequent r12b campaign pinned commit
`3819ba7eab0b7ba9febd43ff13206cf3d0f9e1a6` with the same config digest, but
was also terminated as strict **NO-GO** before it could spend further external
resources. Its formal session already contained two NCBI controlled operations
(`op_80b00685b2a0` completed and `op_fb3cc37d8df6` failed) plus two completed
MAFFT operations (`op_830c597ac386` and `op_e5ca4eba6220`). The second NCBI
request did reach the real adapter before Host artifact-conflict persistence
failed, so it cannot be described as a pre-I/O validation. Both MAFFT jobs
completed with identical alignment bytes, but the final script bound HMMbuild
only to the second artifact identity. The exact-operation-set contract
therefore made the attempt permanently ineligible before EBI HMMER completed;
selecting the newest success or collapsing identical content would hide the
actual operation history and is forbidden. The operator interrupted the
campaign instead of knowingly consuming more provider/MICU budget. The live
ledger then stood at `32,200,575 / 500,000,000` charged tokens with zero hard
limit breaches. r12b has no eligible sealed bundle and none of its sessions,
operations, roots, artifacts or browser interaction can be reused.

The direct trigger was a low-friction harness defect rather than scientific
uncertainty. A recursive executor helper saw one provider file twice through a
canonical manifest row and a nested provenance projection; the same mistake
later counted one fetched MAFFT output twice through top-level `fetch_refs` and
a nested catalog row. Both local parser failures occurred after the controlled
operation had completed, and the repaired script replayed the operation.
`openzyme_pipeline.artifacts` now provides strict direct-field
`provider_file_ref`, `registered_artifact_ref`, and `fetched_output_ref`
helpers. The workflow pack requires attempt-local `/workspace/work`
checkpoints before downstream parsing and forbids a replacement operation when
local source fails. The campaign driver also checks the exact method budget
before every approval and rejects a duplicate or any continuation after a
terminal failed controlled operation before provider/runner dispatch. These
changes preserve the existing exact-operation-set acceptance rule and do not
silently adopt a preferred result.

Supporting explicit cross-run adoption while preserving all failed,
superseded, and abandoned operation facts would change the canonical attempt
model and verifier schema. That larger design is proposal-only in
[canonical scientific chain adoption and attempt closure](architecture-proposals/canonical-scientific-chain-adoption-and-attempt-closure.md)
and is not implemented in this goal.

## Formal AOX scientific closure

The formal NCBI request contains exactly 14 identities: the fixed 13 HMM-model
references plus coordinate reference `AAB57849.1`. The same sealed provider
aggregate is split by versioned calculations, not by copying historical files:

- `aox_hmm_reference_set_selection@1` produces the exact 13-record
  `AOX_ref21.fasta`, which alone enters MAFFT and hmmbuild;
- `aox_reference_selection@1` produces the single-record
  `AOX_coordinate_reference_AAB57849.1.fasta`;
- `aox_scoring_input_assembly@1` produces `AOX_scoring_input.fasta` as AAB first
  plus post-UniProt target records in lexical target-id order.

The discovery path is EBI HMMER `refprot` raw/parsed response →
`hmmer_score_filtered_accessions@1` with score strictly greater than `200` →
an exact conditional UniProt request → `aox_sequence_length_join@1` with
UniProt-derived sequence and inclusive length `650..700` → scoring input →
HMMalign/motif → conditional CD-HIT/similarity. HMMER length/sequence fields,
the probe, and the 13 model references cannot be substituted for UniProt target
truth.

The offline verifier derives one formal branch from sealed bytes:

| branch | stable empty reason | formal operations omitted |
|---|---|---|
| `hmmer_upstream_empty` | `no_hmmer_hits` or `no_filtered_hmmer_accessions` | UniProt, HMMalign, CD-HIT |
| `length_filter_empty` | `no_candidates_after_length_filter` | HMMalign, CD-HIT |
| `motif_filter_empty` | `no_candidates_after_motif_filter` | CD-HIT |
| `nonempty` | n/a | none of the reached chain |

For upstream empty, `provider_upstream_empty_receipt@1` binds the HMMER
score-filter artifact and derivation operation and proves
`provider_io_performed=false`; it has no fabricated invocation, operation,
request, or response digest. For either empty-target branch, HMMalign is not
fabricated: `aox_reference_only_scoring_alignment@1` materializes the verified
AAB-only scoring input. The exact reached/omitted operation set must agree with
the derived branch, and the isolated probe covers required capabilities omitted
from the formal graph.

The executor uses the installed functions
`openzyme_pipeline.aox_reference.select_hmm_reference_set`,
`select_scoring_reference`, `assemble_scoring_input`,
`openzyme_pipeline.aox_hmmer.parse_and_filter_csv`,
`openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions`,
`openzyme_pipeline.aox_motif.score_aligned_fasta`, and
`openzyme_pipeline.aox_similarity.build_similarity_graph`. Provider artifacts
are selected through the unique declared transcript suffixes
`/provider_parsed/proteins.fasta`, `/provider_parsed/parsed_hits.csv`,
`/provider_parsed/sequences.fasta`, and `/provider_parsed/metadata.json`.
MAFFT, hmmbuild, CD-HIT and HMMalign outputs are selected through the unique
`fetch_refs[].declared_output_path` matching the runner-owned paths documented
in [the AOX/HMM workflow guide](execution-pipeline-docs/aox-hmm-live.md). The
fetched hmmbuild artifact id and digest, not a workspace guess, bind the HMMER
search. A formal attempt that approximates these calculations or paths is
ineligible even when its files look plausible.

## Clean-root preflight

Every attempt creates a new attempt root containing initially empty, distinct locations for:

- control-plane SQLite;
- artifact and blob storage;
- persistent executor sandboxes;
- an HPC workspace label/root;
- append-only evidence.

The public root proof contains only stable names, counts, identities and cache policy, never Host paths. `provider_cache_mode=bypass`, `evidence_cache_reuse=false` and `sqlite_preexisting=false` are mandatory. Existing attempt roots, symlinks, preloaded scientific files and unknown prerequisite fields are rejected.

`pin` first derives the declarations and `run-live` resolves the same canonical
launch snapshot before it constructs the campaign runner or any attempt root.
The campaign identity is an exact closed seven-field object:

- `git_commit`;
- `config_digest`;
- `workflow_ref`;
- `scoring_contract_digest`;
- `scoring_implementation_digest`;
- `image_digest`;
- `sdk_digest`.

The launcher derives those values from the clean canonical checkout, the
digest-pinned workflow registry selection, `aox_motif_rule_score@1`, the actual
Pipeline SDK source tree and the Podman sandbox runtime preflight. It compares
the derived object with the declaration field for field; a dirty checkout,
missing/mutable identity, or mismatch stops before root creation.

`config_digest` is the canonical JSON digest of the complete safe preimage
`aox_blank_world_runtime_config@1`. That preimage records the effective
post-foundation configuration, including:

- trusted `local-dev`, single-process SQLite, disabled background runtime and
  principal count;
- HPC backend plus runner-config file digest, provider limits, and the
  runner-owned manifest digest together with the exact closed MAFFT/hmmbuild/
  hmmalign/CD-HIT `tool_id` → `adapter_id`/`command_template_id`/
  `runner_contract_digest` expectation map;
- effective MICU endpoint/model/policies/token/runtime bounds after live-budget
  configuration. Blank-world live requires an explicit
  `context_window_tokens <= 200000`; it must not infer a third-party
  OpenAI-compatible endpoint's context size from the model name;
- research bounds, credential availability, opaque NCBI identity digest and
  tracing digest;
- explicit live-test opt-ins;
- driver approval mode, time/drain/agent bounds, browser observation bounds and,
  for `chrome-once`, the built Web UI dist digest;
- scenario `aox_blank_world_cutover`, the exact cumulative 500,000,000-token
  MICU limit and the existing ledger identity digest.

The preimage never projects raw credentials, the NCBI email, or Host/runner/
ledger paths. It is sealed in each launch receipt and recomputed by the offline
verifier. Before every attempt root is created, the campaign launch guard
recomputes the checkout and effective configuration; any drift fails closed.

`allowed_prerequisites` is also an exact closed object, with exactly these nine
top-level fields and no extras:

1. `git_commit`;
2. `config_digest`;
3. `workflow_ref`;
4. `image_digest`;
5. `sdk_digest`;
6. `toolchain_image_digests`;
7. `credential_slots`;
8. `ncbi_identity`;
9. `prompt_accessions`.

The first five must equal the corresponding launch identity fields.
`credential_slots` contains exactly the boolean keys `llm`, `ncbi`,
`semantic_scholar`, and `tavily`, with `llm=true` and `ncbi=true` mandatory;
it never contains credential values. `ncbi_identity` is an opaque digest.
`prompt_accessions` contains exactly the formal exact-14 NCBI set and the
known-positive NCBI/UniProt probe sets described below. `toolchain_image_digests`
contains exactly:

- `mafft_7.525.hpc_apptainer_sif:v1`;
- `hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1`;
- `hmmer_3.4.hmmalign.hpc_apptainer_sif:v1`;
- `cdhit_4.8.1.hpc_apptainer_sif:v1`.

The hmmbuild and hmmalign values must identify the same immutable HMMER SIF
bytes. Credentials, private locators and scientific bytes are forbidden from
the prerequisite object.

The operator does not guess either closed object. From a clean checkout, `pin`
uses the effective post-foundation settings and the production
`compile_hpc_tool_request` commands to run deterministic non-scientific MAFFT,
CD-HIT, hmmbuild and hmmalign payloads through the configured trusted
`MCPHpcServer` in forced SSH mode. The runner binds its own private SIF locator
and contract, hashes that SIF in the same login shell before and after the real
payload, and emits the closed public runtime identity only on success. The
hmmalign pin consumes the materialized output of the preceding hmmbuild pin;
neither configured locators nor Slurm/discovery metadata can populate
`toolchain_image_digests`. `pin` then calls the same
`prepare_aox_cutover_launch` gate used by `run-live` to detect any intervening
checkout/config/runtime drift.

Both payload files are canonical JSON written with mode `0600` and individual
no-replace publication. They must share one existing real transaction directory
whose two payload targets and fixed marker target do not yet exist. Host fsyncs
both payloads first, then publishes the fixed hidden
`.aox-cutover-pin-commit.json` marker as the single consumer-visible commit
point and fsyncs the directory again. The marker is an exact closed object that
binds both basenames and both canonical payload digests. `run-live` refuses the
pair before launch/root creation when the marker is absent, a symlink, malformed
or digest-drifted. A crash before the marker may leave orphan payload files, but
they can never be consumed as a committed declaration pair; the operator uses a
new transaction directory. Parents must already exist without symlink
traversal, targets must not exist, and checkout-local targets are rejected so
the subsequent clean-checkout guard remains valid. The public pin receipt
contains only commit/config/declaration digests, never an output path,
credential, NCBI identity value, runner locator or Host artifact path.

The unsigned marker is a transaction-integrity commit point, not producer
attestation. `run-live` verifies real regular files, one parent, the exact marker
shape/basenames and both canonical payload digests; it does not prove that an
accepted pair was written by `pin`, that the directory contains no unrelated
files, or that consumer-time modes remain `0600`. The live trusted-operator
contract therefore still requires the canonical `pin` command, while actual
launch recomputation and each live operation's runner-issued identity fail
closed on environment or toolchain drift.

```bash
install -d -m 700 /tmp/openzyme-aox-pin/<campaign-id>
uv --project apps/openzyme-host-api run openzyme-aox-cutover pin \
  --identity-output \
    /tmp/openzyme-aox-pin/<campaign-id>/identity.json \
  --allowed-prerequisites-output \
    /tmp/openzyme-aox-pin/<campaign-id>/allowed-prerequisites.json \
  --approval-mode chrome-once \
  --browser-poll-interval-seconds 0.5 \
  --browser-approval-timeout-seconds 300 \
  --browser-completion-hold-seconds 60 \
  --browser-observation-submission-timeout-seconds 180 \
  --timeout-seconds 1800 \
  --max-drains 120 \
  --max-signals-per-drain 10 \
  --max-steps-per-agent 16
```

These driver arguments, including every Chrome bound, must be repeated exactly
for `run-live`; changing any value changes `config_digest` and is rejected.

Before the first session or model/provider call, the campaign reads the public
Host runtime-health preflight, requires its canonical immutable sandbox image
and Pipeline SDK digests to equal the campaign identity, and only then registers
that verified image identity in the attempt's fresh SQLite repository. Missing
or drifted runtime identity fails closed; a mutable tag or an inherited image
row from another attempt is not accepted. The public preflight image, SDK,
runtime-identity and protocol fields are sealed in the launch receipt, and the
offline verifier compares the image/SDK fields to the campaign identity.

Operator preflight example:

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover preflight \
  --campaign-root /tmp/openzyme-aox-cutover/<campaign-id> \
  --attempt-kind positive \
  --allowed-prerequisites /tmp/aox-allowed-prerequisites.json
```

`local_paths` in this command's stdout are operator-only launch inputs. They must not be copied into workspace/events/report/evidence projections.

## Runner-issued toolchain identity

Every cutover-eligible MAFFT, hmmbuild, hmmalign and CD-HIT operation must carry
`mcp_hpc_toolchain_runtime_identity@1` issued by the runner. The runner-owned
manifest binds the tool, adapter, command template, contract digest and private
SIF locator; a caller cannot submit a locator, runtime request or runtime
identity override. For the current narrow contract, the SSH runner executes the
runner-owned SIF by its resolved pathname in one login shell. Before the first
hash or payload, that shell scrubs every inherited `APPTAINER_*` and
`SINGULARITY_*` runtime-control variable and verifies none remains; inability to
remove any such variable fails before execution. This prevents ambient
trusted-Host configuration from influencing the SIF without requiring the
agent to guess or override Host environment. The shell then hashes that same
pathname immediately before and after the payload, requires both digests to be
identical, removes the private markers from public stdout, and returns the
closed attestation:

- `attestation_scope=same_ssh_login_shell_pre_exec` (the existing closed schema
  name; the runner wrapper still enforces both internal pre- and post-payload
  hashes before emitting it);
- `execution_mode=ssh`;
- exact tool, adapter and command-template ids;
- `runner_contract_digest`;
- the single observed `image_digest`, emitted only when the internal pre/post
  digests are equal.

The Host preserves only this closed public projection across runner adapter,
engine, controlled operation and evidence collector. The collector and offline
verifier compare its image digest with the exact `toolchain_image_digests`
prerequisite for that route. Missing, malformed, caller-injected or mismatched
attestation fails closed.

This proves direct execution of one pathname whose bytes did not change across
the payload; it does not prove an immutable inode/content-addressed execution
snapshot. That stronger guarantee is deferred to the separate
[immutable HPC SIF execution snapshot](architecture-proposals/immutable-hpc-sif-execution-snapshot.md)
proposal and is not implemented by this Goal.

Slurm remains a supported runner execution mechanism in general, but it does
not currently attest the SIF from inside the same scheduled job execution.
Submission/preflight metadata is therefore not reinterpreted as runtime
identity: any AOX cutover tool operation selected as Slurm, or otherwise lacking
the same-shell SSH attestation, is not cutover-eligible. The larger plan to
consolidate parallel toolchain contract definitions is deferred to
[single-source HPC toolchain contract registry](architecture-proposals/single-source-hpc-toolchain-contract-registry.md)
and is not implemented by this Goal.

## Attempt bundle

`aox_blank_world_attempt_bundle@1` is canonical sorted-key UTF-8 JSON wrapped by its SHA-256 payload digest. The payload binds:

- git commit, config, workflow selection, scoring contract/implementation, image and SDK;
- self-consistent clean-root proof and Host launch receipt;
- one continuous MICU ledger before/after transition;
- provider and toolchain invocation/job/operation receipts with sealed formal artifact ids;
- bounded known-positive probe receipts and probe-only artifacts;
- canonical session/message/task/approval/operation identities;
- artifact bytes, provenance and operation input/output digests;
- published report content artifact, source refs, claim links and final master response;
- scoring and similarity recomputation inputs/outputs;
- warnings, enrichment degradations and honest scientific outcome.

An eligible positive attempt additionally requires:

- cache-bypassed PubMed, exact-14 NCBI, and EBI HMMER `refprot` receipts, plus
  either a reached valid UniProt receipt or the strict upstream-empty skip
  receipt;
- completed MAFFT and hmmbuild receipts, plus reached HMMalign/CD-HIT receipts
  or a byte-derived branch that requires their formal omission;
- exactly one durable researcher, executor and reporter task, each explicitly completed;
- exactly one durable delegation receipt per role, with the executor bound to
  the exact campaign workflow manifest and researcher/reporter unbound;
- at least one approved controlled operation with the same operation identity;
- one canonical entry message, root-bound Host launch receipt, workspace/event digests, a non-empty final response and a published report;
- ledger-observed MICU attempt/token growth;
- a passed isolated known-positive provider/HPC attestation whose capability
  union with the reached formal branch is complete.

Failure evidence is still sealed when possible, but `cutover_eligible=false` and therefore stops the campaign before a second positive or GO decision.

## Known-positive probe contract and live gate

The product collector and offline verifier now declare
`aox_known_positive_probe@2` with
`probe_id="independent_globin_provider_hpc_probe"`. This is an implemented
attestation contract, not proof that a real `@2` campaign attempt has passed.
An AAB-only/MAFFT-only `@1` receipt is insufficient and rejected.

The bounded `@2` probe uses NCBI `NP_000509.1` and `NP_000549.1`, UniProt
`P68871` and `P69905`, and exactly six controlled operations: NCBI fetch,
UniProt fetch, MAFFT, hmmbuild, CD-HIT in protein mode at identity `1.0`, and
one HMMalign consuming the real HMM plus the real clustered UniProt FASTA. It
uses one isolated task/workspace/sandbox/source snapshot and binds raw HTTP
response-body digests rather than a parsed-FASTA digest presented as a provider
response digest. EBI HMMER is not duplicated in the probe because every formal
branch already reaches it.

Because the four runner-owned tool templates produce fixed paths, the probe
prompt exposes their exact output contracts: `bio_tools/mafft/alignment.fasta`,
`bio_tools/hmmbuild/model.hmm`, both `bio_tools/cdhit/clustered.fasta` and
`bio_tools/cdhit/clusters.csv`, and `bio_tools/hmmalign/aligned.fasta`. The Host
rejects any different declared path set before HPC dispatch with a
LLM-readable `bio_tool_output_contract_mismatch`; it never rewrites agent code
or treats a predictably missing path as a toolchain health failure.
The probe selects each provider FASTA through the unique
`result_summary.transcript_manifest.files[].relative_path` suffix and never
from positional adapter ID lists. It calls `ws.fetch_outputs` for all four HPC
run handles, including terminal HMMalign, then selects each registered output
through the unique exact `fetch_refs[].declared_output_path`; those fetches
register evidence but do not add controlled operations.

Probe task, operation, invocation and artifact identities must be disjoint from
the formal path. Probe artifacts cannot be selected as formal inputs or cited
by the formal report. Until a real attempt emits this implemented schema and
passes the current offline verifier, the probe criterion remains NO-GO.

## Offline verifier

The verifier makes no network request. It rejects non-canonical/duplicate-key/non-finite JSON, malformed schemas, envelope extras, secret/private path projection, symlink traversal and unreadable artifacts without echoing Host paths. It recomputes:

- bundle, record, artifact content and provenance digests;
- operation/artifact and approval/operation lineage;
- report content/formal scope/claim artifact references;
- exact `aox_motif_rule_score@1` CSV from the sealed alignment;
- similarity nodes/edges/manifest from sealed candidates and CD-HIT membership;
- controlled one-bit fault proof, exact NCBI source, versioned reference-set
  derivation, failed MAFFT consumer, runner-contract expectation, and sealed
  negative-state closure;
- every `openzyme_sealed_source_tree@1` entry and tree digest, plus every
  role-scoped workflow-manifest snapshot and delegation-request digest.

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover verify \
  --bundle <attempt-evidence-root>/attempt-bundle.json \
  --artifact-root <attempt-artifact-root>
```

Exit code is `0` only for a structurally and scientifically verified attempt; verification failure returns `2` and stable issue identities.

## Controlled fault attempt

The required fault contract is
`derived_required_artifact_blob_byte_flip@2`. The only qualifying seam is the
real required chain `bio.ncbi_fetch_proteins` exact-14 `proteins.fasta` →
`aox_hmm_reference_set_selection@1` → `aox_hmm/AOX_ref21.fasta` → pending
MAFFT. The Host flips one bit in the derived `AOX_ref21.fasta` blob after the
versioned selection has reproduced it and before approving its MAFFT consumer.
The attempt records:

- exact source artifact/digest and completed NCBI operation/request identity;
- derivation id, contract digest, implementation digest, input and pre-fault
  output digest;
- target artifact and relative path;
- byte offset;
- before/after content digests;
- the exact pending `bio_tools.mafft` operation and its effective-config runner
  contract expectation;
- terminal `failed`/`recovery_failed` consumer with exact
  `artifact_blob_digest_mismatch`;
- `aox_fault_negative_state_closure@1`, sealing explicit task business exits,
  report/draft states, conversation digests, ordered durable events, every
  direct target consumer, and observed fixed-deliverable paths;
- a non-eligible failure report/outcome backed by that closure artifact.

The offline verifier reverses the recorded bit, recomputes the reference
selection from the sealed NCBI source, verifies the exact MAFFT identity and
effective runner expectation, and requires the execution task to fail/block/
cancel while reporting cannot complete or publish. It rejects any ready or
published report/draft, any successful alternate consumer, any downstream
fixed deliverable, any undeclared file in the authorized artifact root, or a
final assistant response that does not carry the structured fields
`failure_code=artifact_blob_digest_mismatch status=failed` (absence of an
assistant response is allowed). Setting `expected_failure_observed=true`
without this byte, lineage, MICU attribution and negative-state closure is not
evidence.

## Campaign reducer and GO rule

`aox_blank_world_campaign_decision@1` accepts exactly this order:

1. eligible positive attempt;
2. independent eligible positive attempt;
3. controlled fail-closed attempt.

All three pin the same commit/config/workflow/scoring/image/SDK identity and one continuous MICU ledger. Positive attempts must use distinct root/HPC labels, session/message/final-response identities and disjoint task, controlled-operation, provider invocation and toolchain job receipts. Scientific content digests may be identical when providers return the same bytes; execution receipts may not be reused.

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover decide \
  --attempt <positive-1-bundle> <positive-1-artifacts> \
  --attempt <positive-2-bundle> <positive-2-artifacts> \
  --attempt <fault-bundle> <fault-artifacts> \
  --output <campaign-root>/campaign-decision.json
```

Attempt bundles, driver-failure evidence and the decision use atomic no-replace writes plus file/directory fsync. A campaign driver exception produces append-only safe failure evidence and a precise NO-GO; it never falls through to GO.

Real campaign entry point:

```bash
install -d -m 700 /tmp/openzyme-aox-browser-handoff
uv --project apps/openzyme-host-api run openzyme-aox-cutover run-live \
  --campaign-root /tmp/openzyme-aox-cutover/<campaign-id> \
  --identity /tmp/openzyme-aox-pin/<campaign-id>/identity.json \
  --allowed-prerequisites \
    /tmp/openzyme-aox-pin/<campaign-id>/allowed-prerequisites.json \
  --approval-mode chrome-once \
  --browser-poll-interval-seconds 0.5 \
  --browser-approval-timeout-seconds 300 \
  --browser-completion-hold-seconds 60 \
  --browser-observation-submission-timeout-seconds 180 \
  --timeout-seconds 1800 \
  --max-drains 120 \
  --max-signals-per-drain 10 \
  --max-steps-per-agent 16 \
  --browser-observation-receipt \
    /tmp/openzyme-aox-browser-handoff/<campaign-id>.json
```

Every live attempt, including the known-positive probe, positive 2 and the
controlled-fault attempt, uses a same-process loopback HTTP Host.  The current
product drain remains synchronous while a supervised sandbox waits for an
approval, so the cutover driver keeps at most one bounded drain request in
flight and uses the public workspace/approval routes concurrently until that
request returns before a later sequential drain may begin. It auto-resolves
probe and non-Chrome approvals, keeps positive 1's first formal approval
exclusively for the browser, and continues coordinating any later serial
approvals from that same drain. A coordination failure rejects every
still-pending or later-published operation until the existing attempt deadline,
solely to release the failed worker; it never approves an operation as cleanup
or continues scientific execution. Transient cleanup reads/resolves are
retried with stable idempotency while the original coordination blocker remains
authoritative. A successful drain response is not by itself
proof that no last approval became visible: after observing worker terminal,
the coordinator performs one public workspace GET that is known to begin after
that response. Failure arbitration happens only after the drain worker joins:
a drain-command exception remains authoritative, otherwise the earliest public
coordination exception remains authoritative, and a cleanup-only exception uses
`runtime_drain_coordination_cleanup_failed`. Cleanup is still attempted
fail-closed; when it also fails, its safe failure type is retained as secondary
diagnostic metadata in the sealed failure blocker instead of replacing either
earlier blocker. Thus a
background drain exception retains `runtime_drain_command_failed`; only public
coordination/cleanup failures use the coordination taxonomy. The worker must
join before Host teardown or
evidence collection.  Because a client timeout does not prove the synchronous
FastAPI handler has stopped, the loopback Host also tracks every server-side
mutation lifetime, initiates server shutdown, and waits through server retirement
until all of them become idle;
failure/fault/positive evidence and MICU-after collection occur only after the
Host context has fully exited.  If server-side retirement cannot complete, the
campaign remains blocked rather than reading mutable attempt state or claiming
a closed receipt chain. Mutation handlers are forbidden from returning while a
detached writer can still change attempt state. The canonical core and Podman
sandbox control-socket workers are non-daemon; startup failure and stop use a
finite cooperative grace but then wait without a timeout until the worker has
retired, and only then remove its socket. Both core `sandbox.exec` and the
compatibility Podman pipeline runner bind a random container name, protected
unmounted CID file, run-id label and sandbox-root-digest label through the
shared Host runtime lease. Every normal/error/timeout path retires the exact CID
with `kill -> wait -> rm` before stopping the control worker, and returns only
after stable repeated absence of both CID and name; name drift, malformed CID,
identity ambiguity and Podman lifecycle errors remain fail-stop. This
same-process fail-stop may
therefore remain blocked forever after an unrecoverable mutation; process-level
bounded retirement and safe fatal evidence require the separately proposed
[process-isolated live-attempt supervision](architecture-proposals/process-isolated-live-attempt-supervision.md).
This is a cutover-driver workaround, not product-level async drain or
restart-safe continuation; that larger product-runtime change is recorded in
[non-blocking supervised continuation](architecture-proposals/nonblocking-supervised-continuation.md).

Public API receipt sequence is reserved when each request begins and finalized
with that exact response.  This preserves `create < message < drain <
workspace/events` even when the workspace response completes before the blocked
drain response.  Final evidence accepts the sorted contiguous chain only after
all reservations have completed; thread-local response binding prevents a
concurrent drain response from being substituted for the workspace/event call
that produced a semantic snapshot.  A transport or response-normalization
failure retires its reservation as failed and preserves the original blocker in
non-eligible failure evidence; completed response receipts may then contain an
intentional sequence gap and can never be sealed or verified as an eligible
closed chain.

`chrome-once` exposes positive 1 through the Web UI served by the same-process
loopback Host and waits for the first formal approval card. The campaign driver
does not call the approval resolve route for that gate: the operator uses the
public Web UI, which resolves the canonical approval, and the driver observes
ordered durable resolution/continuation events before allowing the same
`operation_id`, operation digest, sandbox run/workspace and continuation to
reach terminal state. The launch receipt seals this lineage and the built UI
dist digest. The event cursor is captured before the drain that exposes the
handoff, so an immediate browser resolution is reconstructed from durable
events instead of racing a later snapshot. A resolution consumer treats only
the canonical `approval.resolved` command event carrying a closed
`decision=approved|rejected` as operator evidence. An activity-backfill
projection may currently reuse that event type while carrying approval
`status` but no `decision`; such an echo is ignored as neither approval nor
rejection. A canonical `decision=rejected` still fails closed immediately, and
failure to observe any canonical closed decision remains bounded by the
approval timeout rather than being inferred from projection state. The
independent approval deadline
starts when the handoff is emitted and is capped by the attempt-wide deadline;
after formal completion the driver keeps a bounded UI observation window.
Under the trusted-operator contract, the final observation target must remain
absent during that entire window; the operator writes a sibling temporary file,
fsyncs it, and atomically renames it only after the handoff's
`receipt_not_before_unix_ns`, within the separately sealed positive finite
observation-submission timeout (default 180 seconds). The current Host rejects a
target seen by any bounded hold poll or whose final mtime predates the hold end,
then requires a non-symlink regular file to remain identical across two
stat/read passes. That proves a fresh stable post-hold final file within the
trusted boundary; it does not prove continuous absence between polls or the
atomic-rename/fsync provenance of that file.
The sealed
`aox_browser_observation_receipt@2` binds the challenge, same page/Host/UI dist,
terminal page state, DevTools transcript, zero application console errors, a
fully decodable PNG, and Host acceptance timing. Public API receipts use the
closed seven-field form including `response_semantic_digest`. The last public
workspace GET and full `after_cursor=0,replay=true` event GET are copied into
bundle-level attestation artifacts; they are not registered back into product
state. Browser approval evidence is valid only for `chrome-once` positive 1.
Because the synchronous sandbox can commit a pending approval before the drain
returns and before its `approval.requested` event is backfilled, the Web UI also
reconciles the currently selected public workspace every five seconds. These
reads are single-flight per active generation and session/version guarded.
Session switches, mutations and applied SSE reducers abort/invalidate older
generations without allowing an old `finally` to clear a newer request; SSE
remains the low-latency path, and neither refresh mechanism mutates approval or
runtime state.

The `approval_required` and `ready_for_completion_observation` handoffs are
dynamic-identity-complete for the trusted Chrome operator. In addition to the
actual loopback HTTP `ui_url`, they expose the sealed logical `page_url`, Host
process id, served UI-dist digest, challenge and raw receipt schema identifier.
They do not carry a standalone receipt builder: the versioned exact field and
digest rules are the static contract below and in `aox_cutover_live.py`. The operator opens
the actual HTTP URL, but writes the sealed logical value
`loopback://same-process/ui/?project_id=aox-blank-world-cutover` into the
receipt. The raw JSON has exactly 23 fields:

- schema/mode/challenge plus session, approval and operation ids;
- sealed page URL, Host process, UI-dist digest and actual Chrome page target;
- hold duration, normalized non-error console entries and their digest, with
  `application_error_count=0`;
- the exact `expected_page_state` supplied after the operator independently
  checks the visible/public terminal semantics, plus its digest;
- one command receipt and an ordered transcript covering at least
  `list_console_messages`, `evaluate_script` and `take_screenshot`;
- strict base64 PNG bytes, raw-byte SHA-256 and IHDR width/height.

All object/list digests use canonical JSON with UTF-8, sorted keys, compact
separators and no NaN. The command and response digest preimages remain the
closed forms enforced by `aox_cutover_live.py`; the screenshot digest is over
raw PNG bytes, not base64 text. Any observed application error is a hard
failure and must not be filtered out to manufacture zero. After accepting the
raw receipt, Host appends exactly six timing fields: hold seconds/satisfied,
submission timeout seconds, ready/not-before timestamps and acceptance
timestamp. The offline verifier binds both time bounds back to effective
config and rejects acceptance before hold end or after the submission
deadline.

The sibling-temp/fsync/atomic-rename sequence is a mandatory trusted-operator
write protocol, not a Host-observed filesystem provenance claim. The accepted
receipt proves only the polling, mtime, regular-file and double-read stability
checks described above.

This `@2` contract is intentionally a trusted-operator observation receipt. It
does not claim a signed, browser-origin-complete, independently replayable raw
MCP transcript. The larger authority/normalization redesign is recorded in
`architecture-proposals/verifiable-chrome-devtools-observation-transcript.md`
and is not implemented by this cutover goal.

Use `--approval-mode auto` only when collecting a non-Chrome campaign that is
expected to remain short of the Chrome GO criterion. The command runs positive
1, positive 2 and the controlled fault in order; any missing receipt, failed
offline verification, identity mismatch or MICU ledger violation produces
NO-GO and exit code `2`.

## Current acceptance boundary

Offline unit/eval success proves implementation behavior only. Local Live cutover becomes GO only after the real public product path also demonstrates:

- two clean-root positive runs with published reports and passed offline verification;
- one reached derived AOX-reference fault with exact NCBI→selection→MAFFT
  lineage and sealed negative-state closure;
- at least one Chrome-observed approval resume of the same operation plus consistent workspace/events/report/evidence and a clean console;
- focused, frontend, non-live, mainline, eval and live provider/LLM/HPC gates;
- a sealed decision from the real attempt digests and final cumulative MICU usage.

Until those artifacts exist, documentation and UI must state NO-GO. Historical S15 and deterministic fixtures remain `fixture_non_cutover` regardless of local test status.
