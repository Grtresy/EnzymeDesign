## ADDED Requirements

### Requirement: External qualification receipts have risk-based freshness and protected storage
Provider receipts MUST expire after 24 hours; Git/LFS, Podman, SSH, Slurm and AlphaFold receipts MUST expire after 7 days; HMMER, Vina, fpocket and preprocessing software receipts MUST expire after 30 days. Exact identity drift, operator revocation or protected-ledger integrity failure MUST invalidate the affected unit immediately. Canonical safe receipts MUST reside in a protected SQLite qualification ledger, while bounded private diagnostics reside in a protected evidence root linked only by `diagnostic_id`.

#### Scenario: Provider endpoint identity drifts before TTL
- **WHEN** the current endpoint or account locator digest differs from the receipt subject
- **THEN** the receipt is invalid immediately and no remaining TTL is honored

#### Scenario: Public receipt export is requested
- **WHEN** an operator exports qualification evidence
- **THEN** the JSON contains safe identities and digests but no credential material, private path, raw stream or traceback

### Requirement: Adoption preserves operation identity and remains explicit
Only an authorized operator adoption step MAY turn an unexpired qualification receipt into a Provider or target resource fact. Adoption MUST bind the exact operation, route, real subject, source, build, configuration, policy and receipt digests and MUST NOT broaden one operation, environment or batch into another; qualification execution itself MUST leave inventories and Session bindings unchanged.

#### Scenario: HMMER target has only hmmbuild evidence
- **WHEN** adoption is requested for both hmmbuild and hmmsearch
- **THEN** only hmmbuild can be adopted and hmmsearch remains blocked

#### Scenario: Qualification completes without adoption authority
- **WHEN** a real receipt is valid but no operator adoption decision exists
- **THEN** the receipt remains stored as qualification evidence and no runtime resource fact changes
