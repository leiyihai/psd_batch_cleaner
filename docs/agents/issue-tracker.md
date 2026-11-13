# Issue tracker：本地 Markdown

本仓库是基于上游项目的本地改造，GitHub origin 不是本项目的工单系统。
规格、工单及讨论均在本地维护；发布工单不涉及远端操作。

## 文件约定

- 每项功能：`.scratch/<feature-slug>/`
- 规格：`.scratch/<feature-slug>/spec.md`
- 工单：`.scratch/<feature-slug>/issues/<NN>-<slug>.md`
- 每张工单独立文件，从 01 开始，按依赖顺序编号。
- 工单顶部记录 Status 和 Blocked by。
- Status 使用 `triage-labels.md` 中的状态名称。
- Blocked by 列出前置工单的编号和标题；无依赖时明确标注。
- 讨论追加到文件底部的 `## Comments`，保留已有记录。

## 技能操作映射

- “发布到 issue tracker”：创建相应本地 Markdown 文件。
- “获取工单”：读取对应工单文件及其 Comments。
- “设置标签”：更新本地工单的 Status，不创建远端标签。
- “执行可开始工单”：只选择前置工单均已完成的任务。
- 完成记录及验收结果写入工单，不能仅凭 ready-for-agent 判断已完成。

创建工单不代表批准执行；遵循用户对拆分、发布和实施的确认范围。
未经用户明确要求，不向上游创建 Issue、PR 或推送代码。
