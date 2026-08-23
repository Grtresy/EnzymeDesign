# Scientific qualification fixtures

These compressed, base64-encoded fixtures are immutable inputs for bounded real-program qualification only.

- `fpocket-1uyd.pdb.gz.b64` is fpocket's commit-pinned 1UYD installation smoke
  fixture (`sha256:923e978e1d570f854d0d5f96d515f70d6fdac25216de586fe8c97a266e803b0c`).
  Upstream documents this exact structure as the build-verification input expected
  to produce a non-empty pocket-info file.
- `vina-receptor.pdbqt.gz.b64` and `vina-ligand.pdbqt.gz.b64` are the repository's existing Vina integration fixtures.

The qualification runtime decodes them in memory, binds their exact content digest into the source-bound workload, and never resolves a path outside the installed Distribution wheel.
