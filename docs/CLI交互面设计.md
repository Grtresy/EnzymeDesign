下面给你一套**“像 Claude Code 一样用”的酶设计 Agent CLI 交互设计**：命令、目录结构、会话/迭代模型、以及典型使用流程。你可以直接按这个做 MVP，然后再迭代 UI/功能。

---

## 1) 核心交互模型

* **Project（项目）**：一个酶/底物/目标的长期工作区
* **Episode（迭代轮次）**：一次“从目标→跑工具→产出候选→报告”的闭环（类似一次 Claude Code 的任务）
* **Run（工具调用）**：一次具体 HPC 工具执行（hhblits/AF3/vina…），对应一个 `run_id`
* **Artifact（工件）**：所有产物文件（结构、msa、评分、日志、图表、报告等）
* **Manifest**：可复现的元数据：参数、版本、输入、输出、依赖、校验

你在 CLI 里主要做两件事：

1. **chat 把目标变成结构化约束 + plan**
2. **run 把 plan 变成可复现工件 + report**

---

## 2) 项目目录结构（强烈建议固定）

```text
my-enzyme-project/
  enzyme.yaml                 # 项目级配置（目标、底物、约束、默认工具链）
  data/
    inputs/                   # 用户提供的输入（序列/结构/底物/参考论文pdf可选）
    refs/                     # 参考结构、对齐参考、模板等
  episodes/
    0001/
      goal.md                 # 本轮自然语言目标（从 chat 摘要而来）
      plan.yaml               # 本轮执行计划（图编译结果）
      state.json              # 本轮结构化状态（约束、位点、评分权重、选择记录）
      runs/
        run_.../              # 每次工具调用一个目录（远端/本地映射）
      artifacts/
        candidates.fasta
        candidates.csv
        structures/
        docking/
        pocket/
      report.md
      manifest.json
  cache/                      # 索引、embedding、下载数据库（可选）
  .enzyme/
    cli_state.json            # CLI 自己的状态（当前 episode、最近 job 列表）
```

---

## 3) CLI 命令面（MVP 一套够用）

命令分四类：项目、对话、执行、回看/交付。

### 3.1 项目类

* `enzyme init <name>`
  创建目录结构 + 生成 `enzyme.yaml` 模板

* `enzyme config set <key> <value>`
  改默认工具链/集群配置/数据库路径等（会写入 `enzyme.yaml`）

* `enzyme doctor`
  自检：能不能连 HPC、runner 是否可用、工具合同是否完整、数据库是否能挂载

### 3.2 对话类（Claude Code 的核心）

* `enzyme chat`
  进入交互式对话（默认绑定当前 project + 当前 episode）

* `enzyme chat --episode 0003`
  切换到某轮迭代继续聊

对话里支持 **斜杠命令**（像 Claude Code）：

* `/goal ...` 设置/更新目标
* `/constraints` 查看结构化约束
* `/set key=value` 修改约束（例如 freeze_residues、pH、metal、substrate）
* `/plan` 生成计划草案（不执行）
* `/apply` 把 plan 固化为 `plan.yaml`
* `/run` 直接开始执行（等价于外部 `enzyme run`）
* `/status` 看 job 状态
* `/open <artifact>` 打开产物（或打印路径）
* `/report` 生成报告

### 3.3 执行类（可脚本化、可异步）

* `enzyme new-episode "提高对底物X的活性"`
  新建迭代轮次：`episodes/000N/`，写入 goal.md

* `enzyme plan`
  从当前 episode 的 state/goal 生成 `plan.yaml`（可加 `--dry-run`）

* `enzyme run`
  执行 `plan.yaml`：提交一串 runs（默认异步 sbatch），持续更新状态

* `enzyme run --step msa` / `--step fold` / `--step pocket` / `--step dock` / `--step design`
  只跑某个阶段（便于你手动控制）

* `enzyme run --resume`
  从失败/中断处续跑（根据 manifest + run 状态）

### 3.4 回看与交付

* `enzyme status`
  总览：当前 episode、正在跑的 jobs、最近失败、关键产物

* `enzyme logs <run_id>`
  拉取/查看 stdout/stderr + 工具日志（支持 `--follow`）

* `enzyme fetch <run_id>`
  把远端产物拉回 `episodes/000N/runs/run_id/`

* `enzyme report`
  生成 `report.md` + `candidates.csv` + 图表（可选）

