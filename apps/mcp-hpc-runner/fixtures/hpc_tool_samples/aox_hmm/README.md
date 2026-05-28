# AOX/HMM Bio Tools Smoke Fixtures

Small synthetic protein inputs for validating AOX/HMM `bio_tools.*` HPC routes.
These files are only smoke-test fixtures; they are not production databases and
must not be used as scientific evidence.

## Files

- `input_sequences.fasta`: short protein FASTA for MAFFT and CD-HIT smoke.
- `msa.sto`: Stockholm MSA for `hmmbuild` smoke.
- `search_targets.fasta`: tiny FASTA target set for `hmmalign` and local
  `hmmsearch` smoke.
- `run_hpc_sif_smoke.sh`: portable command script. It expects SIF paths through
  environment variables rather than hard-coding remote private paths.

## Required Environment

```bash
export MAFFT_SIF=/path/to/mafft.sif
export CDHIT_SIF=/path/to/cd-hit.sif
export HMMER_SIF=/path/to/hmmer.sif
```

## Expected Outputs

The smoke script writes these files under the output directory:

- `mafft.aln.fasta`
- `cdhit_representatives.fasta`
- `cdhit_representatives.fasta.clstr`
- `toy.hmm`
- `hmmbuild.summary.txt`
- `hmmalign.sto`
- `hmmsearch.txt`
- `hmmsearch.tblout`
- `hmmsearch.domtblout`

Success checks are intentionally minimal: output files must exist, be non-empty,
and contain format markers or at least one non-comment HMMER table row.
