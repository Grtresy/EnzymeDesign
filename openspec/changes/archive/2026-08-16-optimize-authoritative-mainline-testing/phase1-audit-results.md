# Phase 1 compatibility audit single-pass 结果

## 结论

`scripts/audit-v3-compat-callers.py` 已从按 seam 重复遍历、读取和扫描仓库，改为一次
invocation-scoped `RepositoryIndex`。在同一当前工作树上，旧实现与新实现连续三对完整
报告均逐字节相同；墙钟中位数从 `22.74s` 降至 `3.25s`，减少 `85.708%`，约为
`6.997x` 加速。

这一优化没有使用 mtime/content 跨调用缓存，也没有改变 report schema、seam 决策、
caller 分类/顺序、violation、scan-error 或退出码语义。当前权威入口
`scripts/check-mainline.sh` 在本阶段保持逐字节不变。

## 重构前冻结证据

在修改 audit 实现前，对当时工作树分别捕获完整报告与 summary：

- 完整报告：
  `/tmp/openzyme-compat-audit-pre-20260729-r2-full.json`
- 完整报告 SHA-256：
  `25e4721489c778f61935929d9a7b30fa6d990a3fb50e32af29e17d56df9c0041`
- 完整报告大小：`57,523` bytes
- 完整扫描墙钟：`22.78s`
- summary：
  `/tmp/openzyme-compat-audit-pre-20260729-r2-summary.json`
- summary SHA-256：
  `4e7ceae82a78c4cb7f24586f82b2e768e4e4ee142ab9246dab4f2478665b75ba`
- summary 墙钟：`22.69s`
- 结果：`21` seams、`0` violations、`0` scan errors、退出码 `0`

完成第一版索引后，在添加新测试源码前捕获
`/tmp/openzyme-compat-audit-post-20260729-r2-full.json`。其 SHA-256 与大小分别仍是
`25e4721489c778f61935929d9a7b30fa6d990a3fb50e32af29e17d56df9c0041`
和 `57,523` bytes，证明重构本身没有改变当前仓库报告。

## 同语料三对测量

最终配对通过 `git show HEAD:scripts/audit-v3-compat-callers.py` 只读加载旧实现，并让旧、
新实现扫描完全相同的当前工作树。两边完整报告均为 `59,402` bytes，SHA-256 均为：

`918adc0882c37765ff7b7b4ef4f071ae48fd3c7dfab66703ad47833b95836a77`

当前 inventory 内容摘要（包含 audit 脚本）为
`sha256:4df0856d40209772e2a24829b0ab6843b211702234edc1c86f385270eaede965`；
两种实现看到的是同一份 inventory。每对测量均先运行旧实现、再运行新实现，并以
`cmp -s` 强制逐字节等价：

| Pair | 旧实现 | `RepositoryIndex` | 完整报告等价 |
| --- | ---: | ---: | --- |
| 1 | `22.69s` | `3.25s` | 是 |
| 2 | `22.95s` | `3.23s` | 是 |
| 3 | `22.74s` | `3.25s` | 是 |
| median | `22.74s` | `3.25s` | 是 |

原始配对文件位于：

- `/tmp/openzyme-compat-audit-paired-legacy-p{1,2,3}.json`
- `/tmp/openzyme-compat-audit-paired-indexed-p{1,2,3}.json`
- 对应的 `.seconds` 文件

最终 `--summary` 位于
`/tmp/openzyme-compat-audit-final-20260729-r1-summary.json`，SHA-256 为
`4e7ceae82a78c4cb7f24586f82b2e768e4e4ee142ab9246dab4f2478665b75ba`，
结果仍为 `21` seams、`0` violations、`0` scan errors，墙钟 `3.24s`。

## Inventory 与读取/解析闭合

最终真实仓库索引统计如下：

| 项目 | 数值 |
| --- | ---: |
| deterministic inventory | `1,087` files |
| 总 read/decode 次数 | `1,087` |
| 任一 candidate 最大读取次数 | `1` |
| Python candidates | `488` |
| TOML candidates / 成功 parse | `25 / 25` |
| Markdown/RST candidates | `353` |
| non-Python source candidates | `246` |
| 预闭合 documentation literals | `14` |
| 预闭合 source literals | `2` |
| scan errors | `0` |

实现只执行一次 deterministic `os.walk`；每个 candidate 的内容、lines 与 SHA-256 在
不可变 index 中保存。Python AST、TOML payload、semantic reference、literal hit、
lifecycle caller、route caller 和 scan error 都在构造期闭合，后续 seam scanner
只读取 index。TOML payload 使用递归只读 mapping/tuple，所有 index records 使用
frozen dataclass。

## 回归边界

`packages/openzyme-core/tests/test_compat_caller_audit.py` 覆盖：

- 受控 reader、`os.walk`、Python parser 和 TOML parser 计数，证明每个 candidate
  最多读取/解析一次；
- 只读 index 与嵌套 TOML payload；
- 由重构前实现独立生成的 clean fixture golden：
  `9ffb7b619be885645e99e3af54c8057f96ac88f06b691a6a982c99cac185232a`；
- 由重构前实现独立生成的 retired-caller fixture golden：
  `63ae093d116583c8d83a0c6d84ddf76b46e8e19058cc76dbb5df8aee6a7ebc08`；
- production retired caller 的相同 caller evidence、classification、三项 violation
  与退出码 `1`；
- invalid Python/TOML、Unicode decode 和 `OSError` 的确定性 scan error 与退出码
  `2`；
- production、production config、test、docs、archive、auxiliary 分类；
- clean、violation、scan-error 三种 CLI 退出码 `0/1/2`；
- 同一 fixture 重复执行 canonical bytes 完全一致。

真实仓库 timing 不作为脆弱的毫秒单元测试断言；正确性由 read/parse 计数、golden bytes
和失败注入锁定，性能由上述 checkout-external 实测证据证明。
