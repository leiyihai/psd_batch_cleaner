# PSD/PSB 深度瘦身工单索引

[完整规格](spec.md)是本功能唯一完整规格。以下八张工单的粒度与依赖已由用户确认；本地工单及验收记录为实时进展来源，不使用远端工单系统。

## 当前进度

- **01 已验收完成（8/8）**：四份真实样本最终分类及证据见 [最终验收记录](../../docs/ticket01-closeout.md)。工单以 `Completion: completed` 和完成记录表示完成，triage Status 本身不表示完成。
- **02 为 `ready-for-agent`，已复现、验收中（2/7）**：CC 2020 进入 `大厅v2.3.psd` 的“组 2083”（ID 556）时已捕获真实未知数据警告；正常 Python 的问题文件＋后续正常文件批次通过。仍待该分支保留图层/可编辑性/视觉及主文档场景验收，见 [复现记录](../../docs/ticket02-warning-reproduction.md)。
- **03–08 未开始**：01 的前置条件已满足，但 03 仍被 02 阻塞；不越过它实施 GUI。

| 编号 | 工单 | Blocked by |
| --- | --- | --- |
| 01 | [真实 PSD/PSB 深度清理与大文件验收](issues/01-real-file-deep-cleaning.md) | 无 |
| 02 | [未知数据文档不中断批处理，禁止自动拼合](issues/02-unknown-data-layer-safety.md) | 无 |
| 03 | [最小可用中文 GUI：选择目录并完成串行瘦身](issues/03-minimal-serial-gui.md) | 01、02 |
| 04 | [GUI 递归扫描与子目录结果映射](issues/04-recursive-directory-mapping.md) | 03 |
| 05 | [安全停止、单文件失败后继续与任务异常反馈](issues/05-safe-stop-and-failure-flow.md) | 03 |
| 06 | [GUI 增量清理：可靠跳过未变化文件](issues/06-incremental-cleaning-ui.md) | 03 |
| 07 | [逐文件结果、真实瘦身统计与报告导出](issues/07-results-and-report-export.md) | 03 |
| 08 | [串行桌面版本整体验收与定期运行入口](issues/08-serial-release-acceptance.md) | 04、05、06、07 |

## 执行规则与初始 frontier

- 八张工单初始 Status 均为 `ready-for-agent`，表示已明确需求，不代表依赖已解除、已获准实施或已完成。
- 初始无前置工单的候选项为 **01、02**；当前 01 已完成，02 已定位真实嵌入警告。每次重试前须确认模态窗口已取消且会话安全，下一步仅在新隔离副本上验证该分支，不直接对原稿运行会自动保存的旧 JSX。
- 02 验收需要能复现未知数据警告的真实文件；截图不足以关闭工单，材料缺失时记录待补信息。
- 前置工单的完成必须有验收证据与明确完成记录。依赖未解除时不开始后续工单。
- 讨论追加到对应工单的 Comments，不以本索引替代工单的状态和完成记录；工单更新后本索引的“初始”说明不代表实时状态。
- 本地工单状态约定见 [triage 状态](../../docs/agents/triage-labels.md)。

## 后续范围

先完成串行桌面版本验收，再决定并行方案及合理并行数；本轮不创建或执行并行处理工单。
