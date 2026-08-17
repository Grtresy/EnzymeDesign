# Executor Workspace Rules

受监督进程是执行隔离，不是共享文件真相。遵守以下规则：

1. 只在当前 owner/generation workspace root 内读写；拒绝 symlink escape、`..`、ambient path 和
   其他 member 的 locator。
2. 使用 native filesystem 和 Git。需要共享时显式形成 clean checkpoint 或调用
   `workspace.publish`；不要传递 mutable checkout path。
3. 外部 job 只从 exact revision 提交。不要将 Host path、remote absolute path、raw scheduler id、
   repository credential 或 LFS endpoint放进 request。
4. login/file credential 不能调用 scheduler。submission 必须经过
   `workspace_revision_job.submit` 的 Host admission。
5. approval、operation id、idempotency key、deadline 或 error code 不得自行改写。pending/unknown
   effect 时等待 durable owner observation，不循环 replay。
6. 进程退出不表示 external effect settled，也不表示 task/scientific attempt 完成。
7. 输出先写当前 workspace，再形成 result revision/publication；不得创建未声明的 placeholder。
8. secret、credential、private ref、raw backend log 和 owner locator 不写入共享文件或 tool result。

`workspace.exec` 可执行有界本地命令，但不能绕过 Host/provider/HPC authority。不要把它用作读取
其他 owner 环境或探测 hidden infrastructure 的捷径。
