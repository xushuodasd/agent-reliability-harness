# Dispatch evidence verification / 副作用证据重算契约

## 本轮范围

为已有 standalone dispatch 诊断增加只读语义复核，作为接入统一证据接口的前置步骤。
只验证 `dispatch-diagnostic-plan/1` 的固定 48 配置和固定目标 `delivery-1` /
`fictional notice`。这不是新增任务族、LLM 实验或统一运行状态机适配。

## 验收约定

1. 首先通过现有 98 文件 manifest 字节边界；不完整时不读取数据库评分。
2. plan、summary、manifest 的版本、scripted 来源、实现哈希与固定配置必须一致。
3. 使用 SQLite `mode=ro&immutable=1` 获取静止账本、计数及工具轨迹；不使用可写环境构造器。
   有 journal/WAL/SHM 边车文件时拒绝复核，要求先由原运行方正常关闭数据库。
4. 每个账本快照必须与 `evidence.json` 私有证据一致；重算完成、重复/无关副作用和
   自报错误标记，并与 episode JSON、summary 中的分数及计数逐项比较。
5. 对重建的完整 48 配置再次执行工程预期检查。读取后再检查 manifest 字节完整性及
   manifest 本身是否变化，避免把检查过程中发生的可见变动作为稳定证据。
6. 任一缺失、结构错误、损坏或不一致：返回 INVALID，`scores=null`、有效测量数为 0，
   不生成零伤害结论、不修复文件、不补跑 episode。成功返回版本化的只读复核报告。

## 证据边界

“通过”仅表示静止的本地 SQLite 工程证据内部一致，不证明来源真实性、研究新颖性、
真实模型表现或现实伤害。manifest 不是签名；同时一致改写所有证据仍可能逃过内部一致性
检查，前后哈希检查也不是对抗并发恶意写入的完整防护。策略自报状态只是被复核的输入，
不能据此宣称其内部推理真实。既有 outcome-only v2 仍保持安全未测，不自动升级为 MEASURED。

只用 `mode=ro` 读取已关闭的 WAL 模式数据库仍可能新建 WAL/SHM 文件，本轮临时夹具已
复现并增加回归测试。`immutable=1` 用于避免此副作用，但会跳过数据库锁与变化检测，
因此绝不能对正在被写入的数据库使用；它不是把文件变成不可修改的权限设置。
参数边界见 [SQLite 官方 URI 文档](https://www.sqlite.org/uri.html#uriimmutable)。

## 使用

```shell
python -m pilot_harness.dispatch_verification --verify runs/dispatch-diagnostic-example
python -m unittest discover -s tests -p test_dispatch_verification.py -v
```

命令只向标准输出返回 JSON；通过退出 0，失败退出 1。不会创建、覆盖、封装或删除源目录
内任何文件；需要保留复核报告时应存到独立派生目录，不写回已封存的原始证据。

English: This read-only bridge recomputes local SQLite side-effect scores from
sealed, quiescent scripted diagnostic evidence. It rejects missing, inconsistent,
or changed inputs without repairing or rerunning them. Internal consistency is
not authenticity, scientific validity, real-model performance, or real-world safety.
