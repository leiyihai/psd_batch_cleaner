# 项目布局与目录重命名

## 当前整理状态

工作目录现已位于 `E:\psd_batch_cleaner`，旧 JSX 和参考资料位于 `legacy/photoshop/`；当前 `.venv/Scripts/python.exe` 可运行测试和验收。01–03 的约定验收已完成，见 [01最终记录](ticket01-closeout.md)、[02最终记录](ticket02-closeout.md)、[03最小窗口验收](ticket03-closeout.md)。

下文保留早期迁移准备步骤。当前没有 `.prototype-data/relocated/` 派生目录，也没有完整169文件迁移清单的后验通过记录；不能把目录已改名或当前测试通过说成所有迁移计划均已执行。历史报告中的旧路径保持原样，后续验收使用各自记录的新隔离副本和派生报告。

## 迁移准备时的阻塞与操作说明（历史）

**当时文件布局整理已完成，根目录重命名尚未完成。** Windows 原子重命名返回 `WinError 32`（目录被其他进程占用）。当时仍为 `E:\photoshop_deep_cleaner_plus`，新目录尚未创建；没有强制结束进程，也没有移动或重建 `.venv`。

请结束当前代理会话，关闭占用项目的编辑器或终端窗口，然后在项目之外的 PowerShell 中执行：

```powershell
Set-Location E:\
Rename-Item -LiteralPath 'E:\photoshop_deep_cleaner_plus' -NewName 'psd_batch_cleaner'
```

若仍报告占用，请释放相应窗口/任务后再试，不强杀 Photoshop 或其他用户进程。成功后在 `E:\psd_batch_cleaner` 重新打开项目和代理会话，按 `.prototype-data/workspace-migration/HANDOFF.md` 继续：备份旧环境、用已缓存的冻结依赖离线重建 `.venv`、运行迁移校验器并复测。不要在新路径直接使用旧 pip/mypy 启动器。

迁移前，整理后的 27 项自动回归已通过。新根目录的文件保全校验、派生报告生成、环境重建与回归尚待执行，不能将准备脚本或旧测试结果当作这些步骤已完成。

## 名称与范围

项目名称为 **PSD Batch Cleaner（PSD 批量瘦身工具）**，本机根目录目标为 `E:\psd_batch_cleaner`，原名为 `E:\photoshop_deep_cleaner_plus`。用户已确认此次整理与重命名；它不改变清理规则、工单状态或 GUI 的实施顺序。

保留 `prototype` 包名，以兼容现有导入、测试和 CLI 命令。目录整理没有迁移为 `src/` 布局或重新实现清理逻辑；后续03已独立交付最小GUI，仍复用现有批处理。

## 目录职责

```text
psd_batch_cleaner/
├── README.md                     # 项目首页与 Python 使用入口
├── AGENTS.md / GLOSSARY.md        # 协作入口、领域术语
├── requirements*.txt             # 运行及开发依赖
├── prototype/                    # Python 清理、批处理与验收
│   ├── batch.py                  # GUI/CLI共享批处理、扫描参数和事件
│   ├── gui.py                    # 最小中文串行窗口（当前目录）
│   ├── file_cleaner.py           # 当前文件区间补丁路径
│   ├── cleaner.py                # XMP 清理、旧内存原型回归
│   ├── acceptance.py             # 真实文件自动验收和资源监测
│   ├── host_acceptance.py        # 显式 Photoshop 实机验收
│   └── verify_samples.py / photoshop_verify.py  # 历史小样本工具
├── tests/                        # 自动回归
├── docs/                         # 验收证据说明、ADR、代理配置
├── legacy/photoshop/             # 旧 JSX 工具，独立于 Python
│   └── reference/                # 原有调试说明和 PDF
├── .scratch/psd-batch-cleaner/    # 唯一规格、本地工单及依赖
├── .vscode/                      # 工作区相对路径调试配置
├── .venv/                        # 本地环境，不提交
├── .prototype-data/              # 本地证据，不提交
└── 测试psd比对/                  # 用户素材和 JSX 参考，不提交
```

旧根目录的五个 `.jsx`/`.jsxinc` 文件整体移动到 `legacy/photoshop/`，包含关系不变。`ReferenceDocumention/` 移到该目录下的 `reference/`；其中调试说明重命名为 `extendscript-debugger.md`，两个 PDF 保留原名。旧文件内容不变，运行方式见 [旧工具说明](../legacy/photoshop/README.md)。

