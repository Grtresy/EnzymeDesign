# Deferred: reproducible sandbox scientific-dependency manifest and build

Status: proposed; not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Pipeline sandbox image builder 在临时 Containerfile 中使用：

```dockerfile
FROM python:3.12-slim
COPY openzyme_pipeline /tmp/openzyme_pipeline
RUN pip install --no-cache-dir /tmp/openzyme_pipeline
```

这能得到一个 Podman immutable image digest，live preflight 也会把该 digest、Pipeline SDK source
tree digest 和 sandbox protocol identity 绑定进 campaign。它能证明“本次 campaign 实际选择了哪份
image bytes”，却不能从仓库工件重复构建同一依赖环境：base tag 可移动，Python patch/ABI 和 OS
userspace未固定；PEP 517 build isolation及 dependency resolution可以联网；wheel/sdist/build backend
来源与 hash没有形成闭集；runtime health也没有 dependency manifest、SBOM 或 backend capability map。

AOX similarity 引入有 C backend 的科学依赖后，这个缺口会直接影响 implementation identity。
`biopython==1.87` 与 `numpy==2.4.4` 的 direct version pin比范围依赖严格，但仅凭版本字符串不能证明
下载的是哪一个wheel、针对哪个Python ABI/platform、由哪份base libc执行，也不能证明未来 online
build仍得到同一artifact graph。

当前 Goal 只允许有界收口：

- exact direct dependency pin；
- runtime package version、selected algorithm/backend、numeric unit和行为 assertions；
- Pipeline source/implementation digest；
- 当前实际构建出的 immutable final sandbox image digest，并在 campaign launch/runtime health 中
  精确比较。

这些约束使 fresh live attempt 对 **实际 image** fail closed，但不声称构建可重现、供应链已
attested 或 dependency graph已由offline hash closure证明。本提案定义完整终态；当前 Goal 不实施
base-image迁移、wheelhouse、offline `require-hashes`、SBOM/attestation或campaign schema扩张。

## Current evidence and failure mode

1. `FROM python:3.12-slim` 是mutable tag。不同日期、registry mirror或architecture可以得到不同
   base image、Python patch、OpenSSL、glibc和system library bytes。
2. `pip install /tmp/openzyme_pipeline` 默认使用build isolation。即使project只有一个direct
   scientific dependency，pip仍可能在线解析/下载build backend、transitive dependency、wheel或
   sdist。
3. `packages/openzyme-pipeline/pyproject.toml`与workspace `uv.lock`是开发环境工件；当前 image builder
   没有把一个platform-specific frozen lock或wheel hashes复制进build context并offline验证。
4. source package被复制后现场build/install；wheel metadata、build timestamp、file ordering、pyc和
   OCI layer metadata没有统一reproducibility policy。
5. runtime identity当前只有configured/immutable image ref、image digest、Pipeline SDK digest和
   protocol version。它没有Python implementation/version/ABI、platform tag、dependency manifest
   digest、SBOM digest或namespaced scientific backend capability。
6. image digest相同足以在一个pinned campaign内拒绝drift，但无法回答：哪些wheel进入image、为何
   选择该platform artifact、能否在air-gapped builder重建、dependency是否被替换。
7. package `__version__` assertion只能发现部分runtime drift；两个不同wheel可以报告同一version，
   同一wheel在不同ABI/libc下也可能具有不同行为。
8. 允许agent在sandbox内`pip install`会绕过image pin、引入network/supply-chain effect并改变
   implementation bytes，因此不是兼容方案。
9. 当前真实 Podman 校准实际观察到 Python `3.12.13`、direct-pinned Biopython `1.87` 与
   direct-pinned NumPy `2.4.4`。Python patch/base、两个distribution wheel、ABI/platform 与其
   artifact hashes并未由current image builder的仓库工件闭合。该环境的最终image digest可供
   本campaign精确比较，但这组运行时版本 observation不能反向构成可重现build manifest。
10. 独立reference validation 使用 NumPy `2.4.6`，cutover runtime exact pin 为 `2.4.4`。最终
    qualification 不把 `2.4.6` 加入runtime allowlist，也不允许缺包、wrong wheel或version
    mismatch时fallback。
