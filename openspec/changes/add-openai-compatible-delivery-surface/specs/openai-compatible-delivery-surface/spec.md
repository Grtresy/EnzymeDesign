## ADDED Requirements

### Requirement: The compatibility surface exposes only the declared L0 public API
The `openzyme.openai-compatible.api` delivery surface MUST expose authenticated `GET /v1/models` and `POST /v1/chat/completions` endpoints with JSON or SSE media types defined by the compatibility contract. It MUST authenticate `Authorization: Bearer <credential>` in constant time before any private Host request, and an absent or invalid credential MUST return HTTP 401 without creating or mutating an OpenZyme Session. The public credential MUST NOT be forwarded to the private Host or accepted as an internal authority credential.

#### Scenario: Probe valid models endpoint
- **WHEN** a caller supplies the configured Bearer credential to `GET /v1/models`
- **THEN** the surface returns HTTP 200 with an OpenAI-style model list and performs no Session or runtime mutation

#### Scenario: Reject an invalid public credential
- **WHEN** a caller supplies a missing or invalid Bearer credential to either public endpoint
- **THEN** the surface returns HTTP 401 with a bounded OpenAI-style error and sends no request to the private Host

### Requirement: Chat completion input is a closed bounded text contract
The chat endpoint MUST accept a non-empty bounded `messages` array whose roles are limited to `system`, `user`, and `assistant` and whose content values are strings. The final executable message MUST be a non-empty `user` message. `stream`, when present, MUST be a JSON boolean. The contract MUST accept `model` when it is absent, null, empty, or a bounded string, and it MUST NOT use the value to select an internal Provider or route. The contract MUST accept `max_tokens` when it is absent or a bounded positive integer compatibility hint, and it MUST NOT use the value to alter deployment-owned runtime bounds or truncate canonical Agent output. The contract MUST accept `sessionId` when it is absent, empty, or a bounded string. Unknown fields and unsupported tool/function, reasoning, multimodal, file, attachment, content-array, or `tool`-role input MUST fail with HTTP 400 before Host mutation rather than being ignored, translated, or downgraded.

#### Scenario: Accept the competition minimal request
- **WHEN** a valid caller posts text messages with `stream=true`, `max_tokens=1`, and an absent or null `model`
- **THEN** the surface accepts the request without using `max_tokens` or `model` to change the OpenZyme Agent, Provider, route, affordance, or runtime-command bounds

#### Scenario: Reject string false for stream
- **WHEN** a request supplies `stream="false"` instead of the JSON boolean `false`
- **THEN** the surface returns HTTP 400 before Session creation, message admission, or runtime-command admission

#### Scenario: Reject function calling in L0
- **WHEN** a request contains `tools`, `functions`, `tool_choice`, a `tool` role, or a non-string content part
- **THEN** the surface returns `unsupported_parameter` and performs no fallback to plain text or internal tool exposure

### Requirement: The advertised model is a compatibility label only
`GET /v1/models` MUST return one deployment-fixed model ID, and successful chat responses MUST echo that fixed ID. The request `model` value MUST NOT override the fixed project, Agent, LLM Provider, capability binding, Driver, target, tool catalog, or approval policy. Model listing MUST NOT disclose internal Provider names, route IDs, credentials, target inventory, or Plugin implementation details.

#### Scenario: Caller requests another model name
- **WHEN** a valid request supplies a model string different from the advertised label
- **THEN** the same fixed EnzymeDesign composition handles the turn and no internal model or route selection changes

### Requirement: External session identity maps deterministically without becoming canonical truth
For a non-empty `sessionId`, the surface MUST derive an opaque internal Session ID using a versioned HMAC-SHA256 input containing the deployment tenant ID, fixed project ID, and exact external session value. The raw external value MUST NOT appear in the internal Session ID, public response, or normal logs. The mapping MUST be stable across process restart while the mapping key and namespace remain unchanged. A missing or empty `sessionId` MUST create a fresh Session per new HTTP request unless the caller supplies a supported external idempotency key. The Host control store MUST remain the sole owner of Session lifecycle and persistence; the surface MUST NOT maintain a second canonical Session database.

#### Scenario: Continue one external conversation after restart
- **WHEN** the surface restarts with the same tenant, project, mapping key, and non-empty `sessionId`
- **THEN** the next request resolves the same opaque internal Session and observes its canonical Host conversation

#### Scenario: Probe without session identity
- **WHEN** a valid request omits `sessionId` and external idempotency identity
- **THEN** the surface creates a fresh internal Session for that request and does not reuse the most recently accessed Session

#### Scenario: Deterministic ID collides with incompatible state
- **WHEN** the derived internal ID already names a Session with another project, owner, release, or incompatible objective
- **THEN** the surface returns a no-fallback conflict and does not adopt or mutate that Session

### Requirement: System messages initialize context but never grant authority
For a new mapped Session, the surface MUST construct the Session objective from a deployment-owned base objective plus explicitly delimited, untrusted initial `system` text. System text MUST NOT replace harness/provider policy, grant authority, resolve an approval, enable a Plugin, select a route, or change runtime bounds. For an existing mapped Session, an omitted system message MUST leave the objective unchanged; a supplied system context MUST canonicalize to the existing objective or fail with `system_context_conflict`. Previous `user` and `assistant` history in the external transcript MUST NOT be inserted as canonical OpenZyme messages.

