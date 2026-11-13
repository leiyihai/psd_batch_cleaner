# PSD/PSB 深度瘦身工单索引

[完整规格](spec.md)是本功能唯一完整规格。用户已确认以下八张工单的粒度与依赖；本次仅发布本地文档，未开始实施、未将任何工单记为验收完成，也未操作远端。

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
- 当前无前置工单的候选项为 **01、02**；实施仍需遵循用户授权范围。二者可并行，但需协调共享样本与清理核心的修改。
- 02 验收需要能复现未知数据警告的真实文件；截图不足以关闭工单，材料缺失时记录待补信息。
- 前置工单的完成必须有验收证据与明确完成记录。依赖未解除时不开始后续工单。
- 讨论追加到对应工单的 Comments，不以本索引替代工单的状态和完成记录；工单更新后本索引的“初始”说明不代表实时状态。
- 本地工单状态约定见 [triage 状态](../../docs/agents/triage-labels.md)。

## 后续范围

先完成串行桌面版本验收，再决定并行方案及合理并行数；本轮不创建或执行并行处理工单。
