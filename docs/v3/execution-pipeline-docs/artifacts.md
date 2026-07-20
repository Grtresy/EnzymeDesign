# Artifacts

Use `artifacts` for explicit movement between the canonical artifact catalog and the executor sandbox.

The sandbox working copy is mutable. The artifact catalog is canonical and immutable/versioned. Files become canonical only when the executor registers outputs or snapshots source code.

There are two artifact read surfaces:

- control-plane agent tools: `artifact.list`, `artifact.get`, `artifact.preview`, `artifact.read_text`, and `artifact.range`; these return safe session catalog records and bounded UTF-8 text content by `artifact_id`
- sandbox SDK: `openzyme_pipeline.artifacts`; this is available only inside the controlled execution sandbox and returns sandbox-safe paths for artifacts explicitly authorized for the current session/task/lane

Neither surface returns the Host-private `storage_uri`, BlobStore path, sandbox host path, or runner path.

`artifact.list` has a hard 100,000-character budget measured against the same
ASCII-safe canonical JSON representation returned to the model. The response
reports `returned_count` and `truncated_by_budget`; when budget truncation
occurs, `next_offset` identifies the first artifact not returned, so continuing
the page cannot skip a record. Metadata, omission summaries, and free-text
catalog fields are independently bounded inside each row.

Short scalar and schema/contract/count/digest identity fields remain visible,
while large lists such as accessions, raw-page digests, or file manifests are
replaced by a deterministic `artifact_list_metadata_summary@1`
`metadata_summary`. Oversized title/description/path fields use
`artifact_list_record_summary@1`. Hints marked `exact_pageable` contain a real
`artifact.get` path; hints marked `root_only` can page only the parent dict.
Keys containing dots, spaces, or other characters outside `[A-Za-z0-9_-]`
must never be advertised as exact dot paths. Large strings are read by
character `offset`/`limit`, up to 12,000 characters per page. A large dict
page's own `read_hint` is either the executable request for that same dict's
next page or `null`; executable exact-child hints belong only to individual key
records. A missing summary field never means the underlying metadata is empty.

The storage model has two layers:

- Blob layer: Host-private sealed file/tree content addressed by `content_digest` or `tree_digest`.
- Artifact layer: immutable catalog records keyed by `artifact_id`, carrying kind/format, validation result, provenance, sealed digest, and workspace-facing `relative_path`.

`relative_path` is only a display/tree hint. Duplicate paths remain separate artifact leaves and must be distinguished by `artifact_id`.

## Materializing Inputs

```python
receptor_path = artifacts.materialize("art_receptor", target_path="/workspace/input/receptor.pdb")
```

`artifacts.materialize()` copies or maps an authorized artifact into the sandbox and returns a sandbox-safe path. The target must stay inside the allowed sandbox workspace/input area. Use this when the executor needs ordinary file operations before a pipeline run.

`artifacts.get()` remains available as a lightweight reference API for compatibility:

```python
receptor = artifacts.get("art_receptor")
```

It only returns artifacts authorized for the current session, task, and lane. It returns a sandbox-safe projection, never the Host `storage_uri`. This SDK call is not the control-plane agent tool `artifact.get(path, offset, limit)`: it does not implement metadata paging and must not emit that tool's `exact_pageable` hint. On the current S09 path it returns the safe catalog record when that record fits the 4 MiB control frame; an oversized record fails explicitly. Use `materialize()` for file bytes and model large reusable metadata as a registered evidence artifact. True bounded metadata-manifest paging is deferred.

The only cross-runner stable field on this compatibility response is:

- `artifact_id`

The S09 catalog projection also carries `relative_path`, `kind`, `title`, bounded control-plane identities and `metadata`; the active compatibility runner may instead carry a sandbox-local `path` plus `format`/digest. New code must not infer Host location from either shape.

## Snapshotting Code

Source edited in `/workspace` is not canonical until it is snapshotted:

```python
source = artifacts.snapshot_code(
    paths="/workspace/src",
    entrypoint="/workspace/src/main.py",
    metadata={"semantic_type": "pipeline_source_snapshot"},
)
```

`snapshot_code` creates an immutable `ArtifactKind.CODE` record with `sandbox_workspace_id`, entrypoint, `source_tree_digest`, file digest manifest, and parent snapshot metadata. `sandbox.exec`, approvals, SDK operations, backend runs, and output provenance must bind to this snapshot. If the executor edits `/workspace/src` after a run starts, the existing run keeps its original snapshot; formal output from new source requires a new `sandbox.exec` / snapshot.

