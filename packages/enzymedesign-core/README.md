# enzymedesign-core

EnzymeDesign 公共垂直 contracts 与组合贡献。

当前包拥有 `enzymedesign.bio-provider@1` 等产品侧稳定 Port/DTO，不提供可激活
manifest、runtime、state writer 或外部效果实现。Provider Plugin 依赖这里的窄
Port，HTTP Adapter 实现该 Port；两者都不能反向依赖 Host、Kernel repository 或
SQLite。Distribution 不得仅因 wheel 已安装就把它视为能力。
