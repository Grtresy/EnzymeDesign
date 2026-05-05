## Why

The team uses a mixed tool stack on Diannan (system binaries, Spack-managed tools, `/opt/tools` wrappers, and standalone SIF images), but there is no single reference for how each tool should be called. We need a unified manual now so agents and collaborators can execute the enzyme-design workflow consistently without trial-and-error.

## What Changes

- Create a Diannan-focused tool usage manual covering all workflow-relevant tools currently available.
- Standardize command-level calling conventions for each tool, including required inputs, optional parameters, and expected outputs.
- Document invocation patterns for three execution modes: native/Spack tools, `/opt/tools` wrappers, and Apptainer SIF images.
- Define tool selection guidance for each workflow stage (evidence, prompt build, generation, evaluation, update/HITL) and accepted substitutes.
- Add a practical validation section so users can quickly verify whether a tool invocation succeeded and produced the expected artifacts.

## Capabilities

### New Capabilities

- `diannan-tool-catalog`: Provide an authoritative inventory of available server-side tools grouped by workflow stage and deployment mode.
- `tool-command-contracts`: Define per-tool command interfaces with explicit input/output formats and calling requirements.
- `container-tool-invocation`: Document how to run SIF-packaged tools and map host paths, inputs, and outputs consistently.
- `workflow-tool-selection-guide`: Provide replacement mapping and decision rules so users know which tool to call for each workflow function.

### Modified Capabilities

- None.

## Impact

- Adds new change artifacts for a documentation-first capability set under OpenSpec.
- Affects documentation and operational onboarding for Diannan-based agent execution.
- Reduces workflow failures caused by inconsistent tool invocation and unclear I/O contracts.
- Improves repeatability across local (uv-managed Python) and server-side execution paths.
