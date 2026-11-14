# PSD Batch Cleaner · PSD 批量瘦身工具

基于 Python 和 `psd-tools` 的 PSD/PSB 深度清理项目：删除主文档及受支持嵌入式智能对象中的 Photoshop XMP `DocumentAncestors`（文档祖先元数据），生成独立瘦身副本。**正常清理不需要启动或调用 Photoshop。**

> **当前为开发阶段，不是已完成的桌面应用。** 工单 01–07 已完成约定验收，已提供支持递归选项、安全停止、增量复用、结果统计与 JSON 导出的中文串行窗口；08 的最终整体验收及后续并行模式尚未完成；这些验收不构成任意文件绝对无损或可直接无人值守生产运行的承诺。

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

窗口提供目录填写/浏览、开始、阶段与当前文件、基本结果及错误详情。**“包含子文件夹”默认勾选，关闭后仅扫描输入目录当前层级；嵌入式智能对象仍按既有规则深度清理。** 扫描完成后显示本轮文件总量与已处理数量；扫描失败明确显示任务异常，不发布不完整的总量。 运行中参数锁定；点击“安全停止”后显示“请求停止”，当前文件完成或安全失败后不再启动下一文件，释放任务资源后才显示“已停止”。扫描中请求停止会等待本次扫描安全返回，不启动文件处理。停止不显示为全部完成；关闭操作仍提示安全停止或等待，不强制中断写入。Tkinter/ttk随带Tcl/Tk的Python提供，无需额外GUI包；精简Python缺少该组件时需先安装Tcl/Tk。

非交互串行入口仍可使用：

```powershell
.\.venv\Scripts\python.exe -m prototype.batch --input "D:\输入" --output "D:\独立输出"
```

**CLI 退出码：`0` 正常、`1` 单文件失败、`2` 任务异常、`3` 部分清理**，任务异常优先、文件失败优先于部分清理；非 0 不应被外部计划任务当作完整成功。stdout/stderr 为 UTF-8，正常终态的最后一行 stdout 为 JSON；任务被外围强杀/超时、缺少终态时也不能视为通过。安装、完整退出码约定、任务计划程序参数、日志与故障复查见 [串行运行指南](docs/serial-running.md)。本工具不自动注册定时任务。

CLI 默认扫描子文件夹，识别 PSD/PSB 及混合大小写扩展名；传入 `--no-recursive` 仅扫描当前层级（`--recursive` 显式开启）。GUI 与 CLI 共用相同范围参数及扫描行为，不进入符号链接或 Windows 目录联接。每次运行创建独立输出子目录；增量命中返回历史输出引用，并不在本轮重复复制一套结果。请避免在处理期间修改输入文件。

重复运行会完整读盘计算源文件及历史副本的 SHA-256，不承诺零耗时跳过。GUI 显示“检查变化”，命中时显示“未变化”、历史复用数量与实际历史路径；选择结果可查看“复用历史副本”说明。**本轮目录不一定是一套完整副本**，历史命中不会重复解析、清理、保存或复制到本轮目录，实际输出以逐文件路径为准。源内容（包括同大小同时间修改）、规则变化、历史输出丢失或哈希不符时生成新副本；失败和部分清理下次仍重试。

`.cleaner-cache.json` 格式损坏、必要字段不完整或输出引用越界时明确报任务异常，保留原记录，不自动忽略或覆盖损坏缓存，也不读取越界历史副本。需要恢复时，先确认没有任务使用该输出目录，备份并检查缓存；若确需重建，可将该缓存文件改名留存后重新运行（原稿和历史输出无需删除）。重建会重新清理生成新副本，不自动找回旧记录。运行期间不要修改输入；检测到哈希、历史校验或清理期间的输入变化时拒绝复用/发布，但不承诺对持续写入提供事务快照。

结果表选择文件后，可在可滚动详情中查看完整来源/输出路径、已知前后大小、精确字节与易读单位差异、文档数量、跳过外链、未处理内容及错误；未知值明确显示“未知”，不会补零。任务结束后汇总成功、无需清理、未变化、部分清理、失败五类数量。