Cutover evidence does not treat that directory-backed catalog record as an
ordinary file. The collector converts a typed
`semantic_type=pipeline_source_snapshot` / `format=source_tree` directory into
canonical `openzyme_sealed_source_tree@1` JSON: sorted relative paths, exact
sizes, per-file digests and base64 bytes plus the original `source_tree_digest`.
Both bundle construction and the offline verifier decode every file and
recompute the tree digest. Symlinks, non-regular entries, empty trees, unsafe
paths, duplicate/unsorted rows or a provenance mismatch fail closed.

## Registering Outputs

Only files under `/workspace/output` or SDK-fetched outputs can be registered.

```python
artifacts.register(
    path="/workspace/output/prepared_ligand.pdbqt",
    kind="structure",
    format="pdbqt",
    metadata={"purpose": "vina ligand input"},
)
```

For fetched HPC outputs:

```python
from openzyme_pipeline import artifacts, hpc, structure_tools

structure = artifacts.get("art_structure")
ws = hpc.workspace("fpocket")
remote_structure = ws.stage_artifact(
    structure["artifact_id"],
    workspace_path="inputs/structure.pdb",
)
run = structure_tools.fpocket(
    structure=remote_structure,
    placement=ws,
    expected_outputs=[
        {"path": "target_out", "kind": "directory", "format": "fpocket"},
    ],
)
result = ws.fetch_outputs(run)
output = artifacts.fetched_output_ref(
    result,
    declared_output_path="target_out",
)
print(output["artifact_id"], output["content_digest"])
```

Fetched outputs must be declared, actually returned as readable content by the runner, fetched by the Host supervisor, and registered as artifact refs rather than exposed as private runner paths. A missing declared output, failed run, or unreadable fetch source is a structured failure and never creates a synthetic scientific artifact. Explicit non-cutover fixture/simulation outcomes are the sole exception; their placeholders carry `synthetic_source=true`, `cutover_eligible=false`, and non-product scientific status.

Registering performs a Host-supervised transaction: source digest/tree manifest, validator, temporary Blob write, sealed digest recheck, immutable Artifact row commit, and workspace manifest update. If validation, sealing, provenance, or commit fails, no visible artifact is created and the SDK receives a structured error.

The public `metadata=` parameter remains one logical JSON object. The SDK canonicalizes it with ASCII-safe strings, sorted keys, compact separators and no non-finite values. Objects up to `256 KiB` stay inline. Objects larger than `256 KiB` and no larger than `32 MiB` are automatically written to the attempt-local `/workspace/work/.openzyme/artifact-metadata/<sha256>.json`; only the closed `artifact_registration_metadata_sidecar@1` descriptor crosses the socket. Do not construct that descriptor or file manually. Above `32 MiB`, register the oversized evidence as its own Artifact and keep only a canonical artifact ref in metadata.

The Host opens sidecars through the current workspace with directory-fd anchoring and no-follow semantics, then validates exact path, size, digest, UTF-8, duplicate keys, non-finite values, object root and canonical bytes before validation/seal/catalog mutation. Top-level `content_digest`, `sealed_digest`, and `tree_digest` are Host-owned registration identity fields; caller metadata containing any of them is rejected locally and again at the raw Host boundary. Nested artifact refs may still carry their own digest fields. The sidecar is transport spool only: it is not an 18th AOX deliverable, scientific evidence or canonical metadata storage. The Artifact row still contains the complete logical metadata object.

Successful canonical registration returns `artifact_registration_response@2`. Its `artifact` is the exact closed `{artifact_id, metadata}` projection, not the general public Artifact record; context, path, title and other catalog fields are intentionally absent. The Host-generated artifact id is limited to 256 UTF-8 bytes. `artifact.metadata` is `artifact_registration_metadata_summary@1`, and `validation` is `artifact_registration_validation_summary@1`; both carry digest/count/size identity while keeping the response bounded. A missing large field in either summary never means the canonical row was truncated. The active compatibility runner instead returns a compact `pipeline_provisional_registration_response@1` with `canonical=false`; it omits repeated path fields, remains bounded at the 128-item batch maximum, is run-local collection state and cannot be selected as a durable catalog ref.

`register_many` is limited to 128 items and 32 MiB of unique logical metadata per request. All metadata transports are resolved before the first item commit, so a bad sidecar creates no item Artifact. The compatibility implementation still commits valid items sequentially; a later path/validator/seal/commit failure is not an all-or-nothing transaction. Do not build scientific atomicity assumptions on this helper.

