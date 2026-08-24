# Operator evidence

## Active generation

- qualification source commit：`bb6af997c369dd03d4d637ca27c284d9006447fd`
- deployment source commit：`7c71dd65ff29bd463362b3f935510d032beef8c8`
- deployment source identity：`sha256:4ff0f73ec714aa9dd42a38fbde84d4fade56b26ee825c96bd5548dae5988c8c5`
- qualified owner closure：qualification/deployment 均为
  `sha256:28a6678f126f902a4bf42f9b7a9b91aa06dc12e70173ba6d64ed9e43fd1d83e3`
- plan：`sha256:0fb4b0ec47f04f8c9d2040f0fda871c9a6d767d9fba57dd99fb5bf134fee09dc`
- authority：`sha256:20df09c3fd666979726f0f2380c627348b80db21e0f967c8d2ba82a95754249b`
- adoption ledger：`sha256:330aac79c88b2a2444a0ce9e9bc461261170458f2d6aaa36f6bbc1d0b8232978`
- startup proof：`sha256:df9ba168e4130272ec71968a92e28a0f4c8287c5d043a0b6b95e540ac9cda8f1`
- cutover receipt：`sha256:16dde1c92a9565af3076f999f316caa1ce7be1744b1b98f81ce9ba907dada1f8`
- activation：`active`
- adopted facts：44
- AlphaFold：`deferred_optional_profile_capacity_unavailable`，未资格、未采用、未 cutover、未广告
- fallback/retry/dual-write：均为 false/0/false

受保护状态位于 operator 已批准的
`/home/grtresy/.local/state/openzyme/deployments/enzymedesign-qualified-runtime`。root、`backups/`、`attempts/`
及 generation 目录均为当前 uid 的 `0700`，全部 evidence/backup 文件为 `0600`。六类 backup manifest digest 为
`sha256:7e9839bd4271bd0ad5e871adc8b24c2062192e5c75e2845a6ebdcdd7d732681c`。

## Post-cutover first live

- smoke plan：`sha256:46eed4fa023bace272250ccbd18dd078d59a57b5d9fd617cda7e3cefb76dcee7`
- smoke authority：`sha256:2df535d3a2e63816e440053537e85c0027f6f91dcdb68e7f386d67aac20aa6c5`
- route：`enzymedesign.bio-provider-http.uniprot.read@1`
- subject：`provider.uniprot.public`
- occurrence：`occurrence.smoke.enzymedesign.uniprot.batch-1`
- backend receipt：`sha256:9d94d23b3be73f492530512bb39c072c3c42796133b203fcdda0b83d3d16e8fe`
- smoke receipt：`sha256:4b22263c6bbd7e14038c81b31d5cf11972a4b8f2b0c6fdd956eea04b8e3d5b75`
- first-live receipt：`sha256:be3600d0ea7460c146ca6714dca37475bc4304a570d61bbdd36a930ec29eca90`
- effect certainty：`terminal_known`
- retry/fallback：0/false
- monitoring：`healthy`，`cleanup_required=false`

重新调用 cutover executor 与 smoke executor 均恢复相同 terminal receipt，没有再次派发 live effect。

## Preserved failed generations

首次 plan `sha256:4b502555e745ad0a0fd8d894a4c52df05d9e6573882454ef67c9a664c9754b2b`
因 receipt canonical ordering 比较缺陷在零 deployment effect 时停止；plan 与 authority 已完整封存，supersession receipt 为
`sha256:f4114449b8d2717cd9fe75e43ad98367922a20aa7a35ce8e03aeed6c6cfe8725`。

第二 generation plan `sha256:b7f1b2a4a2803bf4a6f96832acf0fd86604f8d2186ea8a21459e6254d4f13d39`
完成 backup/adoption/pending activation 后，在 startup readback 发现“唯一延期 AlphaFold blocker”被错误当作 Batch 1
缺失。它在 first-live 前按 exact activation digest 回滚，rollback receipt 为
`sha256:d9b530c8cbbed6725e264a10c702e2e0491260a275eb2b335f1bc9d94c5c6add`，全部 generation evidence 与 backups
随后封存；没有 live effect、fallback 或证据覆盖。

## Final validation and local seal

按 operator 决策，`./scripts/check-mainline.sh` 在 Goal 收口时只执行一次，没有为制造第二张 receipt 而重跑。该唯一一次
authoritative receipt 为 `sha256:6c159e6a218794a6fd37ece5e693d4fd8e7e553cf3ec35c150ffa9bdbe2238af`，
evidence root 为 `/tmp/openzyme-mainline-authoritative.H56EUg/evidence`，terminal status 为 `fail`。134-unit test gate
和 45-unit non-live readiness 已通过；premerge architecture qualification 当时仅有
`operator-retirement.component-wheel-closure` 与
`authority-composition.source-document-owner-closure` 失败。报告同时如实记录 source tree 非 clean：本 change 尚未归档提交，
并存在 operator 自有、未纳入本 change 的 `.env.test.example` 删除。

根因是默认 LLM/Tavily Provider 依赖未列入 profile 外部分发白名单，以及对应 source-bound component/document digest
尚未随闭包更新。修复提交 `9276294` 加入 `langchain`、`langchain-openai`、`tavily-python`，更新精确 profile 断言和
可重算 source/document baseline；未放宽 component、import、owner、catalog 或 no-live 规则。修复后验证结果：

- `scripts/check-openzyme-architecture.py`：通过，37 components、116 import edges，component inventory digest
  `sha256:409140db5015b7560d42057f08c1f9901cb3e4c5464ea6fe41c7b6ab50717ede`；
- architecture manifest/inventory focused tests：12 passed；
- wheel qualification profile tests：3 passed；
- 原始两个 architecture qualification scenario：2 passed；其中 wheel scenario 在非沙箱环境只读使用既有 uv cache，
  无网络、live Provider、HPC 或产品状态 mutation；
- 本 change 与同步后的六项规格均已 strict validation；全仓 `openspec validate --all --strict` 的唯一剩余失败是本 change
  之外、既存的 `mcp-enzyme-design-knowledge` 缺少 Purpose/Requirements。

本 change 已同步 main specs 并归档为 `2026-08-24-cut-over-enzymedesign-qualified-runtime`。所有提交仅位于本地
`dev`，未 push；`.env.test.example` 的 operator 改动未暂存、未恢复、未提交。唯一 mainline receipt 保持原始 fail
裁决，不将后续 focused verification 冒充为第二次 mainline green receipt。
