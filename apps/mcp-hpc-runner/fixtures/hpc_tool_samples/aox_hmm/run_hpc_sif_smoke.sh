#!/usr/bin/env bash
set -euo pipefail

input_dir="${1:-$(pwd)}"
out_dir="${2:-$PWD/out}"

: "${MAFFT_SIF:?Set MAFFT_SIF to the MAFFT SIF path}"
: "${CDHIT_SIF:?Set CDHIT_SIF to the CD-HIT SIF path}"
: "${HMMER_SIF:?Set HMMER_SIF to the HMMER SIF path}"

mkdir -p "$out_dir"

apptainer exec "$MAFFT_SIF" mafft --auto "$input_dir/input_sequences.fasta" \
  > "$out_dir/mafft.aln.fasta"
grep -q '^>' "$out_dir/mafft.aln.fasta"

apptainer exec "$CDHIT_SIF" cd-hit \
  -i "$input_dir/input_sequences.fasta" \
  -o "$out_dir/cdhit_representatives.fasta" \
  -c 0.85 -n 5 -d 0 -T 1 -M 256 \
  > "$out_dir/cdhit.log"
test -s "$out_dir/cdhit_representatives.fasta"
test -s "$out_dir/cdhit_representatives.fasta.clstr"

apptainer exec "$HMMER_SIF" hmmbuild --amino \
  "$out_dir/toy.hmm" "$input_dir/msa.sto" \
  > "$out_dir/hmmbuild.summary.txt"
grep -q '^HMMER3/f' "$out_dir/toy.hmm"

apptainer exec "$HMMER_SIF" hmmalign --amino \
  -o "$out_dir/hmmalign.sto" \
  "$out_dir/toy.hmm" "$input_dir/search_targets.fasta"
grep -q '^# STOCKHOLM 1.0' "$out_dir/hmmalign.sto"

apptainer exec "$HMMER_SIF" hmmsearch \
  --noali \
  -E 1000 --domE 1000 \
  --tblout "$out_dir/hmmsearch.tblout" \
  --domtblout "$out_dir/hmmsearch.domtblout" \
  "$out_dir/toy.hmm" "$input_dir/search_targets.fasta" \
  > "$out_dir/hmmsearch.txt"

test -s "$out_dir/hmmsearch.tblout"
test -s "$out_dir/hmmsearch.domtblout"
awk 'BEGIN { ok = 0 } $0 !~ /^#/ && NF > 0 { ok = 1 } END { exit ok ? 0 : 1 }' \
  "$out_dir/hmmsearch.tblout"

printf 'AOX/HMM bio-tools smoke completed\n'
