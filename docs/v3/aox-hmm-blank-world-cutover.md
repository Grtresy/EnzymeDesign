# AOX/HMM blank-world cutover evidence contract

Status: implementation and offline gates in progress; local Live cutover remains **NO-GO** until two real positive attempts and one real controlled fault attempt are sealed and verified on one commit/config identity.

This document describes the operator/evidence boundary implemented by `openzyme_host_api.aox_cutover_evidence`. It does not turn the historical S15 fixture into live evidence and does not authorize seeded state, cached scientific outputs, the reference notebook, or copied reference results as attempt inputs.

## Fixed scope

- Runtime remains single-process SQLite and the runner remains trusted-Host-only.
- Scientific failures are fail closed; an honest no-hit/no-candidate outcome may publish a healthy empty report but cannot claim discovery.
- The formal workflow uses `aox_motif_rule_score@1`, canonical real-sequence similarity, `cdhit_cluster_membership@1`, and digest-pinned workflow/image/SDK identities.
- The existing cumulative MICU ledger is read before and after every attempt. Its hard limit is exactly 100,000,000 input+output tokens; it is never reset by campaign setup.
- A bounded known-positive provider/HPC probe is separate from formal artifacts. Probe artifacts cannot enter formal operations or the published report.

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
  configuration;
- research bounds, credential availability, opaque NCBI identity digest and
  tracing digest;
- explicit live-test opt-ins;
- driver approval mode, time/drain/agent bounds, browser observation bounds and,
  for `chrome-once`, the built Web UI dist digest;
- scenario `aox_blank_world_cutover`, the exact cumulative 100,000,000-token
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
  negative-state closure.

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

`chrome-once` exposes positive 1 through the Web UI served by the same-process
loopback Host and waits for the first formal approval card. The campaign driver
does not call the approval resolve route for that gate: the operator uses the
public Web UI, which resolves the canonical approval, and the driver observes
ordered durable resolution/continuation events before allowing the same
`operation_id`, operation digest, sandbox run/workspace and continuation to
reach terminal state. The launch receipt seals this lineage and the built UI
dist digest. The event cursor is captured before the drain that exposes the
handoff, so an immediate browser resolution is reconstructed from durable
events instead of racing a later snapshot. The independent approval deadline
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
