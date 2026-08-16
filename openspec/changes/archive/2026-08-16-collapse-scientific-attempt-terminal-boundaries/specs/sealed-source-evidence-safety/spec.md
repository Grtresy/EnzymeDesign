# sealed-source-evidence-safety

## ADDED Requirements

### Requirement: Sealed source preserves exact public bytes without interpreting language syntax
Source-evidence publication MUST preserve exact declared source bytes and bind
them to canonical digests. Safety validation MUST reject actual secret-like
material, explicit private roots, private backend locators, private URLs,
manifest path escape, undeclared files, and digest mismatch. It MUST NOT
interpret an arbitrary absolute-Unix-looking token as a Host path merely
because the token appears in program syntax.

#### Scenario: Portable shebang is sealed
- **WHEN** a declared source file begins with `#!/usr/bin/env python3` and contains no secret, private locator, private root, path escape, or digest mismatch
- **THEN** publication preserves the exact bytes and accepts the file

#### Scenario: Private root appears in source
- **WHEN** source contains an explicit location under `/home`, `/root`, `/tmp`, `/scratch`, `/cluster`, `/gpfs`, `/lustre`, `/mnt`, `/private`, a private Windows root, or an UNC location
- **THEN** safety validation rejects publication with a typed private-location reason

#### Scenario: Encoded private root appears
- **WHEN** source contains a supported encoded representation of an explicit private root
- **THEN** safety validation rejects publication rather than treating encoding as sanitization

#### Scenario: Secret or private URL appears
- **WHEN** source contains secret-like material, a private backend locator, a private URL, or unsafe URL query material
- **THEN** safety validation rejects publication

#### Scenario: Manifest identity differs
- **WHEN** a declared path escapes its root, an undeclared file is present, bytes differ, or a digest does not match
- **THEN** evidence sealing fails closed without repairing or normalizing the source tree

### Requirement: Attestation state is distinct from operation state
Evidence projection MUST represent operation/check execution status separately
from later attestation status. A failed or unavailable attestation MUST make the
overall evidence non-eligible but MUST NOT mutate a previously established
completed operation or passed check into a failed execution.

#### Scenario: Probe passes before attestation failure
- **WHEN** all probe checks passed and a later source or evidence attestation fails
- **THEN** each check remains `passed`, attestation is recorded as failed or unavailable, and the bundle is non-eligible

#### Scenario: Probe did not run
- **WHEN** no operation record establishes a probe check result
- **THEN** projection records the check as unobserved rather than claiming either success or an attestation-induced execution failure