11. 最终 comparison receipt
    `sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e`
    在 immutable image
    `sha256:a581e59d462556186f4cb7cd98587d17307159af58135155596ca54e6c6a7eb2`
    内完成两次独立 cutover NumPy `2.4.4` full-set run，raw outputs 相同，且只规范化
    calculation/implementation pins 与 pin-induced manifest closure 后等于 old pure-v3 输出。
    Biopython/NumPy distribution-record digests分别为
    `sha256:df12d09072ff0f4e999cf22864183a3e12fac0337200a5af916535c00cc64873` /
    `sha256:8c29c383eeb00847bde76cfc46c4e1a112c9f070d897fddaec3c6b4fb4436123`。
    这不是direct full-set NumPy `2.4.6`/`2.4.4` patch A/B，也不是hash-closed reproducible
    build；ordinary `/tmp` receipt只完成当前diagnostic/reviewer gate。

## Agent-harness principles

- agent看到的是已安装、namespaced、versioned的scientific backend capability，不负责选择index、
  wheel、ABI、base image或build tool。
- Host把真实runtime/dependency约束作为facts呈现；缺失或漂移时fail closed，不建议agent现场安装、
  改import或切换“能跑”的库。
- calculation contract、implementation source、dependency environment和final image是不同identity，
  必须分别绑定，不能用一个image digest掩盖所有语义。
- build必须可在无网络环境从verified input closure完成；download/fetch与image build是两个独立、
  可审计阶段。
- dependency hash证明artifact bytes，不证明publisher可信或代码安全；SBOM列清单，不替代签名、
  provenance review、vulnerability policy或科学等价验证。
- generic sandbox不应因一个AOX backend无边界地增加所有scientific packages。capability必须
  namespace/version化，并由workflow显式选择。

## Scope and adjacent identities

本提案回答 **which exact runtime and dependency bytes**：

- calculation contract/implementation registry定义算法、callable和implementation digest；
- 本提案定义base/Python/platform/dependency/build manifest及backend capability；
- [calculation placement proposal](host-authoritative-scientific-calculation-placement-and-sandbox-resource-class.md)
  选择一个已注册runtime/resource class，不拥有dependency resolution；
- HPC SIF/toolchain仍由runner-owned manifest与runtime attestation管理，不因sandbox manifest自动覆盖；
- existing sandbox image registry继续保存immutable image identity，但将来必须引用本提案的manifest
  closure。

## Target invariants

1. 每个cutover-grade sandbox image都从immutable OCI base digest构建；mutable tag只能作human alias，
   不能成为build input或runtime authority。
2. manifest显式绑定Python implementation、full version、ABI、platform/architecture、libc/runtime tags。
3. 所有Python distribution与build tool都有exact version和cryptographic artifact hash；没有unhashed
   transitive dependency、unbounded range或隐式extra。
4. resolve/fetch阶段生成verified wheelhouse；image build阶段 `--network=none`，只消费该wheelhouse。
5. runtime installation使用frozen/offline/require-hashes语义；缺wheel、hash drift、sdist fallback、
   incompatible tag或index access全部fail closed。
6. source distributions若不可避免，必须在独立network-isolated builder用pinned build environment
   先产生reproducible wheel；runtime image不现场build sdist。
7. canonical dependency manifest、SBOM、build recipe和attestation都绑定相同input closure和final
   image/content graph digest。
8. scientific backend capability是namespaced immutable record，绑定package artifact、adapter/
   algorithm、numeric assertions、supported calculation implementations和runtime manifest。
9. runtime health从实际running image重建safe identity并与registry完全相等；不能只回显operator
   declaration。
10. workflow/campaign pin选中的backend capability、dependency manifest、image和SDK identity必须一致；
    mixed dependency epochs不能聚合GO。
11. historical images/attempt按原identity只读验证，不原位生成SBOM或补写provenance authority。
12. build/install/runtime均不暴露index credential、registry token、Host cache path或private locator。

## Proposed artifact model

### `sandbox_scientific_dependency_manifest@1`

closed canonical manifest至少包含：

- `schema_id`, manifest id/digest, created policy epoch；
- OCI base repository logical id、exact manifest/config/layer digests；
- OS name/version、architecture、platform triple、libc/runtime identity；
- Python implementation、full version、SOABI、cache tag、supported wheel tags digest；
- Pipeline SDK project/version/source tree/wheel digest；
- lock format/tool/version、lock bytes digest、selected groups/extras/markers；
- canonical hash-locked requirements/export digest；
- sorted wheelhouse records；
- pinned build toolchain records；
- install order/command semantic digest；
- namespaced backend capability refs；
- SBOM format/content digest；
- build recipe/context/reproducibility policy digest；
- final OCI image/content graph digest；
- public-safe projection digest。