#### Scenario: Create a Session with system context
- **WHEN** the first request for a non-empty `sessionId` contains bounded system text and a final user message
- **THEN** the system text is retained only as delimited untrusted objective context and the final user text is admitted through the canonical message endpoint

#### Scenario: Attempt to change established system context
- **WHEN** a later request for the same mapped Session supplies different system text
- **THEN** the surface returns HTTP 409 before posting another user message or runtime command

#### Scenario: External assistant history is present
- **WHEN** a later request includes prior assistant strings in its complete compatibility transcript
- **THEN** those strings participate only in transport turn identity and are not persisted as OpenZyme assistant facts

### Requirement: Each semantic turn has one durable message anchor and one bounded runtime command
For each newly admitted semantic turn, the surface MUST post exactly one latest user message through the public Host contract and admit exactly one `runtime.drain` command with deployment-fixed `max_signals`, deployment-fixed `max_steps_per_agent`, and `auto_enqueue_ready_tasks=false`. It MUST derive distinct deterministic Host idempotency keys from a versioned turn identity and MUST reuse the same message anchor and command on an identical retry. It MUST only observe or poll that exact command after admission; it MUST NOT issue a second drain, enlarge bounds, auto-enqueue tasks, choose a route, approve an operation, cancel on disconnect, or infer command success from unrelated workspace changes.

#### Scenario: Execute a new compatibility turn
- **WHEN** a valid new turn reaches a ready mapped Session with no pending approval
- **THEN** exactly one user message and one bounded runtime command are admitted and the command has `auto_enqueue_ready_tasks=false`

#### Scenario: Retry after response loss
- **WHEN** the caller repeats the same complete transcript after the surface loses the HTTP response
- **THEN** the surface retrieves the same idempotent message anchor and runtime command and performs no duplicate message or drain admission

#### Scenario: Runtime command finishes
- **WHEN** the one bounded runtime command reaches a completed status
- **THEN** the surface treats only that command as terminal and does not mark any Task, scientific attempt, publication, report, or Session complete

### Requirement: Per-Session compatibility turns are serialized and bounded
The first release MUST run as one declared surface instance and MUST permit at most one distinct active compatibility turn per internal Session. A concurrent different turn MUST fail before Host mutation with `session_busy`; a retry with the same turn identity MUST be allowed to observe the existing command. The surface MUST enforce closed request bytes, message count/content bytes, identifier lengths, global active-turn count, per-Session active-turn count, poll interval, command deadline, keepalive interval, and output-byte limits. Exceeding a bound MUST return a bounded `400`, `413`, or `429` error and MUST NOT truncate intent or fall back to a stateless answer.

#### Scenario: Two different turns race on one Session
- **WHEN** a second distinct request reaches a Session whose first compatibility turn is still active
- **THEN** the second request receives `session_busy` before a message or command is admitted

#### Scenario: Request exceeds content budget
- **WHEN** the request body or aggregate message content exceeds the configured hard bound
- **THEN** the surface rejects it before Session, message, runtime, Provider, or external-effect mutation

### Requirement: Assistant content comes only from the verified public conversation projection
The surface MUST take the idempotent user `message_id` as the response anchor and read assistant conversation entries only through the exact verified `file_workspace_public@2` projection. The response segment MUST contain assistant entries after that anchor and before the next user entry in canonical order; multiple entries MUST be joined with exactly two newline characters. The surface MUST NOT read repository objects, engine documents, private runtime outputs, traces, tool results, or Host implementation memory. A completed command with no associated assistant entry MUST fail as `openzyme_no_assistant_output` rather than fabricate a success response.

#### Scenario: One assistant entry follows the anchor
- **WHEN** the bounded command completes and one projected assistant entry appears after the anchored user message
- **THEN** the exact entry content becomes the compatibility response content

#### Scenario: Multiple assistant entries follow the anchor
- **WHEN** two ordered assistant entries appear before any next user message
- **THEN** the surface joins them in canonical order with `\n\n` and does not select one heuristically

#### Scenario: Command reports completed without output
- **WHEN** the exact command is terminal completed but the verified anchor segment has no assistant entry and no pending approval
- **THEN** the surface returns `openzyme_no_assistant_output` and no placeholder assistant text

### Requirement: Non-streaming responses conform to the L0 completion shape
A successful non-streaming response MUST use object `chat.completion`, a stable `chatcmpl-*` ID derived from the turn identity, Unix-second `created`, exactly one choice at index zero, an assistant string, and an allowed `finish_reason`. The first release MUST use `finish_reason="stop"` for successful bounded output. Because no verified token accounting crosses the public Host contract, `prompt_tokens`, `completion_tokens`, and `total_tokens` MUST each be zero and MUST NOT be estimated from characters.

