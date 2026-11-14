# PSD Batch Cleaner · PSD 批量瘦身工具

基于 Python 和 `psd-tools` 的 PSD/PSB 深度清理项目：删除主文档及受支持嵌入式智能对象中的 Photoshop XMP `DocumentAncestors`（文档祖先元数据），生成独立瘦身副本。**正常清理不需要启动或调用 Photoshop。**

> **当前为开发阶段，不是已完成的桌面应用。** 工单 01–03 已完成约定验收，已提供最小中文串行窗口；04–08 的递归选项、安全停止、完整结果/导出及整体验收和并行模式尚未实现；这些验收不构成任意文件绝对无损或可直接无人值守生产运行的承诺。

## 当前能力与边界

- 递归清理实际内容为 PSD/PSB 的嵌入式智能对象；不跟随外链源文件。
- 只删除文档祖先元数据，不整体删除 XMP，不合并、栅格化图层或重新编码像素。
- 输入、输出目录独立且不可相互包含，原稿不覆盖；新副本保留输入子目录结构。
- 非 PSD/PSB 嵌入内容原样保留，明确标记“部分清理”；结构或校验失败时不发布修改结果。
- 完整成功或无需清理的文件，在源内容、规则和输出校验均未变化时可增量复用；部分清理和失败不作为完整成功复用。
- 大文件主路径使用文件区间补丁和未修改区间逐块校验，不全量重序列化文档。当前发布机制要求输出文件系统支持硬链接（如 NTFS）。
- 图层记录元数据与紧凑通道索引合计限128 MiB，不把外层像素通道载荷误算成记录；通道仍校验边界/压缩头并原样复制。见 [真实大通道拒绝修复](docs/large-layer-channel-fix.md)。兼容性规则已更新为v4，旧缓存将重验，已打开的窗口需重启。

四份真实样本已完成约定的结构、渲染及编辑保存重开验收，含真实嵌套、共享实例和原生嵌入 PSD；其中三份 0.91–2.80 GB 文件已有自动保真与资源测量证据，峰值工作集约 162–200 MiB。未知数据样本已验证嵌入/独立文档保留图层、原始未知载荷逐字节保留及损坏拒绝后继续批次。详见 [01 最终验收](docs/ticket01-closeout.md)、[02 最终验收](docs/ticket02-closeout.md)。**Python 不通过丢弃未知内容消除 Photoshop 警告，清理稿在旧 Photoshop 中仍可能报警。**

## 快速开始（Windows）

在项目根目录执行（本机当前为 `E:\psd_batch_cleaner`）。以下命令不依赖该绝对位置；目录职责和历史迁移说明见 [项目布局](docs/project-layout.md)。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m prototype.gui
```

窗口提供目录填写/浏览、开始、阶段与当前文件、基本结果及错误详情。**目前只扫描输入目录当前层级，不包含子目录；嵌入式智能对象仍按既有规则深度清理。** 运行中参数锁定，尚无停止按钮，关闭操作提示等待本轮安全完成。Tkinter/ttk随带Tcl/Tk的Python提供，无需额外GUI包；精简Python缺少该组件时需先安装Tcl/Tk。

非交互串行入口仍可使用：

```powershell
.\.venv\Scripts\python.exe -m prototype.batch --input "D:\输入" --output "D:\独立输出"
```

CLI 默认扫描子文件夹，识别 PSD/PSB。每次运行创建独立输出子目录；增量命中返回历史输出引用，并不在本轮重复复制一套结果。请避免在处理期间修改输入文件。

首次使用请先备份素材并用少量副本验证。正常清理只需 `requirements.txt`；开发、资源测量及可选 Photoshop 验收使用 `requirements-dev.txt`。

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports --follow-imports=silent --check-untyped-defs prototype/file_cleaner.py prototype/batch.py prototype/acceptance.py prototype/host_acceptance.py prototype/gui.py
```

普通自动测试不调用 Photoshop；真实Tk控件测试需要Tcl/Tk和可用桌面，无显示时明确跳过，不视为GUI验收通过。真实样本、资源测量和宿主验收的命令及安全要求见 [真实文件验收记录](docs/real-file-acceptance.md)。宿主验收必须显式执行，使用已有且无文档的空闲 Photoshop 会话；watchdog 退出不等于取消 Photoshop 脚本，超时后不得自动重试。

## 项目导航

| 路径 | 用途 |
| --- | --- |
| `prototype/` | 共享Python清理/批处理、最小窗口（`python -m prototype.gui`）及验收模块 |
| `tests/` | 自动回归测试 |
| `docs/` | 当前验收记录、历史验证、架构决策及协作配置 |
| `GLOSSARY.md` | 领域术语 |
| `.scratch/psd-batch-cleaner/` | 唯一完整规格及本地工单 |
| `legacy/photoshop/` | 独立保留的旧 JSX 工具及参考资料，不是 Python 清理依赖 |
| `.prototype-data/` | 被 Git 忽略的本地样本、验收证据和诊断工具 |
| `测试psd比对/` | 被 Git 忽略的用户原始素材与 JSX 参考集 |

- [目录布局与重命名说明](docs/project-layout.md)
- [真实文件早期验收记录](docs/real-file-acceptance.md)：保留当时的失败与资源测量记录
- [01 最终验收](docs/ticket01-closeout.md)、[02 最终验收](docs/ticket02-closeout.md)：内容安全结论与支持边界
- [03 最终验收](docs/ticket03-closeout.md)：最小窗口、共享事件、启动命令及真实GUI冒烟
- [历史小样本验证](docs/prototype-validation.md)：早期记录，不代表当前批处理限制
- [文件区间补丁 ADR](docs/adr/0001-stream-metadata-patches.md)
- [规格与工单导航](docs/spec-psd-batch-cleaner.md)
- [旧 JSX 使用说明](legacy/photoshop/README.md)

## 项目来源

本项目从 Photoshop Deep Cleaner Plus 的 JSX 工具演进而来，当前主方向为无需 Photoshop 的 Python 批量清理。

- 原项目：<https://github.com/julysohu/photoshop_deep_cleaner>
- 原作者：<https://github.com/julysohu>

Git 历史、原有 JSX 脚本与参考资料均保留。JSX 上游来源为 [Photoshop Deep Cleaner Plus](https://github.com/MisakaCirno/photoshop_deep_cleaner_plus)；当前开发仓库为 [leiyihai/psd_batch_cleaner](https://github.com/leiyihai/psd_batch_cleaner)。本项目规格和工单在本地 Markdown 维护，不使用上游或开发仓库的 GitHub Issues 作为工单系统。
