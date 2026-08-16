## ADDED Requirements

### Requirement: Public diagnostic sanitization is deterministic and authority-safe
The system MUST sanitize public diagnostic text and nested scalar payloads
without exposing credentials, authorization values, private locators, Host
paths, encoded private locations, or raw backend diagnostics. For the same input
it MUST produce the same output, and sanitizing its output again MUST be
idempotent. The sanitizer MUST preserve existing stable redaction markers and
MUST NOT recover, infer, or publish private authority.

#### Scenario: Credential-bearing URI is redacted
- **WHEN** a public diagnostic contains a URI with user information, a password, and a host
- **THEN** the complete credential-bearing locator is replaced by the stable private diagnostic marker and no credential or private locator remains

#### Scenario: Repeated sanitization is stable
- **WHEN** a sanitized public diagnostic is passed through the sanitizer again
- **THEN** the second result is byte-for-byte equal to the first result

#### Scenario: Nested public payload uses the same boundary
- **WHEN** strings containing credentials or private locators occur in nested mappings or sequences
- **THEN** every public scalar is sanitized under the same rules while non-sensitive structure and safe scalar values remain deterministic

### Requirement: Credential URI detection has bounded work at accepted scalar scale
Credential-URI detection MUST avoid restarting an unbounded greedy scheme scan
at successive characters of an allowed scalar. The production sanitizer MUST
process the qualification profile's plain 64 KiB scalar within its registered
identity-bound child-process deadline, without input truncation, fallback,
alternate sanitizer, external effect, descendant leak, or deadline widening.
Long mixed content containing a plausible credential URI MUST still redact that
URI, and long benign content MUST remain unchanged when no other sanitization
rule applies.

#### Scenario: Long benign scalar completes unchanged
- **WHEN** the production sanitizer receives the registered plain 64 KiB allowed scalar
- **THEN** it completes within the registered hard deadline and returns the complete scalar unchanged

#### Scenario: Long mixed content retains credential protection
- **WHEN** a long allowed prefix is followed by a delimiter and a credential-bearing URI
- **THEN** the sanitizer completes under the same bounded-work implementation, preserves the benign prefix, and removes the complete credential-bearing URI

#### Scenario: Timeout cannot be hidden by alternate evidence
- **WHEN** the identity-bound sanitizer child misses its registered deadline or is replaced by a non-production implementation
- **THEN** architecture qualification records a violation or invalid evidence and cannot admit the revision