* `enzyme export --episode 0004 --format zip`
  打包交付：report + manifest + candidates + 关键结构/评分（给实验同事）

---

## 4) `enzyme.yaml`（项目配置模板）

```yaml
project:
  name: my-enzyme-project
  organism: ""
targets:
  substrate:
    name: "substrate_X"
    smiles: ""
  reaction: ""
constraints:
  freeze:
    residues: []        # e.g. ["A:57", "A:102"]
    radius_angstrom: 6
  keep_metal: true
  ph: 7.5
pipeline:
  defaults:
    msa: hhblits
    fold: chai_fold      # or alphafold3
    pocket: fpocket
    tunnel: caver
    dock: vina
    design: proteinmpnn
scoring:
  weights:
    docking_score: 0.5
    pocket_volume: 0.2
    conservation: 0.3
hpc:
  profile: diannan       # 对应你的 cluster config
```

---

## 5) `plan.yaml`（一次迭代的执行计划示例）

```yaml
episode: "0004"
steps:
  - id: msa_1
    tool: hhblits
    inputs:
      fasta: "data/inputs/enzyme.fasta"
      db: "uniref30"
    outputs:
      a3m: "artifacts/msa/enzyme.a3m"

  - id: fold_1
    tool: chai_fold
    inputs:
      fasta: "data/inputs/enzyme.fasta"
      msa: "artifacts/msa/enzyme.a3m"
    outputs:
      pdb: "artifacts/structures/model_1.pdb"

  - id: pocket_1
    tool: fpocket
    inputs:
      pdb: "artifacts/structures/model_1.pdb"
    outputs:
      pockets_dir: "artifacts/pocket/fpocket_out/"

  - id: dock_1
    tool: vina
    inputs:
      receptor_pdbqt: "artifacts/docking/receptor.pdbqt"
      ligand_pdbqt: "artifacts/docking/ligand.pdbqt"
    outputs:
      poses: "artifacts/docking/poses.pdbqt"
      score: "artifacts/docking/score.json"

  - id: design_1
    tool: proteinmpnn
    inputs:
      pdb: "artifacts/structures/model_1.pdb"
      freeze_residues: ["A:57","A:102"]
      num_seqs: 64
    outputs:
      fasta: "artifacts/candidates/candidates.fasta"
```

---

## 6) 典型使用流程（从零到一轮迭代）

### 6.1 初始化

```bash
enzyme init my-enzyme-project
cd my-enzyme-project
enzyme doctor
```

### 6.2 放入输入

```bash
cp enzyme.fasta data/inputs/enzyme.fasta
cp ligand.sdf  data/inputs/ligand.sdf
```

### 6.3 开始一轮迭代（Claude Code 体验）

```bash
enzyme new-episode "在不改动活性位点附近6Å的前提下，提高对底物X的结合"
enzyme chat
```

在 chat 里你可以：

* `/set constraints.freeze.radius_angstrom=6`
* `/set constraints.freeze.residues=["A:57","A:102"]`
* `/plan`
* `/apply`
* `/run`

### 6.4 中途查看与续跑

```bash
enzyme status
enzyme logs run_20260302_...
enzyme run --resume
```

### 6.5 交付

```bash
enzyme report
enzyme export --format zip
```

---

## 7) MVP 必须实现的“Claude Code 感”

为了让你真的觉得“像 Claude Code”，CLI 里建议强制这些交互细节：

1. **所有改动都落盘**：goal、constraints、plan、manifest、report
2. **每个工具都有 run_id + 可复现参数**：manifest 里记录工具版本、输入哈希、输出哈希
3. **默认异步**：run 提交后立刻返回，status/ logs/ fetch 都可独立调用
4. **关键节点停下来问你**：比如要提交大规模 ProteinMPNN（num_seqs 很大）或要跑 AF3 GPU 长作业时，必须确认（即使你不喜欢确认，也建议默认开一个 `--yes` 绕过）
5. **一次迭代一个“交付包”**：report + candidates + top structures + scores + manifest

---

如果你认可这套交互面，下一步我建议直接把**CLI 的命令与内部 API**定死：每条命令输出什么 JSON（便于以后做 TUI/Web），以及 episode/runs 的 manifest schema（和你现有 tool-contracts/runner 对齐）。我可以继续把这些 schema（`EpisodeState`, `RunManifest`, `ArtifactIndex`）给你画出来。
