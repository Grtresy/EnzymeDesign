## ADDED Requirements

### Requirement: Operational selection loads only deployment-adopted qualification admission
After cutover, the EnzymeDesign application composition root MUST derive its external qualification admission from the verified deployment adoption ledger and startup proof. It MUST NOT use installed-package discovery, ambient configuration, mounted-only routes, qualification receipts that were not adopted, or an adjacent operational Adapter. Missing or drifted adoption MUST keep the exact route blocked with no fallback.

#### Scenario: Selected Adapter is mounted but adoption ledger is absent
- **WHEN** the composition root can construct the Adapter runtime but cannot verify deployment adoption
- **THEN** external route admission remains blocked and writer startup cannot claim cutover readiness

