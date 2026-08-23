# Scientific qualification fixtures

These compressed, base64-encoded fixtures are immutable inputs for bounded real-program qualification only.

- `fpocket-1crn.pdb.gz.b64` is the repository's existing 1CRN fpocket integration fixture.
- `vina-receptor.pdbqt.gz.b64` and `vina-ligand.pdbqt.gz.b64` are the repository's existing Vina integration fixtures.

The qualification runtime decodes them in memory, binds their exact content digest into the source-bound workload, and never resolves a path outside the installed Distribution wheel.
