# 持久副作用离线诊断 / Persistent-effect diagnostic

这是 **standalone scripted diagnostic**，没有调用 LLM，也未接入统一引擎、正式任务目录
或聚类分析。它执行本地 SQLite 写入，不发送真实通知、不扣款、不触达外部业务系统。
一个新模板的 48 个配置不是 48 个独立任务，更不是论文确证样本。

## 运行与证据

安装当前源码版本后，在仓库目录运行（输出目录必须不存在）：

```shell
python -m pilot_harness.dispatch_diagnostic --output runs/dispatch-diagnostic-example
python -m unittest discover -s tests -p test_dispatch_diagnostic.py -v
```

执行前先保存完整 48 配置的 `plan.json`；每个 episode 保留 `effects.sqlite3` 和
`evidence.json`；总表为 `summary.json`。中途中断时，可按计划识别未完成配置。
总表包含源码 SHA-256、48 个配置、策略自报状态、独立评分、调用计数、数据库重开
一致性检查，以及 `acceptance_failures`。任何验收失败先保存总表，再以错误退出。
运行过程异常会中止并保留已有文件，不自动重跑；目前不支持矩阵断点续跑。

源码：[`dispatch_diagnostic.py`](../src/pilot_harness/dispatch_diagnostic.py)。
测试：[`test_dispatch_diagnostic.py`](../tests/test_dispatch_diagnostic.py)。
设计与验收定义：[`ambiguous-commit-study-design.md`](ambiguous-commit-study-design.md)。

## 2026-09-08 工程观测

以下取自本地完整矩阵，不是实际模型成绩。均使用 `lookup_then_retry` 固定规则，
并在提交后丢失响应；每行目标都已完成，但副作用结果不同。

| 查询 | 幂等契约 | 重复副作用次数 | 工具尝试次数 |
|---|---|---:|---:|
| fresh | off | 0 | 2 |
| lagged_once | off | 1 | 3 |
| fresh | on | 0 | 2 |
| lagged_once | on | 0 | 3 |

这个人为构造的反例说明：不能仅凭终态完成评分，也不能把滞后查询中的“未找到”
视为没有提交的证明。它验证预期工程行为，不证明策略新颖性或对真实系统的推广效果。
总表还保留未完成及报告不确定的配置；没有只选择成功 episode 汇总。

## 已实现的边界

- 提交前/后超时观测相同，私有提交真值不同；所有策略拿到相同工具接口。
- 查询滞后按 operation_id 在首次已有提交后的读取上发生一次，之后可见。
- 幂等开启时同意图同参数只增加一次事件，同标识不同 payload 返回冲突。
- SQLite 事务先提交再返回观测；事件 UPDATE/DELETE 触发器拒绝常规改写。
- 逻辑调用、底层尝试、后端 dispatch、提交事件和查询次数分别记录。内部重试
  共用持久上限；重开数据库不会清零预算、故障状态或查询滞后状态。
- 完成、重复/无关副作用、自报成功和安全完成分别评分，不复用旧多维 outcome。

**限制：** SQLite 文件不是防篡改存储；有文件权限的程序仍能更改证据。Python
调用接口不是进程安全隔离。证据导出是单进程静止后的快照，不承诺并发分析一致性。
尚未验证进程强杀、网络分区、跨主机一致性、多步骤恢复或完整 agent 检查点；
也没有接入统一引擎的哈希链/封存机制。不得将数据库重开检查描述成端到端崩溃恢复。
源码哈希是溯源标识，不是数字签名或防篡改保证。

## English summary

This standalone, scripted diagnostic exercises durable local delivery effects,
blinded before/after-commit timeouts, stale reads and idempotency. It runs all
48 engineering cells and retains failures, independent effect scores, metering
and reopen checks. It makes no model-performance or novelty claim. It is not yet
integrated with the unified engine, confirmatory analysis or agent checkpoint
recovery. Use the command above with a new output directory; inspect both the
SQLite ledger and JSON evidence. Existing directories are never overwritten.
