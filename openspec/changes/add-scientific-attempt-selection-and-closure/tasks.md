## 1. Canonical attempt and selection model

- [x] 1.1 Add attempt authority/envelope, selection revision, disposition, effect adoption, materialization, and closure domain models with closed enums and invariants
- [x] 1.2 Add database migration, indexes/triggers, repositories, CoreRepositories wiring, and consistency audit coverage

## 2. Authorization and selection services

- [x] 2.1 Implement atomic idempotent envelope admission/consumption with count, MICU/cost/time, effect, target, expiry, and unknown-effect blockers
- [x] 2.2 Implement Host-derived operation universe, immutable/CAS selection revisions, and complete disposition validation
- [x] 2.3 Implement effect adoption validation against controlled-operation identity, result, certainty, approval, workflow role, and same-attempt scope
- [x] 2.4 Implement Host-supervised artifact materialization with catalog grant, digest, target authority, and overwrite checks
- [x] 2.5 Implement selection sealing and attempt closure consuming exact quiescence while leaving task status unchanged

## 3. Product surfaces

- [x] 3.1 Register actor-bound idempotent attempt/selection/disposition/adoption/materialization/closure tools and services
- [x] 3.2 Add Host API, workspace/event projection, CLI/UI read and command surfaces with private authority redaction

## 4. Verification and documentation

- [x] 4.1 Add migration/repository/service tests for concurrency, replay, cross-scope rejection, unknown effect, materialization tamper, CAS, quiescence, and task independence
- [x] 4.2 Sync `docs/OpenZyme架构设计.md` and relevant `docs/v3/` control-plane, engine, interface, runtime, and harness-audit documents
- [x] 4.3 Run focused non-live tests, ruff, diff check, and OpenSpec strict validation