所有list按canonical key排序，package name按PEP 503 normalize；duplicate name/version/file/hash、unknown
marker result、noncanonical URL或extra field fail closed。

### Wheelhouse records

每个 `python_distribution_artifact@1` 包含：

- normalized distribution name、exact version、direct/transitive/build role；
- filename、artifact SHA-256、byte size；
- wheel build/tag set、Python ABI、platform compatibility；
- source index logical id和download receipt digest（不含credential/query token）；
- license/metadata digest、RECORD digest；
- optional source archive hash and source-to-wheel build attestation；
- selected marker/extras reason；
- yanked/prerelease/local-version policy verdict。

runtime install只读取这些verified files。hash-locked requirements必须覆盖所有可选platform candidate，
但current build只能选择manifest声明platform的exact wheel；不能因compatible wheel缺失而联网或选sdist。

### Build toolchain records

`uv`、pip、installer、hatchling/build backend及生成SBOM/attestation的工具也属于supply chain，必须
exact pin/hash。可以用一个预构建、digest-pinned builder image承载它们，但builder image自身也要有
base/manifest/SBOM identity，不能成为未审计bootstrap例外。

## Canonical lock and offline build flow

```text
reviewed pyproject + exact direct policy
                  |
                  v
pinned uv resolver for declared target platform(s)
                  |
        canonical uv.lock / hash export
                  |
                  v
controlled fetch phase with hash verification
                  |
          verified read-only wheelhouse
                  |
                  v
network-disabled reproducible OCI build
  FROM exact base@sha256
  install --offline --frozen --require-hashes
  no sdist / no index / no runtime pip mutation
                  |
                  v
runtime assertions + SBOM + build attestation
                  |
                  v
immutable image + dependency manifest registry record
```

推荐以`uv lock --locked`/platform-aware export产生canonical lock，再生成pip-compatible
`--require-hashes` input或直接使用uv的frozen/offline install。具体CLI可以演进，但semantic contract
必须固定：不resolve、不联网、不忽略hash、不从ambient cache引入undeclared artifact。

Host package cache只能作为content-addressed mirror：读取前后重算hash，cache miss是build prerequisite
failure，不授权访问public index。download phase若需要network，必须是独立受控供应链job，产生receipt；
live attempt/image build不能隐式fetch。

## Reproducible OCI build

Container recipe至少要求：

- `FROM <logical-base>@sha256:<manifest-digest>`，并校验architecture；
- canonical build context inventory与每个file digest；
- fixed ownership/mode/uid/gid、path ordering、mtime/`SOURCE_DATE_EPOCH`；
- 禁止ambient git metadata、Host path、locale/timezone、random cache id进入layer；
- network disabled；
- verified wheelhouse以read-only context输入；
- no apt/apk online mutation。若需要OS package，使用digest-pinned base variant或独立hash-closed
  package snapshot；
- deterministic bytecode policy：禁用pyc或固定hash-based pyc/source epoch；
- canonical OCI config/env/labels/entrypoint/user；
- builder engine/version与reproducibility policy进入attestation。

目标是相同input closure在支持的builder上得到相同OCI config/layer/image digests。若不同build engine
目前不能产生bit-identical transport metadata，必须至少定义独立canonical rootfs/content graph digest，
但它不能冒充OCI image digest；cutover仍绑定实际immutable image。最终authority接受哪些digest必须
由versioned policy明确，不能运行时择优。

## SBOM and build attestation

SBOM可采用version-pinned CycloneDX或SPDX canonical profile，覆盖：

- base OS/Python packages；
- every Python runtime/build distribution；
- Pipeline SDK source/wheel；
- native shared libraries及wheel extension dependencies；
- package relationships、licenses、artifact hashes和backend capability refs。

`sandbox_image_build_attestation@1`至少绑定：

- source repo commit/tree and dirty=false；
- build recipe/context/base/dependency/wheelhouse/SBOM digests；
- builder image/tool/version/policy identity；
- network-disabled verdict；
- build start/end与reproducibility epoch；
- output OCI manifest/config/layer/image digests；
- runtime assertion receipt digest；
- signer/attestor identity when deployment has one。