VS Code 配置使用 `${workspaceFolder}`，不绑定本机盘符或某个 Photoshop 版本。Python 调试需要相应 Python/Debugger 扩展；旧 JSX 配置需要 Adobe ExtendScript Debugger 扩展并手动选择宿主。配置存在不代表已执行宿主调试。

## 本地证据目录

为了保持已记录的相对路径和证据来源，既有大文件与报告目录不整体搬到另一套层级：

| 路径（相对于 `.prototype-data/`） | 用途 |
| --- | --- |
| `original/`、`injected/`、`cleaned/`、`renders/`、根目录早期 JSON | 历史官方小样本及其验证结果 |
| `batch-output/` | 早期批处理结果 |
| `user-acceptance/` | 早期真实文件运行及宿主局部证据，不能混作最终自动报告 |
| `user-acceptance-final/20261113_194622_237572/` | 三份用户文件的最终自动报告及资源测量 |
| `host-diagnosis/` | 超时定位的阶段日志、实际 JSX、失败与通过证据 |
| `host-regression/` | 大厅单文件宿主回归，`hall-am-r4` 为本轮最后一次通过记录 |
| `tools/` | 本地一次性诊断和迁移工具，不属于产品运行链路 |
| `relocated/` | 根目录重命名后的派生可用报告及来源说明 |
| `workspace-migration/` | 迁移前校验清单、环境版本、校验结果和原环境备份 |

临时诊断脚本由 `.prototype-data/diagnose_host.py` 移至 `.prototype-data/tools/diagnose_host.py`，相应的项目根目录定位已更新。历史验收文档中的命令保留当时路径；后续使用新路径。该脚本会调用 Photoshop，仅限显式诊断，不要作为普通测试运行。

### 报告中的绝对路径

原始 `acceptance.json`、宿主报告、日志与实际 JSX 都作为历史证据原样保留，其内部可能仍包含旧根目录绝对路径。**不要批量替换它们，也不要将旧路径不存在误判为素材丢失。**

原迁移计划由工具在 `.prototype-data/relocated/acceptance.json` 生成最终自动报告的派生副本（当前尚未生成，不能直接运行此路径），仅重定位旧根目录下的路径，保留所有原验收结果；`_workspace_relocation` 记录原报告相对位置、SHA-256、旧/新根目录和迁移性质。另生成 `hall-acceptance.json`，用于仅选大厅的后续诊断。派生报告不是重新验收通过的证据，也不取代历史报告。

重命名后如需显式宿主验收，可将派生报告作为 `--report` 参数；输出必须为 `.prototype-data/relocated/` 下尚不存在的隔离子目录。仍须先人工确认 Photoshop 空闲、没有打开文档，不能因重命名自动运行宿主验收。

### 缓存和虚拟环境

增量缓存包含源绝对路径和历史输出位置。原缓存作为历史记录保留，不迁移缓存键、不伪造增量命中；重命名后旧缓存可能失效并重新处理，属于预期的安全行为。

Python 虚拟环境的激活脚本及控制台启动器可能嵌入旧路径，不能只测试 `python.exe` 能启动就认定全部可用。迁移时将旧环境保留在 `.prototype-data/workspace-migration/venv-before-rename/`，在新根目录重建 `.venv`，按迁移前冻结版本安装依赖。旧环境仅为回退材料，不再用于运行。

## 校验与安全边界

迁移前对 169 份素材、既有验收证据、JSX 脚本和参考资料建立大小及 SHA-256 清单，总计 8,195,233,153 字节。迁移后按明确的文件映射逐项验证；不会重新生成图片或通过改写报告掩盖路径问题。

迁移工具和结果留在 `.prototype-data/workspace-migration/` 与 `tools/`，不纳入 Git。完成后仍需运行 27 项自动回归、四个当前运行模块的 mypy、Python 编译检查和 CLI 帮助检查；这些检查不启动 Photoshop。

原稿、JSX 参考、已有输出、`.git` 和本地工单均保留。迁移准备阶段没有回滚未提交的宿主修复、向上游推送或关闭/结束 Photoshop，也没有因目录整理就将工单01标记完成。后续01、02的完成来自各自独立实机验收；本次按用户要求将剩余Git可见修改提交至用户开发仓库，不上传被忽略的本地素材或证据。
