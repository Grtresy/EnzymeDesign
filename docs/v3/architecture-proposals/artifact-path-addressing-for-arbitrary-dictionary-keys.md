# Artifact Path Addressing For Arbitrary Dictionary Keys

Status: proposal only; not implemented by the current artifact-list bounding change.

## Problem

The current `artifact.get(path=...)` resolver splits a dot-delimited string and
uses each segment as either a dictionary key or list index. This is compact for
ordinary control-plane keys such as `artifact.metadata.accessions`, but it
cannot represent a literal dictionary key containing `.`, an empty key, or a
key whose text would otherwise be interpreted as path syntax.

Generating `artifact.metadata.lookup.key.with.dot` for a literal
`"key.with.dot"` is incorrect: the resolver interprets three nested keys and
returns `path does not exist`. Escaping ad hoc in a display string would make
the ambiguity worse and could create inconsistent behavior across Python,
browser, CLI, and future SDK consumers.

The current tactical behavior is therefore fail-closed:

- safe `[A-Za-z0-9_-]+` keys may receive an exact child path;
- every other key is reported with `exact_path_available=false` and a
  `root_only` hint for paging the parent dictionary;
- no current response claims that the unsupported key can be read exactly.

## Goals

- Address every JSON object key without ambiguity, including dots, spaces,
  slashes, empty strings, Unicode, and digit-only keys.
- Keep list indices distinct from object keys.
- Preserve session scoping, private-field sanitization, response budgets, and
  existing artifact authorization checks.
- Make hints machine-executable rather than prose that an agent must repair.
- Provide one canonical representation shared by Host API, CLI, browser, and
  agent tool adapters.

## Non-goals

- This proposal does not expose Host paths or raw storage URIs.
- It does not make arbitrary artifact file contents JSON-addressable.
- It does not alter immutable artifact identity, sealing, or provenance.
- It does not implement the new addressing form in the current cutover goal.

## Recommended Contract

Add a structured `path_segments` input alongside the legacy `path` string:

```json
{
  "artifact_id": "art_example",
  "path_segments": [
    {"kind": "key", "value": "artifact"},
    {"kind": "key", "value": "metadata"},
    {"kind": "key", "value": "lookup"},
    {"kind": "key", "value": "key.with.dot"}
  ],
  "offset": 0,
  "limit": 30
}
```

Each segment is tagged:

- `{"kind":"key","value":"..."}` selects an exact dictionary key;
- `{"kind":"index","value":0}` selects a list index.

The Host must reject calls that provide both `path` and `path_segments`, reject
unknown segment kinds, and validate index bounds without coercing a key into an
index. Returned hints should contain structured `read_request` data using
`path_segments`; a human-readable command may be derived from that structure
but must not be the source of truth.

JSON Pointer was considered, but tagged segments are preferred because they do
not require every client and model adapter to implement identical `~0`/`~1`
escaping and because they preserve the key-versus-index distinction directly.

## Compatibility And Migration

1. Keep the existing dot `path` resolver for safe legacy paths.
2. Add `path_segments` as an additive input and emit it for arbitrary keys.
3. During migration, emit both forms only when the dot form is provably exact.
4. Add telemetry for legacy path use and malformed mixed-form requests.
5. Retire any ambiguous generated dot paths after internal and external caller
   audit; do not silently reinterpret an old string under new escaping rules.

## Security And Budget Rules

- Authorization and private-field sanitization occur before resolution.
- A structured path never bypasses `PRIVATE_ARTIFACT_KEYS` filtering.
- Keys in summaries remain bounded; very large key text is represented by
  length/digest until an authorized structured read request is made.
- Dict pages, string pages, and final tool output retain their existing hard
  response budgets.
- Missing keys and type mismatches return structured errors; the Host must not
  guess a nearby key or rewrite the path.

## Acceptance Criteria

- Round-trip tests cover `.`, `/`, spaces, empty keys, Unicode, numeric-looking
  keys, and keys containing JSON Pointer escape characters.
- `"0"` as a dictionary key is observably different from list index `0`.
- Every emitted exact hint dispatches successfully against the same immutable
  artifact and returns the intended value.
- Cross-session artifact access remains rejected.
- All private-key fixtures remain absent from exact and parent-page responses.
- Pagination and the 100,000-character `artifact.list` budget remain
  deterministic under arbitrary key text.
- Browser, CLI, and agent tool schemas use the same structured contract.
