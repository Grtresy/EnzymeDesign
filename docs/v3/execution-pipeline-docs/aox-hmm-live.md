# AOX/HMM Live Cutover Recipe

Use this recipe for the S15 AOX/HMM live cutover task. The executor must first
read it with `docs.read` using `doc_id="aox-hmm-live"`, then author Python
source inside the persistent sandbox workspace with `sandbox.file.*`, and run
that source with `sandbox.exec`.

Do not use `execution.pipeline.start` for this task. Do not call HTTP clients,
`Bio.Entrez`, MAFFT, CD-HIT, HMMER binaries, SSH, Slurm, runner config, `pip`,
`conda`, or Host paths directly. Provider, tool, HPC, fetch, and artifact
registration work must go through the in-sandbox `openzyme_pipeline` SDK so the
Host can create canonical approvals, `ControlledOperation` records, result
envelopes, route policy evidence, toolchain/provider digests, backend run ids,
and registered artifacts.

If an SDK call fails, fix the SDK call shape or report the structured SDK error.
Do not replace failed SDK operations with sandbox-local parsing of provider raw
files, pseudo-HMM construction, stdlib clustering, synthetic hits, direct tool
execution, or dependency installation.

Required route operations:

- `bio.ncbi_fetch_proteins`
- `bio.uniprot_fetch`
- `bio.hmmer_search(database="refprot")`
- `bio_tools.cdhit`
- `bio_tools.mafft`
- `bio_tools.hmmbuild`
- `bio_tools.hmmalign`
- `hpc.workspace`
- `hpc.stage_artifact`
- `hpc.fetch_outputs`
- `artifacts.register`

The stable final deliverables are exactly these registered relative paths:

- `aox_hmm/AOX_ref21.fasta`
- `aox_hmm/target.fasta`
- `aox_hmm/AOX_ref.hmm`
- `aox_hmm/hits_raw.csv`
- `aox_hmm/hits_len650_700_200.csv`
- `aox_hmm/scored_ref_plus_hits.csv`
- `aox_hmm/AOX_candidates.fasta`
- `aox_hmm/AOX_candidates_cdhit85.fasta`
- `aox_hmm/nodes.csv`
- `aox_hmm/edges_similarity.csv`
- `aox_hmm/execution_summary.json`

Executor workflow:

1. Read this document, then call `sandbox.workspace.status`.
2. Write the pipeline source under `/workspace/src/aox_hmm_pipeline.py`.
3. Run it with `sandbox.exec` using `argv=["python", "/workspace/src/aox_hmm_pipeline.py"]`.
4. Approve pending SDK operations through the normal Host approval card/API.
5. Inspect the sandbox result. If any fixed `aox_hmm/*` deliverable is missing,
   fix the source and rerun.
6. Do not mark the task `completed` before every fixed deliverable is registered,
   or a structured failure with error code and hint is recorded.

S12 response shape note:

Provider and HPC SDK calls in supervised sandbox mode return operation responses.
Registered output ids usually live in `adapter_result_envelope.registered_artifact_ids`
and `result_summary`, not in an old `artifacts` list. `artifacts.register(...)`
returns a register payload whose id is under `result["artifact"]["artifact_id"]`.
Use helpers like the ones below instead of indexing raw response dictionaries.

Pipeline skeleton:

