# enzymedesign-aox-executor

AOX Product Plugin 的 subordinate calculation Driver。

本包拥有 AOX fixed references、motif/threshold、HMMER parsing、sequence join、similarity graph、candidate validation、deterministic finalization calculation 和对应 fixtures。它可以依赖 Biopython、NumPy 与 domain-neutral `openzyme-execution-sdk`，但不拥有 AOX workflow/scientific file contract，也不直接访问 Host、Core repositories、SSH、Slurm、credential 或 target inventory。

Driver manifest 精确绑定 owning `enzymedesign.aox@1`、calculation manifest digest、scientific file result contract 和 execution SDK Port。安装 wheel 不会 ambient 激活；必须由 EnzymeDesign Distribution 显式选择。
