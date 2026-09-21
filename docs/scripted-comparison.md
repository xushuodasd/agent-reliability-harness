# 配对脚本恢复策略（开发诊断 v1）

## 实施契约

本轮只比较 `retry_once`（超时直接重试一次）与 `query_then_retry`（超时先查询，仅在未发现效果时重试一次）。两者只能读取统一引擎的公开任务契约与工具历史，不能读取私有故障标签、账本或计划。

- 同一任务结构、故障、查询可见性、幂等性下配对；每个配置均为最多 4 次工具尝试、6 次决策步。
- dispatch：3 种故障 × 2 种可见性 × 2 种幂等性 × 2 个策略，共 24 格。
- reservation：3 种故障 × fresh 查询 × 2 种幂等性 × 2 个策略，共 12 格。
- 共 36 个确定性配置，只有 **2 种独立任务结构**，不是 36 个独立科研样本。不同可见性、幂等性不能合并后归因于策略。
- 未支持的错误、重复超时或异常响应停止策略并保留引擎 UNKNOWN；不能伪造完成或无限重试。
- 运行前写入完整计划；每格使用新环境和新策略实例。保留失败格，不重试、不选择性剔除。
- 保存实际工具尝试数；预算上限相同不代表消耗相同。局部副作用评分不替代通用安全测量。
- 对整个批次封存，并以完整预期文件边界只读复核。缺失、篡改或计划不符时不得输出已验证汇总。

## 验证边界

这是人为设置故障下的脚本对照，不使用真实模型，不计推理成本，不支持优于模型的结论，不证明新颖性，不用于正式推断统计。提交后的实验方案、更多独立任务结构、外部模型基线、计量与正式协议仍未完成。

## 复现与只读验证

在仓库根目录安装项目后，使用一个尚不存在的目录：

```powershell
python -c "from pathlib import Path; from pilot_harness.scripted_comparison import run_comparison; run_comparison(Path('runs/scripted-comparison-example'))"
python -c "from pathlib import Path; from pilot_harness.scripted_comparison import verify_comparison; r=verify_comparison(Path('runs/scripted-comparison-example')); print(r['valid'], r['errors']); raise SystemExit(0 if r['valid'] else 1)"
```

输出包括运行前 `plan.json`（配置及源码/模式哈希）、每格 `episodes/`、
`execution-errors.json`、逐格 `summary.json` 和外层 `manifest.json`。
基础设施错误不重试，失败格的原始材料及错误类保留；校验不通过时返回的
`summary` 为 null。策略错误产生的有效 UNKNOWN 记录仍保留，不把它当缺失格剔除。
完整性有效不意味着所有格安全，也不意味着实验有统计效力。

验证器根据版本固定的 36 格设计确定所需边界，不依赖待验证 manifest 自报文件清单。
比对原始任务配置、模型/策略标记、故障条件、局部账本、工具轨迹及保存的汇总。
验证前后重新校验外层哈希；只读，不修复、不重新采样。源码哈希用于来源追踪，
不是签名，不证明来源真实；复核旧证据不要求当前源码与历史源码完全一致。

本 v1 查询策略仅处理一次已知超时。错误类别、异常响应及重复超时会以 RuntimeError
结束并留下 UNKNOWN，而不是生成“安全停止”测量。未来真实模型基线需另行固定提示词、
模型版本、token/金额累计预算与断点策略，不能把这里的脚本名称改成模型名充当实测。