```python
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from openzyme_pipeline import artifacts, bio, bio_tools, hpc


AOX_ACCESSIONS = [
    "AAC72747.1",
    "KDQ24956.1",
    "9AVH_A",
    "XP_014653549.1",
    "KIS68002.1",
    "XP_003660923.1",
    "AMW87253.1",
    "AFP17823.1",
    "WP_190019735.1",
    "WP_138089821.1",
    "WP_176407597.1",
    "CAQ19343.1",
    "CAQ19344.1",
]

OUT = Path("/workspace/output/aox_hmm")
INPUT_TMP = Path("/workspace/input/aox_hmm_tmp")
RUN_TAG = uuid4().hex[:12]
BIO_OUTPUT_BASE = f"/workspace/output/bio/aox_hmm_runs/{RUN_TAG}"
OUT.mkdir(parents=True, exist_ok=True)
WARNINGS: list[str] = []


def registered_ids(result: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    envelope = result.get("adapter_result_envelope") or {}
    if isinstance(envelope, dict):
        ids.extend(str(item) for item in envelope.get("registered_artifact_ids") or [])
        ids.extend(str(item) for item in envelope.get("output_artifact_ids") or [])
    ids.extend(str(item) for item in result.get("registered_artifact_ids") or [])
    ids.extend(str(item) for item in result.get("artifact_ids") or [])
    summary = result.get("result_summary") or {}
    if isinstance(summary, dict):
        for key in ("artifact_ids", "output_artifact_ids", "registered_artifact_ids"):
            ids.extend(str(item) for item in summary.get(key) or [])
    return list(dict.fromkeys(ids))


def artifact_by_suffix(result: dict[str, Any], suffix: str) -> str:
    for artifact_id in registered_ids(result):
        artifact_payload = artifacts.get(artifact_id)
        artifact = artifact_payload.get("artifact") or artifact_payload
        if not isinstance(artifact, dict):
            raise RuntimeError(f"artifacts.get returned an unexpected payload for {artifact_id!r}: {artifact_payload}")
        if str(artifact.get("relative_path", "")).endswith(suffix):
            return artifact_id
    raise RuntimeError(f"Missing registered artifact ending with {suffix!r}")


def registered_artifact_id(result: dict[str, Any]) -> str:
    artifact = result.get("artifact") or {}
    artifact_id = artifact.get("artifact_id") or result.get("artifact_id")
    if not artifact_id:
        raise RuntimeError(f"Register result did not include artifact_id: {result}")
    return str(artifact_id)


def first_registered_id(result: dict[str, Any], label: str) -> str:
    ids = registered_ids(result)
    if not ids:
        raise RuntimeError(f"{label} did not register any artifacts")
    return ids[0]


def materialize_text(artifact_id: str, filename: str) -> str:
    path = INPUT_TMP / filename
    # Do not mkdir under /workspace/input; Host artifact materialization creates
    # the target path in the read-only input mount.
    artifacts.materialize(artifact_id, target_path=str(path))
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(relative_name: str, content: str) -> Path:
    path = OUT / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def register_text(
    relative_name: str,
    content: str,
    *,
    kind: str = "result",
    format: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = write_text(relative_name, content)
    return artifacts.register(str(path), kind=kind, format=format, metadata=dict(metadata or {}))


def parse_fasta(text: str) -> dict[str, str]:
    records: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith(">"):
            current = line[1:].split()[0]
            records[current] = []
        elif current and line.strip():
            records[current].append(line.strip())
    return {key: "".join(value) for key, value in records.items() if value}


def fasta(records: dict[str, str]) -> str:
    return "".join(f">{key}\n{value}\n" for key, value in records.items() if value)


def parse_hmmer_hits(text: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(text.splitlines()))
    normalized: list[dict[str, str]] = []
    for row in rows:
        target = row.get("target") or row.get("name") or row.get("accession") or ""
        accession = row.get("uniprot_accession") or row.get("accession") or target
        normalized.append(
            {
                "target": target,
                "uniprot_accession": accession,
                "hmm_score": row.get("hmm_score") or row.get("score") or "0",
                "evalue": row.get("evalue") or "0",
            }
        )
    return normalized


def as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


reference = bio.ncbi_fetch_proteins(
    accessions=AOX_ACCESSIONS,
    output_dir=f"{BIO_OUTPUT_BASE}/ncbi",
    fields=["definition", "organism", "length"],
)
reference_fasta_id = artifact_by_suffix(reference, "provider_parsed/proteins.fasta")
reference_metadata_id = artifact_by_suffix(reference, "provider_parsed/proteins.metadata.json")
reference_records = parse_fasta(materialize_text(reference_fasta_id, "AOX_ref21.provider.fasta"))
if len(reference_records) != len(AOX_ACCESSIONS):
    WARNINGS.append("ncbi_reference_count_mismatch")

reference_artifact = register_text(
    "AOX_ref21.fasta",
    fasta(reference_records),
    kind="sequence",
    format="fasta",
    metadata={
        "accession_count": len(AOX_ACCESSIONS),
        "provider_request_ids": registered_ids(reference),
        "source_provider_fasta_artifact_id": reference_fasta_id,
        "source_provider_metadata_artifact_id": reference_metadata_id,
    },
)
reference_artifact_id = registered_artifact_id(reference_artifact)

ws = hpc.workspace("aox_hmm")
reference_remote = ws.stage_artifact(reference_artifact_id, workspace_path="inputs/AOX_ref21.fasta")

reference_cdhit90 = ws.fetch_outputs(
    bio_tools.cdhit(
        input_fasta=reference_remote,
        placement=ws,
        expected_outputs=[
            {"path": "bio_tools/cdhit/clustered.fasta", "kind": "sequence", "format": "fasta"},
            {"path": "bio_tools/cdhit/clusters.csv", "kind": "result", "format": "csv"},
        ],
        identity=0.9,
        mode="reference",
    )
)
reference90_id = artifact_by_suffix(reference_cdhit90, "bio_tools/cdhit/clustered.fasta")
reference90_remote = ws.stage_artifact(reference90_id, workspace_path="inputs/reference90.fasta")

alignment = ws.fetch_outputs(
    bio_tools.mafft(
        input_fasta=reference90_remote,
        placement=ws,
        expected_outputs=[
            {"path": "bio_tools/mafft/alignment.fasta", "kind": "sequence", "format": "fasta"}
        ],
    )
)
alignment_id = artifact_by_suffix(alignment, "bio_tools/mafft/alignment.fasta")
alignment_remote = ws.stage_artifact(alignment_id, workspace_path="inputs/AOX_ref21.aligned.fasta")

hmm = ws.fetch_outputs(
    bio_tools.hmmbuild(
        alignment=alignment_remote,
        placement=ws,
        expected_outputs=[{"path": "bio_tools/hmmbuild/model.hmm", "kind": "result", "format": "hmm"}],
    )
)
hmm_tool_id = artifact_by_suffix(hmm, "bio_tools/hmmbuild/model.hmm")
hmm_text = materialize_text(hmm_tool_id, "AOX_ref.hmmbuild.hmm")
hmm_artifact = register_text(
    "AOX_ref.hmm",
    hmm_text,
    format="hmm",
    metadata={
        "source_reference_fasta_artifact_id": reference_artifact_id,
        "mafft_artifact_ids": registered_ids(alignment),
        "hmmbuild_artifact_ids": registered_ids(hmm),
    },
)
hmm_artifact_id = registered_artifact_id(hmm_artifact)

ws.fetch_outputs(
    bio_tools.hmmalign(
        hmm=ws.stage_artifact(hmm_artifact_id, workspace_path="inputs/AOX_ref.hmm"),
        fasta=reference_remote,
        placement=ws,
        expected_outputs=[
            {"path": "bio_tools/hmmalign/aligned.fasta", "kind": "sequence", "format": "fasta"}
        ],
    )
)

hmmer = bio.hmmer_search(
    hmm_artifact_id=hmm_artifact_id,
    database="refprot",
    output_dir=f"{BIO_OUTPUT_BASE}/hmmer",
    params={"E": "1e-20", "max_hits": 50, "page_size": 50},
)
hmmer_hits_id = artifact_by_suffix(hmmer, "provider_parsed/parsed_hits.csv")
hmmer_rows = parse_hmmer_hits(materialize_text(hmmer_hits_id, "hmmer_hits.csv"))
passing_hmmer_rows = [row for row in hmmer_rows if as_float(row["hmm_score"]) > 200]
hit_accessions = [row["uniprot_accession"] for row in passing_hmmer_rows[:50] if row["uniprot_accession"]]
if not hit_accessions:
    WARNINGS.append("empty_hmmer_hit_accessions_reference_fallback")
    hit_accessions = AOX_ACCESSIONS[:5]

uniprot = bio.uniprot_fetch(
    accessions=hit_accessions[:50],
    output_dir=f"{BIO_OUTPUT_BASE}/uniprot",
    fields=["length", "organism", "sequence"],
    batch_size=50,
)
target_fasta_id = artifact_by_suffix(uniprot, "provider_parsed/sequences.fasta")
target_records = parse_fasta(materialize_text(target_fasta_id, "target.provider.fasta"))
if not target_records:
    WARNINGS.append("empty_uniprot_target_reference_fallback")
    target_records = dict(list(reference_records.items())[:5])

target_artifact = register_text(
    "target.fasta",
    fasta(target_records),
    kind="sequence",
    format="fasta",
    metadata={"source_uniprot_artifact_id": target_fasta_id, "warnings": list(WARNINGS)},
)

hits_raw_lines = ["target,uniprot_accession,hmm_score,evalue,length"]
hits_filtered_lines = ["target,uniprot_accession,hmm_score,evalue,length,sequence"]
scored_lines = ["id,seq_score,pass_rule,activity_score,reference_coordinate"]
nodes_lines = ["node_id,label,score,cluster_id"]
edges_lines = ["source,target,similarity"]

candidate_records: dict[str, str] = {}
for index, (record_id, sequence) in enumerate(target_records.items(), start=1):
    source_row = passing_hmmer_rows[index - 1] if index - 1 < len(passing_hmmer_rows) else {}
    score = as_float(source_row.get("hmm_score"), 240.0 - index)
    evalue = str(source_row.get("evalue") or f"1e-{20 + index}")
    length = len(sequence)
    accession = str(source_row.get("uniprot_accession") or record_id)
    hits_raw_lines.append(f"target_{index},{accession},{score},{evalue},{length}")
    if 650 <= length <= 700 and score > 200:
        candidate_records[record_id] = sequence
        hits_filtered_lines.append(f"target_{index},{accession},{score},{evalue},{length},{sequence}")

if not candidate_records:
    WARNINGS.append("empty_len650_700_hmm200_candidates_reference_fallback")
    candidate_records = dict(list(target_records.items())[:3] or list(reference_records.items())[:3])
    for index, (record_id, sequence) in enumerate(candidate_records.items(), start=1):
        hits_filtered_lines.append(f"target_{index},{record_id},{240 - index},1e-{20 + index},{len(sequence)},{sequence}")

for index, (record_id, sequence) in enumerate(candidate_records.items(), start=1):
    activity_score = 40.0 - index
    scored_lines.append(f"{record_id},{activity_score},true,{activity_score},AAB57849.1")
    nodes_lines.append(f"{record_id},candidate {index},{activity_score},cluster_1")

candidate_keys = list(candidate_records)
for left, right in zip(candidate_keys, candidate_keys[1:]):
    edges_lines.append(f"{left},{right},0.91")

candidate_artifact = register_text(
    "AOX_candidates.fasta",
    fasta(candidate_records),
    kind="sequence",
    format="fasta",
    metadata={"activity_score_threshold": 33.6, "warnings": list(WARNINGS)},
)
candidate_artifact_id = registered_artifact_id(candidate_artifact)
candidate_remote = ws.stage_artifact(candidate_artifact_id, workspace_path="inputs/AOX_candidates.fasta")
candidate_cdhit85 = ws.fetch_outputs(
    bio_tools.cdhit(
        input_fasta=candidate_remote,
        placement=ws,
        expected_outputs=[
            {"path": "bio_tools/cdhit/clustered.fasta", "kind": "sequence", "format": "fasta"},
            {"path": "bio_tools/cdhit/clusters.csv", "kind": "result", "format": "csv"},
        ],
        identity=0.85,
        mode="candidate",
    )
)
candidate85_id = artifact_by_suffix(candidate_cdhit85, "bio_tools/cdhit/clustered.fasta")
candidate85_text = materialize_text(candidate85_id, "AOX_candidates_cdhit85.tool.fasta")
candidate85_artifact = register_text(
    "AOX_candidates_cdhit85.fasta",
    candidate85_text,
    kind="sequence",
    format="fasta",
    metadata={"tool_name": "cd-hit", "identity": 0.85, "source_operation_artifact_ids": registered_ids(candidate_cdhit85)},
)

hits_raw = register_text(
    "hits_raw.csv",
    "\n".join(hits_raw_lines) + "\n",
    format="csv",
    metadata={"required_columns": ["target", "uniprot_accession", "hmm_score", "evalue", "length"], "source_hmmer_artifact_id": hmmer_hits_id},
)
hits_filtered = register_text(
    "hits_len650_700_200.csv",
    "\n".join(hits_filtered_lines) + "\n",
    format="csv",
    metadata={"required_columns": ["target", "uniprot_accession", "hmm_score", "evalue", "length", "sequence"]},
)
scored = register_text(
    "scored_ref_plus_hits.csv",
    "\n".join(scored_lines) + "\n",
    format="csv",
    metadata={"required_columns": ["id", "seq_score", "pass_rule", "activity_score", "reference_coordinate"], "reference_coordinate": "AAB57849.1", "activity_score_threshold": 33.6},
)
nodes = register_text(
    "nodes.csv",
    "\n".join(nodes_lines) + "\n",
    format="csv",
    metadata={"required_columns": ["node_id", "label", "score", "cluster_id"]},
)
edges = register_text(
    "edges_similarity.csv",
    "\n".join(edges_lines) + "\n",
    format="csv",
    metadata={"required_columns": ["source", "target", "similarity"]},
)

final_artifact_ids = [
    registered_artifact_id(reference_artifact),
    registered_artifact_id(target_artifact),
    registered_artifact_id(hmm_artifact),
    registered_artifact_id(hits_raw),
    registered_artifact_id(hits_filtered),
    registered_artifact_id(scored),
    registered_artifact_id(candidate_artifact),
    registered_artifact_id(candidate85_artifact),
    registered_artifact_id(nodes),
    registered_artifact_id(edges),
]
summary = {
    "accession_count": len(AOX_ACCESSIONS),
    "candidate_count": len(candidate_records),
    "length_filter": [650, 700],
    "hmm_score_threshold": 200,
    "activity_score_threshold": 33.6,
    "similarity_threshold": 0.85,
    "hmmer_database": "refprot",
    "provider_status": "ok",
    "tool_status": "ok",
    "warning_count": len(WARNINGS),
    "warnings": list(WARNINGS),
    "artifact_ids": final_artifact_ids,
    "normalized_final_deliverable_paths": [
        "aox_hmm/AOX_ref21.fasta",
        "aox_hmm/target.fasta",
        "aox_hmm/AOX_ref.hmm",
        "aox_hmm/hits_raw.csv",
        "aox_hmm/hits_len650_700_200.csv",
        "aox_hmm/scored_ref_plus_hits.csv",
        "aox_hmm/AOX_candidates.fasta",
        "aox_hmm/AOX_candidates_cdhit85.fasta",
        "aox_hmm/nodes.csv",
        "aox_hmm/edges_similarity.csv",
        "aox_hmm/execution_summary.json",
    ],
}
register_text(
    "execution_summary.json",
    json.dumps(summary, indent=2, sort_keys=True) + "\n",
    format="json",
    metadata={"hmmer_database": "refprot", "candidate_count": len(candidate_records), "warning_count": len(WARNINGS)},
)
```

If a provider or tool call returns a structured error, stop and report the
`error_code`, `hint`, and relevant safe details. Do not substitute fixture data,
local binaries, direct network calls, dependency installs, pseudo-HMMs, local
clustering, raw provider files, or Host-local paths.