**本轮收益仅统计本轮实际发布、大小已核实且文件状态非失败的结果**，包含部分清理的实际体积差异，但不把它算作完整成功；历史复用、失败（即使已有输出）、未发布和大小未知均不重复计入。净减少为负数表示体积增加。大小以处理时的已核实记录为准，不是对之后外部修改的实时监控；文档数量含已检查但无需清理的文档，删除字段数不代表完整清理成功。

任务结束或异常后可点击“导出 JSON…”，选一个**尚不存在**的文件名。导出采用 UTF-8 JSON，包含原始逐文件记录、同口径汇总、收益说明及本轮任务状态/已处理数/总量/错误/原报告路径；不是表格格式，不执行用户文本中的公式。已有目标一律拒绝覆盖；导出取消或失败不改变批处理结果，可更换文件名或修复权限后重试。导出在后台执行，期间不能启动新任务或关闭窗口中断写入。导出任务状态 `finished` 表示本轮处理结束，不代表没有失败或部分清理，仍须核对分类数量和逐文件状态。

坏文件或校验拒绝会记录原因并继续后续文件；输出读写、发布、缓存或报告等基础设施故障会终止任务并明确提示异常。报告更新失败时保留上次成功保存的报告，界面仍展示本次已发布的输出；该报告可能不含最后展示的文件，不应当作全量成功清单。此时 JSON 导出保留界面收到的实际记录及明确的任务异常/未完成总量，因此可以比最近保存的 `report.json` 多几行；自动 `report.json` 继续保持原逐文件列表格式，JSON 导出另包含任务与统计信息。恢复后可再次开始，仍有效的历史结果按既有缓存策略复用。

同一输出目录使用 `.cleaner.lock` 互斥。遇到“已有任务或遗留锁”时，先等待该输出目录的任务结束；若程序曾异常退出，**必须确认没有任何任务仍在使用该输出目录后**才可手动移除遗留锁。PID 仅供参考，不能仅凭它自动判断锁已失效；本工具不提供强制解锁，不结束 Photoshop 或其他用户进程。

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
- [04 最终验收](docs/ticket04-closeout.md)：递归开关、目录映射、文件总量进度及扫描隔离
- [05 最终验收](docs/ticket05-closeout.md)：安全停止、文件失败与任务异常分流、锁冲突及恢复重启
- [06 最终验收](docs/ticket06-closeout.md)：增量复用说明、缓存安全校验、失效及输入并发修改验收
- [07 最终验收](docs/ticket07-closeout.md)：完整详情、保守收益统计、中文 JSON 导出与故障恢复
- [08 整体验收](docs/ticket08-closeout.md)：同一套真实样本的 GUI/CLI、Photoshop、资源与超时记录
- [串行运行指南](docs/serial-running.md)：安装、外部定期执行、退出码、日志和遗留锁处理
- [历史小样本验证](docs/prototype-validation.md)：早期记录，不代表当前批处理限制
- [文件区间补丁 ADR](docs/adr/0001-stream-metadata-patches.md)
- [规格与工单导航](docs/spec-psd-batch-cleaner.md)
- [旧 JSX 使用说明](legacy/photoshop/README.md)

## 项目来源

本项目从 Photoshop Deep Cleaner Plus 的 JSX 工具演进而来，当前主方向为无需 Photoshop 的 Python 批量清理。

- 原项目：<https://github.com/julysohu/photoshop_deep_cleaner>
- 原作者：<https://github.com/julysohu>

Git 历史、原有 JSX 脚本与参考资料均保留。JSX 上游来源为 [Photoshop Deep Cleaner Plus](https://github.com/MisakaCirno/photoshop_deep_cleaner_plus)；当前开发仓库为 [leiyihai/psd_batch_cleaner](https://github.com/leiyihai/psd_batch_cleaner)。本项目规格和工单在本地 Markdown 维护，不使用上游或开发仓库的 GitHub Issues 作为工单系统。
