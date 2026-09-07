# Reliable pairing / 可靠配对

Engineering analysis pairs observations by `(task_id, fault, pair_id)` across
the two selected providers. Assign a nonempty string `pair_id` in the design
before execution, shared by the matching baseline and treatment observations.
Never infer pairing from outcomes, row order, or completion time.

```json
{"results": [
  {"task_id": "a", "fault": "timeout", "pair_id": "repeat-1", "provider": "basic", "success": false},
  {"task_id": "a", "fault": "timeout", "pair_id": "repeat-1", "provider": "enhanced", "success": true}
]}
```

If any selected row supplies `pair_id`, every selected row must supply it.
Duplicates and missing or mismatched counterparts raise `ValueError`.
Legacy input without IDs remains supported only for one observation per
provider/task/fault cell. For repeated legacy observations, recover IDs from the
frozen design or source artifacts, not row positions. If recovery is impossible,
paired analysis is unsupported. Outcomes must be booleans or integer 0/1.
Contrast reports include only the two selected providers.

中文：重复实验须提前按设计分配配对编号。同一任务、故障和重复条件下的两种方法
共用 `pair_id`，合并或打乱日志不会改变结果。旧格式每组只有一次观测仍可使用；
重复观测缺编号、编号重复或不匹配会报错。未知、缺失和字符串 `"false"` 不会被
自动当成成功或失败。旧记录须从原始设计恢复编号，不能按行号补编号。

This remains an engineering diagnostic, not a confirmatory statistical pipeline.
The percentile bootstrap resamples individual pairs. Repeats within the same
task can be dependent; formal studies require a frozen estimand, missingness
policy, and design-appropriate clustered or hierarchical analysis. Constant
observed differences can yield a zero-width interval without proving certainty.

本模块仍用于工程诊断。当前 bootstrap 按配对观测重采样，同一任务的重复可能相关；
正式论文须按设计采用聚类或分层分析并预先固定目标效应和缺失值规则。
零宽区间不代表总体效果没有不确定性。
