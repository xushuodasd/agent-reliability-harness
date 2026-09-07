# Plan-based cluster analysis

`pilot_harness.cluster_analysis` estimates one prespecified scaffold contrast
within one model and one fault condition. It joins outcome records to the frozen
`compile_plan` output by episode ID. It rejects duplicate/unplanned results and
invalid plan hashes; labels come from the plan, never result ordering.

Input outcomes are a JSON list, for example:

```json
[{"episode_id": "use-the-actual-plan-episode-id", "outcome": "PASS"}]
```

Export `episode_id` and `outcome` from the machine acceptance long-form records
after artifact validation. Preserve UNKNOWN and every failed attempt; do not
select the best retry. The plan hash validates content consistency only. It is
not proof of a public timestamp, independent validation, or real-model origin.

```shell
python -m pilot_harness.cluster_analysis runs/study/plan.json runs/study/outcomes.json --model exact-model-id --baseline basic --treatment verified --condition timeout_committed_once --clusters runs/study/task-clusters.json --output runs/study/analysis.json
```

The cluster mapping is a JSON object from task ID to shared-template ID. Without
it, each task is a cluster; this assumes tasks are independent. Group variants
of the same template together. At least two clusters are needed to compute an
interval, but this computational minimum is not adequate scientific sample size.
Reports warn below 20 clusters; even above 20, simulation and design review are
needed. Do not infer adequate precision from a threshold alone.

## Estimand and missingness

For each task, average the treatment-minus-baseline difference across its planned
paired repetitions. Average those task means equally. The primary endpoint is
verified completion under the assigned budget: PASS=1; FAIL, UNKNOWN, and absent
records=0. This does not assert that unknown runs actually failed. Counts retain
UNKNOWN and MISSING separately for each arm. The planned denominator never shrinks.

`unknown_outcome_bounds` gives the worst/best possible true-success difference
if every unresolved baseline/treatment outcome were assigned adversely/favorably.
These are identification bounds, not confidence limits. If an entire pair is
unresolved, it contributes [-1,1]. Missingness can dominate a nominal improvement.

Resample complete clusters with replacement, carrying all tasks and repetitions
together. For unequal template sizes each resample divides summed task effects
by the number of sampled tasks. The 95% percentile interval concerns the verified
completion endpoint, not the unknown-outcome bounds. Constant observations may
produce a zero-width interval; no population certainty is implied.

This utility does not yet pool models or conditions, perform multiplicity
correction, estimate safety endpoints, or validate causal assumptions. Decide
the primary contrast, clustering, sample size, and reporting rules before
collecting confirmatory data. Use safety and cost analyses in addition to success.

## 中文说明

新模块先根据冻结计划按 episode ID 对齐观测，再在同一模型、同一故障条件内比较
两种脚手架。先算每项任务的平均差异，再对任务等权平均。重复次数不会凭空增加
独立样本量；同模板任务须通过 `--clusters` 归入同一组一起重采样。

主指标是“在既定预算内有证据确认完成”。未运行、基础设施异常和未知观测保留在
计划分母中，分别计数；它们没有确认完成，但不能据此说模型必然失败。报告同时
给出把未知结果按最不利/最有利情形处理后的差异范围，它不是置信区间。

模块可运行不等于研究达到发表要求。正式实验仍须完成任务与模板审计、方法对照、
统计覆盖率/精度检查、外部任务验证及真实来源审计。模拟数据仅能验证程序行为。
