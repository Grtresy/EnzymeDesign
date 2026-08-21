# enzymedesign-docking-preprocess

EnzymeDesign 的分子对接前处理产品插件。它是原 `preprocess-backend` 的唯一代码 owner；旧 wheel 已从
workspace 与 lock manifest 移除，不再保留第二套实现或兼容导入。

插件贡献一个 closed 工具 `enzymedesign.docking.preprocess`，支持 `convert_format`、
`prepare_receptor`、`prepare_ligand` 和 `smiles_to_3d`。模型只能传 workspace-root-relative
输入/输出路径，不能传 Host 路径、credential、target 或任意命令。runtime 通过注入的应用实现执行，
成功只表示一个私有 workspace 输出已经生成；它不发布 revision、不形成 scientific adoption，也不完成
Task。

exact manifest 声明以下资源事实与 operator-controlled qualification：

- `software.rdkit >=2024.9.1`：SMILES 三维构象；
- `software.meeko >=0.6.1`：配体 PDBQT 前处理；
- `software.openbabel >=3.1.1,<4`：格式转换与 receptor/ligand 基础转换。

Python 化学依赖只位于本 wheel 的 `chem` extra。普通 OpenZyme Standard 不安装本包或这些依赖；
EnzymeDesign composition 将插件列为 optional，依赖或 qualification 不满足时按 manifest 进入 degraded，
不会让 Host 静默改用另一套转换器。

Non-live 验证：

```bash
.venv/bin/pytest -q packages/enzymedesign-docking-preprocess/tests
```