没有签名服务时可以先保存unsigned canonical attestation并明确`signature_status=absent`；不能把普通
JSON hash称为signed provenance。未来签名/透明日志属于deployment policy，不应硬编码到scientific
calculation合同。

## Namespaced backend capability

科学backend不应以顶层裸包名投影。建议registry record示例：

```text
scientific_backend:aox_global_sequence_identity.biopython_trace_guarded_numpy_gotoh@1
```

`scientific_backend_capability@1`包含：

- capability ref/content digest；
- owning calculation implementation refs；
- adapter module/callable digest；
- distribution artifact ref/hash and native dependency closure；
- exact algorithm/mode/matrix/gap/numeric/tie semantics assertion ids；
- supported Python ABI/platform/runtime manifest digests；
- deterministic/oracle fixture digests；
- availability/failure taxonomy；
- public docs/facts projection。

同一个`biopython==1.87`可服务不同算法，但每个adapter capability必须namespace化，不能用
`biopython_available=true`概括科学语义。workflow选择calculation implementation后机械得到所需
backend capability；agent不能用另一个Biopython algorithm或本地import猜测替代。

## Registry, runtime health, and campaign pinning

### Image/dependency registry

Host sandbox image registry将来应存：

- immutable image ref/digest；
- dependency manifest id/digest；
- base/Python ABI/platform digest；
- SBOM/attestation digest and verification status；
- backend capability map/content digest；
- Pipeline SDK source/wheel/protocol identity；
- qualification status and policy epoch。

registry row只能从verified build output创建；operator输入不能成为truth source。预存未知row、mutable
ref、manifest/image mismatch或backend map duplicate全部fail closed。

### Runtime health

preflight在实际image内运行bounded inspector，返回safe closed facts：

- actual Python implementation/full version/SOABI/platform/libc；
- installed distributions names/versions/RECORD aggregate digest；
- native extension/import path content digest（不投影Host path）；
- backend-specific version/algorithm/numeric assertions；
- dependency manifest/SBOM/backend capability map digest；
- image/SDK/protocol identity。

Host把inspector result与registry manifest逐字段比较。仅image id相等但installed distribution或ABI
漂移也必须失败；inspector不可读取network、credential或Host filesystem。

### Campaign identity

当前 AOX exact-seven launch identity和exact-nine prerequisite schema不在本Goal扩张。未来migration
需要version bump并至少绑定：

- sandbox image digest；
- Pipeline SDK digest；
- dependency manifest digest；
- Python ABI/platform digest；
- backend capability map digest；
- SBOM/build-attestation policy identity。

pin、run-live、attempt bundle和offline verifier必须引用同一closed preimage。两个positive或fault若
dependency/backend epoch不同，不能聚合GO；历史image digest不能被new manifest反向补强。

## Runtime assertions for scientific dependencies

dependency manifest证明bytes closure，backend runtime还要证明selected semantics：

- import exact distribution and adapter；
- assert exact normalized version；
- assert expected Python ABI/platform and extension load identity；
- assert named algorithm/config path，不允许default algorithm漂移；
- assert integer/rational/numeric units、rounding和tie behavior；
- runsmall immutable oracle vectors including boundary/tie/error cases；
- emit closed backend capability receipt bound toimage/manifest/implementation digest。

这些assertions不能靠`__version__`单字段替代，也不能在失败时改用pure Python/local approximation。

## Failure taxonomy

建议稳定分类：

- `sandbox_base_image_unpinned`
- `sandbox_dependency_lock_drift`
- `sandbox_dependency_hash_mismatch`
- `sandbox_dependency_artifact_missing`
- `sandbox_dependency_platform_incompatible`
- `sandbox_dependency_sdist_forbidden`
- `sandbox_dependency_online_resolution_forbidden`
- `sandbox_dependency_manifest_mismatch`
- `sandbox_dependency_sbom_mismatch`
- `sandbox_build_attestation_incomplete`
- `sandbox_runtime_python_abi_mismatch`
- `sandbox_runtime_distribution_mismatch`
- `scientific_backend_capability_missing`
- `scientific_backend_runtime_assertion_failed`

public errors只含stable code、logical capability/package、expected/observed digest prefix和safe platform
identity；index URL、cache/Host path、registry token、wheel locator、environment和raw loader error留在
private diagnostic。

