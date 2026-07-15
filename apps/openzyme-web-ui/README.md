# openzyme-web-ui

OpenZyme V3 browser workspace.

## Scope

This directory contains the browser-facing workspace shell for V3 sessions:

- create and select sessions
- conversation-centered master-agent interaction
- task board, lane, teammate, approval, capability, artifact, report, and activity views
- V3 session event stream consumption
- sanitized runtime health and deployment-profile visibility

## Development

- `npm test`
- `npm run build`

The browser consumes V3 Host workspace projections and the stable `openzyme.event`
SSE envelope directly. Browser mutations generate `Idempotency-Key` headers; approval
and lane identities remain server-owned.