`kind` is a closed wire enum, not a free-form scientific label. The exact
values are `code`, `log`, `sequence`, `structure`, `report`,
`research_dossier`, `result`, `cache`, and `other`. Put the concrete encoding
or scientific file family in `format` or metadata: for example an HMM is
`kind="result", format="hmm"`, not `kind="model"`. Likewise `alignment`,
`table`, and `graph` are not artifact kinds. `kind="directory"` is retained
only as the established `expected_outputs` shape sentinel; it is never stored
as an artifact kind, and directory content is registered under a real enum
value. The sandbox SDK validates this
enum before opening the control socket, and the Host artifact boundary repeats
the validation for older or bypassing callers. An invalid value fails
non-retryably as `artifact_kind_invalid` before file sealing or external work.

The source snapshot is Host authority, not a caller-supplied claim. Control-socket
registration binds the snapshot sealed for the current `sandbox.exec`; provider
artifactization and adapter-backed HPC output fetch bind their controlled
operation snapshot. A stale prior command summary must not override that current
run/operation identity.

## Closed response selectors

Rich Host responses may repeat one artifact in nested provenance projections.
Do not recursively search them. The sandbox SDK provides three pure,
non-I/O selectors. They are alternatives for three different response types,
not a selector pipeline:

- `artifacts.registered_artifact_ref(response)` reads only the closed
  `artifact_registration_response@2`, requires its bounded metadata and
  validation summary schemas, requires an exact file projection whose top-level
  and summary `tree_digest` are null and whose summary `content_digest` and
  `sealed_digest` both equal the top-level digest, and returns canonical
  `artifact_id` plus `content_digest`;
- `artifacts.provider_file_ref(operation, relative_path_suffix=...)` reads only
  `result_summary.transcript_manifest.files` and requires one exact suffix
  match;
- `artifacts.fetched_output_ref(fetch, declared_output_path=...)` reads only the
  top-level `fetch_refs` list and requires one exact declared-path match.

`provider_file_ref` and `fetched_output_ref` already return the terminal
canonical `{artifact_id, content_digest}` reference. Stage or consume that
mapping directly. Never pass it to `registered_artifact_ref`, and never
synthesize an `artifacts.register`-shaped envelope. The latter selector accepts
only the direct response returned by a real `artifacts.register(...)` call.

All three validate non-empty identities and lowercase canonical SHA-256
digests. Missing, duplicate, malformed, or nested-only data raises a
non-retryable `PipelineSdkError` at `artifacts.response_selection`. The helpers
never choose list order, search a fallback projection, register or materialize
content, replay a provider/tool operation, or conceal an ambiguous response.
Passing an already-selected canonical ref to `registered_artifact_ref` fails as
`artifact_ref_already_canonical` rather than silently treating selector output
as a registration response.

Built-in validators normally enforce non-empty output plus format checks for
FASTA, HMM, CSV, JSON, and text-like outputs. `metadata.required_columns` can
only tighten CSV validation; it cannot bypass the built-in validator. It is
bounded to 4,096 non-empty string entries, 256 UTF-8 bytes per name and 64 KiB
in aggregate; oversized or non-string shapes fail before Artifact mutation.

The sole current typed exception is a scientifically derived zero-record FASTA:

```python
artifacts.register(
    path="/workspace/output/target.fasta",
    kind="sequence",
    format="fasta",
    validation_profile="fasta_zero_records@1",
    metadata={
        "empty_result_reason": "no_candidates_after_length_filter",
        "derivation_contract_id": "aox_sequence_length_join@2",
    },
)
```

This profile accepts only an exact zero-byte regular file, `kind=sequence`, a
FASTA format, one stable lowercase reason and one versioned derivation contract
whose identifier is no longer than 256 UTF-8 bytes.
Without the profile, zero bytes remain invalid; with it, any whitespace,
header-only file, sentinel residue or other non-zero content remains invalid.
The byte validator does not decide that the scientific branch was legitimate:
the workflow-specific collector/offline verifier must still recompute the
upstream derivation and omitted-operation closure. For AOX cutover evidence,
the collector also seals `openzyme_typed_empty_artifact_validation@1` from the
catalog metadata and exact validation result; the offline verifier reconstructs
that validation digest and rejects every zero-byte sequence without it.

Do not register arbitrary absolute host paths. Dry-run must reject them.

Pipeline code must not infer Host paths from workspace/API responses. Inputs must be authorized through the artifact catalog and staged/materialized by the Host supervisor; runner/HPC inputs must use staged sandbox or runner paths derived from that authorization.
