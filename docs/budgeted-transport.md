# 单次计费传输桥接 v1

## 实施契约

`send_budgeted(request, timeout, ledger=..., request_id=..., episode_id=...,
operation=..., budget=..., transport=...)` 显式处理一次物理发送，不自动重试。
`AttemptBudget` 固定正整数总 token 保守上界和输入/输出 USD/百万 token 费率；
费率为非负十进制字符串（不接受浮点、指数或分数）。所有金额按单请求向上取整到
nano-USD，预留为 token 上界乘较高费率，使用精确有理数中间计算。

- 先完成配置校验和持久 reserve，只有首次 True 才调用注入的 transport 一次。
  重复 ID、限额不足、未知阻断、账本读写错误均不能放行。
- 成功 JSON 必须含严格有效的 prompt/completion 用量，total 可由两项相加；矛盾、
  bool、负数等无效，只有 total 不足以定价。先结算，再把原响应交给调用方。
- 超过预留仍如实结算并抛错；后续新请求由账本阻断。费用是固定费率估算，不是账单。
- 超时、HTTP 异常/非 2xx、无效 JSON、缺失用量保留整笔 unknown 并抛安全错误；
  不记录原始异常、URL、请求、响应或凭据。不把 HTTPError 透传给兼容回退逻辑。
- 写入失败不交付响应；标记 unknown 失败时原 pending 仍占用预算，不自动恢复或清零。
  KeyboardInterrupt/SystemExit 尽力标记 unknown 后原样退出；硬崩溃仅能留下 pending。

## 适用范围与未完成项

这是供调用方显式接入的桥接函数，不是 CLI 的默认传输，也不是已完成的统一引擎集成。
transport 必须不做内部重试或额外计费发送；v1 不审计第三方 transport 内部行为。
仅适用于完整非流式、上述双费率能够覆盖的 chat usage；模型列表等无 usage 响应不能
被推断为免费。缓存/额外工具/其他计费项目需先单独建模，不可直接用于本函数。

调用方负责冻结并绑定正确模型/费率/计费语义、保守输入加输出 token 上界、稳定且不含
秘密的 ID。预算不会自动验证 tokenizer 上界、请求 payload 或模型与计划摘要的绑定。
action/preflight/fallback 每一次发送均需显式分配 ID；unknown 不允许自动回退重试。
重启后不能用新 ID 代替旧 pending 重发；完整恢复协调和供应商对账仍待实现。

本轮仅使用注入离线响应，不读取密钥、不发送 API 请求、不新增实测研究数据。
旧 CLI 仍可能绕过本桥接；安全凭据、固定设计、全路径集成、累计账单核对、24 episode
上限与恢复验收完成之前，不解锁真实采集。缺失旧账本不能新建并声称历史消费为零。