## Security and supply-chain boundary

- hash pin防止artifact bytes被无声替换，但不证明maintainer可信；依赖加入仍需source/license/security/
  scientific review。
- download使用allowlisted HTTPS registry/mirror和credential broker；credential不进入lock、manifest、
  SBOM、attestation或error。
- wheel在进入wheelhouse时校验filename/metadata/RECORD/hash；archive path traversal、duplicate member、
  symlink和malformed metadata拒绝。
- native extension增加TCB；runtime profile保持no-network、non-root、read-only、cap-drop、seccomp/cgroup，
  并做native dependency inventory。
- SBOM与attestation themselves是content-addressed artifacts；tamper或cross-image reuse失败。
- builder与runtime分离，runtime image不含compiler/header/package manager cache或download credential。
- agent不能写site-packages、设置任意`PYTHONPATH`覆盖backend、加载user site或运行时安装plugin；当前
  read-only SDK mount也必须与manifest identity明确分层。

## Compatibility and migration

1. **Inventory**：记录current base tag、actual OCI digest、Python/ABI/platform、Pipeline dependencies、
   build isolation downloads、native wheels和all image/runtime consumers。
2. **Schema/profile freeze**：定义dependency manifest、distribution artifact、backend capability、SBOM、
   attestation和runtime inspector closed schemas/canonical digests。
3. **Direct-pin baseline**：保留当前Goal的exact direct pins和runtime assertions；生成shadow lock/export，
   不改变current image authority。
4. **Verified wheelhouse**：用pinned uv/build tools针对declared platform下载并hash所有runtime/build
   artifacts；禁止隐式sdist fallback。
5. **Immutable base and offline build**：切换`FROM ...@sha256`、network-disabled install、canonical
   context/mtime/ownership；连续build比较OCI/content graph digest。
6. **SBOM/attestation**：生成canonical SBOM与build/runtime assertion receipts并独立验证。
7. **Namespaced backend registry**：先shadow登记AOX backend，比较actual imports/algorithm/oracles；
   mismatch保持NO-GO。
8. **Runtime health dual projection**：现有image/SDK identity继续authority，新manifest facts只shadow；
   API/UI不得称shadow verified。
9. **Schema authority cutover**：version bump sandbox registry/runtime health/campaign pin/evidence，绑定
   dependency/backend/SBOM identities；legacy image明确non-cutover。
10. **Caller audit and retirement**：确认CI/operator/live没有调用mutable/online builder后，用breaking
    change删除旧path；new build失败时不回退online pip。
11. **Fresh qualification**：重跑tamper/reproducibility/non-live/real backend tests及完整AOX三attempt
    campaign，之后才能将manifest标为cutover authority。

historical images只保留其immutable digest和当时可证明的runtime facts，不根据today lock生成“追溯
SBOM”。rollback到legacy builder必须同时恢复明确legacy/NO-GO，不允许new manifest pin在old image执行。

## Tamper and verification tests

### Build closure

- mutable base tag、base manifest/architecture drift、missing digest全部拒绝；
- lock、requirements export、wheel byte/filename/METADATA/RECORD/hash任一bit flip拒绝；
- transitive dependency缺失、额外wheel、duplicate normalized name、unexpected extra/marker拒绝；
- build with network disabled；任何index/DNS request测试必须失败而不是成功fetch；
- sdist-only、wrong ABI/platform wheel、yanked/prerelease policy driftfail closed；
- builder tool/version/hash漂移改变attestation并阻止reuse。

### Reproducibility

- 相同base/context/wheelhouse/policy在两个fresh roots连续build，比较OCI config/layer/image和canonical
  rootfs/content graph digests；
- file order、mtime、uid/gid、umask、locale/timezone、Host path改变不影响canonical output；
- intentional source/dependency/base/recipe改变必须改变对应manifest和image/content digest；
- ambient pip cache为空/污染两种环境得到同一结果或被明确拒绝，不能悄然采用cache artifact。

### Runtime and backend

- actual Python full version/SOABI/platform/libc与manifest闭合；
- installed distribution aggregate、native library、SDK source/wheel和backend capability map闭合；
- wrong package with sameversion、metadata-only spoof、alternate algorithm/default、numeric/tie drift被oracle
  assertions拒绝；
