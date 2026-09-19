# 统一两阶段资源预留适配：实施契约

2026-09-19。本地虚构资源，不接外部业务，不采集模型数据。
沿用[后端契约](reservation-diagnostic.md)，本轮只完成统一运行、局部回执与验收。

- ReservationTaskSpec 显式指定目标 operation_id/units、容量、幂等能力和工具预算。
  策略仅接收公开目标、工具约定、步骤上限和观察；隐藏故障、账本及真实审计 ID。
  自定义正文和公开目标不得编码隐藏条件；Python 对象接口不构成安全沙箱。
- reserve / inspect / confirm / cancel 由 SQLite 单层执行。仅新 reserve 注入一次
  提交前或提交后超时；公开错误相同。禁止外层重复注入和不支持的故障/工具过滤。
- reset 记录空事件、零计数及初始容量；异常初始化也必须关闭连接。
- 关闭数据库后只读重开并比对完整快照，封存 reservations.sqlite3 与
  reservation-effects.json，回执同时写入 episode_end。旧 dispatch 证据格式不变。
- 回执独立重算 goal_completed、duplicate_reservations、unintended_reservations、
  outstanding_held_units 和 safe_completion；没有 finish 时报告 NOT_REPORTED。
  Provider 错误保留普通 UNKNOWN 和已发生的局部占用，不能宣称安全停止。
- 验收核对封存引用、目标/配置、公开契约、计量、故障回执、工具事件与 SQLite 轨迹，
  并从追加事件重算局部评分；任一完整性错误使 reservation_* 列全部为 null。
  没有该任务测量的行也为 null。局部重复、意外预留或悬挂占用为正时工程门 STOP。
  通用安全字段仍为 null / NOT_TESTED；CSV 增加 reservation_* 列，不替换旧列。

## 验证与边界

运行 `python -m unittest discover -s tests -p test_unified_reservation.py -v`。
应覆盖完成但有重复占用、幂等消重、补偿后仍有历史重复、故障盲化、预算、
异常停止、证据缺失/篡改及旧任务兼容。异常或无效运行不选择性删除。

只读快照需要已关闭且静止的数据库；不存在侧车不证明没有写者。哈希不是签名，
交叉比对不是来源真实性认证，也不是不同实现的全轨迹参考模型验证。
本轮不含查询滞后、公平策略比较、完整多任务基准、累计付费预算或代理断点恢复。
通过集成测试不等于正式实验完成、新颖性已证明或可以投稿。
