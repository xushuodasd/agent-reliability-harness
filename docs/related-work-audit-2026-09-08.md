# 候选贡献定向核查：工具故障与提交不确定性

日期：2026-09-08。性质：研究准备记录，不是系统综述、实验复现、预注册或录用判断。
本轮查阅三篇预印本全文中的相关方法/评分章节与 AgentCheck、ToolMaze 的指定源码。
未运行第三方软件、未验证论文报告的数值，也未完成全部相关文献的排查。

## 结论与行动

**不能把“故障注入 + 重试 + 状态核验”作为新的算法贡献。** 当前证据支持把候选题目
收窄为实证问题：在相同工具权限与预算下，查询可见性和幂等契约如何影响智能体的
完成率、重复副作用与停止决策？这个问题仍须进一步排查重叠，不能声称首次研究。

本轮确定的下一项工程工作见[开发规格](ambiguous-commit-study-design.md)：先建立
有持久副作用记录、可控查询滞后和独立评分的本地任务，再考虑付费模型实验。

## 来源与证据边界

| 来源及版本 | 实际核查范围 | 能支持的判断 / 不能支持的判断 |
|---|---|---|
| [AgentCheck v3](https://arxiv.org/html/2607.11098v3)，§4.1、附录 A/E、伦理与局限性；下列固定提交源码 | 缓存重放、输出注入、工具层重试 | 已有受控故障与缓解比较。不能仅凭其缓存响应推断独立重置后的后端提交状态 |
| [ReliabilityBench v1](https://arxiv.org/html/2601.06112v1)，§3.5、§4.1–4.5、算法 2 | 状态判定、故障执行顺序 | 已有终态验证和故障恢复；算法中可恢复故障分支在调用工具前返回错误，另一分支先执行再改响应。该算法不是同一超时观测的提交前/后配对实验。未定位到作者代码入口，源码核查未完成 |
| [ToolMaze v1](https://arxiv.org/html/2606.05806v1)，§3.2–3.5；下列固定提交源码 | 路径结构、故障拦截、恢复评分 | 已有多路径重规划与恢复成本；安全终止可计为恢复，不能与本项目“有证据完成”混作同一指标 |
| [OpenHands benchmarks RFC #764](https://github.com/OpenHands/benchmarks/issues/764)，2026-07-30 的提议正文 | 丢失响应、避免重做不可逆操作、恢复开销 | 与候选问题接近，必须披露。它是公开提议，不是已合并实现或经复现的研究；提及的 reconciliation engine 尚未定位，不推断其功能已验证 |
| [AWS Builders' Library：Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/) | 超时歧义、请求标识、重试契约、迟到请求 | 幂等和核对状态是既有分布式系统方法，作为基线而非我们的发明 |

有限检索词包括 `PranavMishra28 reconciliation engine persist dispatch agent github`、
`"PranavMishra28" "irreversible"`、`"When Tools Fail" "ToolMaze" github`。
“没有定位到”仅说明本轮检索边界，不表示源码不存在或没有同类工作。

## 固定版本的源码证据

### AgentCheck

核查提交：`2b89d2c5782ff81d20843391e1bd410d3e7ffbe9`。

- [`injectors.py`，`inject_a1_timeout`](https://github.com/aritra741/AgentCheck/blob/2b89d2c5782ff81d20843391e1bd410d3e7ffbe9/agentcheck/injectors.py#L15)：返回空结果，由调用层转为超时；这一函数本身不判定业务提交。
- [`mcp_runner.py`，`_run_clean` / `_run_faulted`](https://github.com/aritra741/AgentCheck/blob/2b89d2c5782ff81d20843391e1bd410d3e7ffbe9/agentcheck/mcp_runner.py#L721)：clean 调用后缓存；faulted 命中缓存就复用，偏离后转向实际工具调用，再修改选定响应。
- [`mitigations.py`，`_retry_backoff_wrapper`](https://github.com/aritra741/AgentCheck/blob/2b89d2c5782ff81d20843391e1bd410d3e7ffbe9/agentcheck/mitigations.py#L55)：包装器内多次调用 executor。我们的预算必须区分模型轮次、逻辑工具调用、底层尝试和实际提交，不能只限制轮次。
- [`runner.py`，`run_scenario`](https://github.com/aritra741/AgentCheck/blob/2b89d2c5782ff81d20843391e1bd410d3e7ffbe9/agentcheck/runner.py#L34)：本地路径使用预设 clean_response；不可当成真实后端副作用验证。

这些是所读函数的静态行为判断，不是对该项目所有模式的否定，也不是运行复现结果。
其[根许可证](https://github.com/aritra741/AgentCheck/blob/2b89d2c5782ff81d20843391e1bd410d3e7ffbe9/LICENSE)
为 MIT；场景和第三方依赖仍须逐项核查来源。本轮没有复制其代码或数据。

### ToolMaze

核查提交：`ef0798aa7f31ac9b33403254b1ef76e8673305fa`。

- [`sandbox.py`，`_should_perturb` / `_intercept_tool_call`](https://github.com/Zhudongsheng75/ToolMaze/blob/ef0798aa7f31ac9b33403254b1ef76e8673305fa/evaluation/core/sandbox.py#L513)：扰动分支记录预设输出后直接返回，不进入下方 executor；非扰动分支才执行插件。
- [`executor.py`，`execute`](https://github.com/Zhudongsheng75/ToolMaze/blob/ef0798aa7f31ac9b33403254b1ef76e8673305fa/toolmaze/core/executor.py#L66)：验证参数、调用插件并记录结果。

由所读路径可知，不能直接把其扰动结果重新标记为“已提交但响应丢失”。这不是
整个仓库不可能支持这种扩展的证明。本轮目录树未找到 LICENSE 文件，**暂不引入
代码或任务数据**；后续查明具体材料的许可再决定复用，公开可见不等于许可明确。

## 对本项目的具体约束

1. 比较条件各自重置环境；不得让无故障运行的副作用污染故障条件。
2. 提交前/后超时给模型相同错误结构，隐藏评估真值；之后允许查询产生有意义差异。
3. 成功重试不等于安全恢复。终态正确但曾重复扣减、通知或创建资源仍记副作用。
4. 查询未发现结果不必然证明操作没发生。先用可控滞后反例检验规则，再测 LLM。
   这是本项目待验证设计推论，不是上述论文已经报告的实验结论。
5. 幂等契约是环境能力，不是核验策略私有特权；同一环境内所有策略有相同接口。
6. 完成、无重复副作用、安全停止和自报成功分别评分；不再用同一 outcome 冒充多维。

## 判定门槛与仍未完成项

- 本轮完成：方法章节定向对照、两个仓库的关键执行路径检查、开发规格。
- 仍未完成：reconciliation engine 定位、ReliabilityBench 代码定位、外部任务许可、
  更广泛新颖性检索及基线运行复现。不得将本记录称为“新颖性已证明”。
- 开发继续条件：可以构造盲化成立、评分独立、预算公平的反例，并保留失败证据。
- 正式采集停止条件：缺少上述验证、累计预算或安全凭据；不可先跑大量数据再选结论。
- 若已有研究覆盖相同因素、评分和结论，改为透明复现/扩展；若只有显而易见的
  幂等工程常识，没有可推广的实证发现，则优先软件报告，不强行包装 SCIE 创新。