- capabilitymissing不fallback到pure Python、另一个package、Host-local import或runtime pip；
- user-site/PYTHONPATH/site-packages mutation、network、write权限和credential absence测试。

### Product/evidence

- sandbox image registry只接受verified manifest/image pair；preloaded/stale/mismatched row拒绝；
- runtime health重算facts，不回显declaration；public projection无Host/cache/index locator；
- campaign pin/run-live/bundle/offline verifier对dependency/backend/SBOM digest任一tamper fail closed；
- two positives/fault必须same manifest/backend epoch；mixed legacy/new拒绝；
- historical attempts只读且不被new manifest重新解释。

## Risks and mitigations

- **lock跨platform歧义**：每个supported target生成独立selection manifest；不在runtime按marker重新resolve。
- **OCI bit-reproducibility难**：固定build engine/context metadata并同时记录OCI与canonical rootfs graph；
  authority policy只接受明确digest，不择优。
- **wheelhouse体积/维护成本**：按namespaced runtime profile切分、content-addressed dedup；不能因此回退
  online install。
- **SBOM false confidence**：UI/文档明确SBOM是inventory，签名/provenance/vulnerability/scientific review
  分字段表达。
- **direct pin升级频繁**：dependency update是显式reviewed change，重新生成manifest/oracle/image/campaign；
  不用range降低维护成本。
- **generic sandbox膨胀**：backend capability按profile namespace；只有workflow-required profile进入image。
- **SDK read-only source mount与installed wheel双份**：长期明确一个execution authority，另一份仅作
  source attestation或退役；preflight拒绝import precedence漂移。
- **native extension portability**：每个ABI/platform独立manifest和qualification；不声称一个wheel跨
  glibc/architecture通用。

## Explicit non-goals

- 不允许agent运行时pip/uv install、选择index、下载wheel或修改site-packages。
- 不以SBOM/hash pin替代dependency安全审计、license review、签名或科学正确性证明。
- 不自动升级package/base image、合并Dependabot式变更或放宽version range。
- 不把sandbox dependency manifest扩张为HPC SIF、Host OS或所有产品服务的统一供应链registry；这些
  runtime各自保留owner并通过identity引用。
- 不因build reproducibility引入多进程SQLite、untrusted runner或新的顶层control plane。
- 不在当前AOX/HMM Goal实现offline wheelhouse、immutable base、SBOM/attestation、registry schema或
  campaign identity migration。

## Acceptance criteria before implementation becomes authoritative

1. build仅接受exact base OCI digest、declared Python ABI/platform和hash-closedwheelhouse；network与
   ambient cache不可改变结果。
2. complete runtime/build dependency graph可从canonical lock/requirements/wheel records重算，所有
   transitive artifact有SHA-256和selection reason。
3. two fresh offline builds达到policy要求的identical OCI/content graph digests；差异有typed blocker，
   不人工选择一个作为canonical。
4. canonical SBOM和build attestation绑定base/source/lock/wheels/tools/recipe/runtime assertions/final image，
   tamper全部fail closed。
5. namespaced backend capability绑定exact distribution artifact、adapter/algorithm/numeric oracles、ABI/
   platform和calculation implementation；裸`package available`不能满足workflow。
6. actual runtime inspector与registry manifest逐字段一致；same-version wrong wheel或wrong ABI被拒绝。
7. runtime image no-network/non-root/read-only，不能runtime install、user-site override或读取build/index
   credential。
8. sandbox registry/runtime health/API/UI只投影safe manifest/backend facts，不暴露Host/cache/index path。
9. versioned campaign pin和offline bundle绑定image+SDK+dependency+ABI+backend+SBOM identity；mixed epoch
   无法聚合GO。
10. historical images/attempts不被retrofit，legacy builder仅在caller audit完成后breaking退役且无online
    fallback。
11. dependency update流程包含review、lock/wheel/SBOM/attestation regeneration、oracle/performance/tamper
    gates和fresh live qualification。
12. AOX两个positive与fault在同一verified dependency manifest/backend capability/image上真实封存并
    offline通过，之后才可称该build architecture支持cutover。

在这些条件全部满足前，本提案保持 **proposed / not implemented**。当前Biopython `1.87` / NumPy
`2.4.4` exact direct pins、runtime version/algorithm/numeric/trace/correction assertions和immutable
final image digest是必要的小型fail-closed边界，
不是可重现依赖供应链的替代品。