#### Scenario: Return a successful non-streaming completion
- **WHEN** `stream=false` and the exact turn yields associated assistant content
- **THEN** the surface returns HTTP 200 with `choices[0].message.content`, `finish_reason="stop"`, and a zero-valued usage object

### Requirement: Streaming responses follow the required SSE frame lifecycle
For `stream=true`, the surface MUST complete authentication, request validation, Session/message admission, and exact runtime-command admission before opening a successful SSE response. It MUST emit exactly one assistant role data frame first, zero or more UTF-8-safe content frames after associated output is available, exactly one stop data frame with empty delta, `finish_reason="stop"`, and zero usage, followed by exactly `data: [DONE]`. If the surface emits bounded SSE comments to keep the connection alive, those comments MUST NOT alter data-frame order. The surface MUST describe this as command-lifecycle buffered compatibility streaming and MUST NOT claim Provider token streaming.

#### Scenario: Stream a successful completion
- **WHEN** a valid streaming turn produces assistant content
- **THEN** the client receives role, content, stop, and `[DONE]` data frames in that order with no duplicate terminal frame

#### Scenario: Probe receives an early frame
- **WHEN** the runtime command has been admitted but assistant content is not yet terminal
- **THEN** the surface may emit the single role frame and bounded keepalive comments without emitting fabricated content or completion

#### Scenario: Failure after streaming starts
- **WHEN** the command fails, times out, waits for approval, or yields no output after the SSE role frame was sent
- **THEN** the surface emits one safe error-bearing stop frame with `finish_reason="stop"`, then `[DONE]`, and does not encode `error` as a finish reason

### Requirement: Approval remains an out-of-band native OpenZyme operation
If a Session already has pending approval, the surface MUST reject a new compatibility turn before posting its user message. If the admitted runtime command becomes suspended for approval, the surface MUST return `openzyme_approval_required` as non-streaming JSON or as the defined post-header SSE error. It MUST NOT interpret any user or assistant chat text as approval, call the approval-resolution endpoint, grant scientific authorization, or automatically drain a continuation. Approval resolution and explicit continuation drain MUST occur only through an authorized native operator surface. Retrying the same compatibility turn MUST reuse its original message/command identity and MUST return any assistant content later associated with the same anchor.

#### Scenario: User types approval language
- **WHEN** a mapped Session has pending approval and the external user sends text such as "approve" or "yes"
- **THEN** the surface reports approval required before message admission and the durable Approval remains pending

#### Scenario: Operator completes an approved continuation
- **WHEN** an authorized native operator resolves the approval and explicitly advances the continuation, producing assistant content after the original anchor
- **THEN** a retry of the original compatibility turn reads that content without creating another surface-owned drain

### Requirement: Failure, timeout, and disconnect preserve canonical effect certainty
Before SSE starts, failures MUST use a bounded OpenAI-style JSON envelope with `error.message`, `error.type`, `error.param`, and `error.code`. The mapping MUST distinguish authentication/validation, Session conflict/busy/approval, runtime locked, upstream failed, no output, and timeout. A timeout, transport loss, still-running command, or client disconnect MUST NOT be reported as no effect, MUST NOT cancel or redispatch the Host command, and MUST direct an identical retry to observe the same turn identity. Private diagnostics MUST record stable code, component, phase, safe identities, mutation/fallback facts, effect certainty, retry/reconcile policy, cause chain, and `diagnostic_id`; public output and logs MUST exclude secrets, raw external session IDs, full prompts, Host paths, private URLs, traceback, storage/runner locators, and backend output.

#### Scenario: HTTP deadline expires while command is running
- **WHEN** the exact runtime command remains accepted or claimed at the compatibility deadline
- **THEN** the surface returns or streams `openzyme_runtime_timeout`, leaves the command untouched, and does not submit a replacement command

#### Scenario: Streaming client disconnects
- **WHEN** a caller closes the SSE connection after command admission
- **THEN** the surface stops serializing that connection but neither cancels nor retries the canonical Host command

#### Scenario: Private Host error contains sensitive context
- **WHEN** a Host or transport failure has a traceback, token, path, URL, or backend output in its private cause
- **THEN** the public OpenAI-style error contains only bounded safe fields and links to the protected record by `diagnostic_id`

### Requirement: Readiness proves the exact private dependency without mutating it
The surface MUST be ready only when its external authentication configuration, separate Host credential, Session mapping key, fixed tenant/project, bounds, exact surface contract digest, private Host reachability, Host/client public contract, and active Distribution release are compatible. Readiness and model-list probing MUST perform no Session, message, runtime, approval, task, workspace, Provider, or external-effect mutation. A structurally installed but unverified surface MUST remain not ready and MUST NOT advertise a usable model.

#### Scenario: Host release does not match the selected Distribution
- **WHEN** the private Host reports a release or public-contract digest different from the surface configuration
- **THEN** readiness fails closed and `/v1/models` does not claim the deployment is usable

#### Scenario: Readiness succeeds
- **WHEN** all secret presence, fixed-scope, reachability, contract, release, and bound checks pass
- **THEN** readiness reports the exact surface as ready without creating a Session or starting runtime work
