# 中英文软件稿件主张与代码核查（2026-09-25）

性质：仅核对本仓库一手代码、版本与留存记录。固定代码基线
[`85ea06c`](https://github.com/xushuodasd/agent-reliability-harness/tree/85ea06ccc5a2a26ddaf5b46da1ad2aceecc8aab8)。
不是外部文献新颖性审查、原始运行数据复核、作者审稿或正式投稿许可。

## 已核实的事实与稿件处理

| 主张 | 一手证据 | 本轮处理 |
|---|---|---|
| 每个 episode 均有 manifest | [统一引擎](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/src/pilot_harness/unified_engine.py#L213-L230)写入并核验 manifest；[旧 runner](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/src/pilot_harness/runner.py#L38-L80)走另一条较简的路径。 | 将全称判断限定为统一引擎的已完成 episode。 |
| 核验脚手架必然读回并恢复 | [适配器提示词](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/src/pilot_harness/provider_http.py#L231-L255)指导模型，但不能强制它采取动作。 | 改为“提示模型核验与有界恢复”。 |
| 模型预检只读 | [models GET 与 chat POST](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/src/pilot_harness/provider_http.py#L216-L226)是两种不同预检。 | 分别陈述，不推断 chat 预检免费。 |
| 单 episode 费用“硬上限” | [响应后预算检查](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/src/pilot_harness/provider_http.py#L164-L213)仅能拒绝后续动作；[显式预算桥](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/docs/budgeted-transport.md#L21-L34)未默认接入旧 CLI。 | 改为响应后估算/止损，说明全路径累计预算未就绪。 |
| 一般安全已测量 | [验收器](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/src/pilot_harness/acceptance.py#L365-L374)分离缺失安全证据与策略违规；[评分语义](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/docs/scoring-semantics.md#L45-L58)不把工程 GO 当一般安全测量。 | 将“安全违规”限于策略标记，保留未测量边界。 |
| 864 彩排和 72 探索 episode 可供复核 | [后续整理的历史汇总](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/docs/pilot-results.md#L6-L31)记载数量；[恢复记录](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/docs/research-progress-2026-09-07.md#L41-L45)明确原未推送 runs 丢失。代码仍有[彩排入口](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/src/pilot_harness/rehearsal.py#L62-L143)。 | 保留“历史文字记录”属性，不把旧汇总当作可逐项复查的实测证据。 |
| 本稿对应 DOI 版本与当前主线相同 | [CITATION.cff](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/CITATION.cff#L5-L11)列出 `v0.1.2` DOI；[变更日志](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/CHANGELOG.md#L5-L17)含之后的未发布能力。 | 改为“已存档版本”，正式投稿前必须冻结并核对引用版本。 |
| 作者已经审阅并核验 | 仓库无可替代作者本人确认的证据；[研究进度](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/docs/research-progress-2026-09-07.md#L442)也保留此人工步骤。 | 中英文 AI 使用声明改为待作者确认，不代作者宣称完成。 |

## 待完成的判断

1. 本次没有重新核查 ReAct、SWE-bench、tau-bench、AgentDojo 等外部全文或最新工作；
   [2026-09-08 定向核查](related-work-audit-2026-09-08.md)明确不是全面新颖性证明。
2. JOSS 软件稿与拟投 SCIE 实证论文是不同产物。目前没有足以支持 SCIE 效果主张的
   新真实数据或冻结实验协议；不得把此软件稿直接改标题后当作完成的 SCIE 实证论文。
3. 投稿前须由作者核实署名、机构、ORCID、引文、AI 使用声明、软件版本与最终全文；
   新发布版本的 DOI 和原始证据应与提交稿对应。本轮只修订可核实措辞，不代签声明。
