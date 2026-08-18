# V3 Failure Recovery 与 Scientific Attempts

## Failure 不是单一状态

系统分别记录 occurrence、cause/hypothesis、effect certainty、retry eligibility、recovery disposition 和
terminal proof。一个异常可以阻断当前 observation，但不能自动说明 task、attempt 或 external effect 的终态。

## Effect certainty

- `no_effect`：证明外部动作未发生，可在同 phase/identity 下进行有界恢复；
- `effect_known` / `terminal_known`：有 durable receipt 支持已知结果；
- `dispatch_in_doubt`：动作可能已发生，只能 reconcile，禁止 replay；
- unknown：证据不足，保持 blocked。

timeout、missing response、process exit 或 stale lease 不得提升 certainty。

## Recovery

recovery disposition 必须绑定 exact occurrence、owner、phase、operation digest、fence 和理由。允许的动作由
machine contract 限定，但 agent 决定何时检查、如何解释和是否请求新的用户授权。不能用“换 backend/参数”
绕开原 approval 或未知 effect。

## Scientific attempt

formal attempt 由显式 admission/authorization 创建，绑定 campaign、task、workflow/root、scope、budget 和
source identity。attempt 内的 operation universe 不从成功文件反推。

selection lifecycle：

1. `scientific.selection.begin` 固定当前 occurrence universe；
2. 每个 operation 写显式 disposition；
3. 成功 producer effect 通过 adoption 绑定 workflow role；
4. seal selection，拒绝 missing/duplicate/unknown occurrence；
5. finalization 从 immutable published revision 验证 scientific files；
6. attempt close 绑定 selection、adoptions、deliverable receipt、quiescence 和 authority consumption。

attempt close、report publish、task finish 和 master response delivery 仍是独立事实。

## Scientific files

`ScientificDeliverableRef` 绑定 publication、commit/tree/path、Git blob/LFS identity、content digest/size、
role、format contract 和 producer adoption。finalization fresh-read bytes，验证完整 bundle 后原子写 refs、bundle
和 receipt。

空结果必须是安装的 deterministic calculation 产生的 typed zero receipt，并有明确 empty reason、contract/
implementation digest 和 output digest。未知、缺文件或 provider failure 不是 scientific negative。

## Historical non-adoption

离线迁移生成的 `refs/openzyme/history/*` 和 mapping 永远
`historical_import_non_adoptable`。它们可供审计/verifier 读取，但不能满足 current scientific admission、
effect adoption、deliverable、report claim、task evidence 或 canonical GO/NO-GO。

AOX/HMM 历史 campaign 和旧 cutover receipt 同样不可回填。新的 formal attempt 必须从 current code、workflow
contract、public API、machine authority 和 source-bound evidence 重新建立。

## Fail-closed matrix

以下情况保持 blocked：unknown effect、unsettled occurrence、selection universe drift、producer/result mismatch、
publication/path/LFS drift、format failure、missing adoption、stale authority、quiescence mismatch 或 historical ref。
不存在 automatic negative、best-effort close、manual override 或 hidden fallback。

行为验收必须 fresh-read publication bytes，覆盖 unknown publication、path/blob/LFS drift、role/adoption
mismatch、bundle tamper 和 artifact-era request field rejection。AOX finalizer 测试只能证明 file-native
finalization composition；non-live fixture 不证明真实 provider/HPC 可用，也不授权新 campaign。
