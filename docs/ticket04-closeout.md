# Ticket 04：递归扫描与子目录映射验收

## 交付范围

- GUI 新增默认开启的“包含子文件夹”；关闭后仅处理当前层级。与目录字符串一起在启动时捕获布尔值，运行期间禁用选项，后续程序性修改不影响已运行任务。
- GUI 与 CLI 继续共用 `batch.run(recursive=...)` 和同一扫描器。CLI 保留默认递归，新增 `--recursive` / `--no-recursive`。
- 处理前完整扫描所选范围，扫描成功后才发出 `scanned(total)`；逐文件与终态事件包含 `completed`、`total`。扫描中显示不定进度，完成扫描后显示可靠的文件计数与确定进度；不提供伪造的阶段百分比或剩余时间。
- 保留原有相对路径映射、独立运行目录和增量复用：缓存命中仍引用历史输出，不在本轮重复复制。不同子目录的同名文件互不覆盖。
- 继续拒绝输入输出相互包含、排除符号链接。额外修复 Windows 目录联接（junction）会进入历史输出的漏洞，递归扫描也跳过目录联接。
- 扫描异常发送任务错误、释放锁，不发送不完整总量或“处理完成”；原稿与历史输出保留。空的嵌套目录树明确显示 `0 / 0`。

没有改动清理算法、规则版本、保真门禁、Photoshop 交互；安全停止与完整报告界面仍属后续工单。

## 测试接缝与红→绿

用户确认共享批处理入口、真实 GUI 操作、隔离目录端到端三个接缝后实施。

1. `test_scan_total_precedes_processing_and_progress_counts_selected_scope` 先因没有 `scanned` 事件失败，再补完整扫描和计数事件；验证递归开关及 `selected_files` 的真实总量。
2. `test_recursive_option_defaults_on_maps_nested_names_and_freezes_scope` 先因没有 GUI 选项失败，再补默认值、捕获与控件禁用；真实 Tk 测试发现停止进度动画会清零，修正为结束时只停止不定进度，保留确定进度终值。
3. CLI 测试先因不识别 `--no-recursive` 失败，再补参数传递。
4. Windows 真实 junction 测试先复现历史 PSD 被重新清理，再增加联接排除，测试转绿。
5. 补充既有安全行为回归：双方包含、符号链接、混合扩展名、中文/空格、多层同名文件、空目录、两种文件系统扫描故障、任务错误保留原稿及历史输出。权限/设备错误在 `os.scandir` 文件系统边界注入，不模拟清理模块。
6. Spec 审查发现 `os.walk` 会吞掉目录项 `is_dir()` 的错误。新增文件系统 `DirEntry` 边界故障测试，先复现未抛错且误报完成，再改为 `os.scandir` 加显式不跟随链接的 `stat`、迭代目录遍历；目录项分类失败向上传播，不静默遗漏子树。

测试文件：`tests/test_batch_gui_contract.py`、`tests/test_gui.py`。

## 可见窗口端到端冒烟

修正扫描器后最终复跑的隔离证据目录：`.prototype-data/ticket04/20261114_133422_928995/`，含 `evidence.json`、两轮报告、输出和 `gui-True.png` / `gui-False.png`。可见窗口使用正式 `create_window()`，未调用 Photoshop、未访问用户素材。

输入包含当前层级 `同名.PSD`、`子目录/同名.PSD`、`子目录/多层/设计.PsB`、忽略的 JPG 和空目录。第一轮默认递归，真实处理 3 个文件、显示 `3 / 3`，保留全部相对路径。通过真实复选框关闭后第二轮仅处理 1 个文件、显示 `1 / 1`；返回未变化及历史输出引用，保留两轮独立报告和首轮输出。全部输入字节不变。截图与事件循环均实际运行，不将无显示跳过视作通过。

## 最终验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports --follow-imports=silent --check-untyped-defs prototype/file_cleaner.py prototype/batch.py prototype/acceptance.py prototype/host_acceptance.py prototype/gui.py
git diff --check
```

- 全套 **64 项：59 通过、5 跳过**；10 项真实 Tk 测试全部实跑通过。
- 4 个跳过是既有真实样本/Photoshop opt-in；另 1 个是本机缺少创建符号链接权限（WinError 1314），不声称已实跑真实 symlink 场景。符号链接排除沿用既有逻辑，Windows 真实目录联接测试实际通过；嵌套空目录另由 GUI 测试实跑。
- 上述 5 个入口/相关模块 mypy 通过，差异空白检查通过。
- 另尝试扩大到整个 `prototype/` 的 mypy，发现未修改的 `photoshop_verify.py`、`verify_samples.py` 共 6 个既有类型错误；这两文件相对本轮基点无差异，本轮不扩大修复范围，不声称全目录类型检查通过。

首轮双轴审查：Standards 无硬性违规，1 项低优先级测试故障辅助代码重复的判断建议；保留两处短小的局部故障注入以便独立阅读，不引入跨测试文件的辅助层。Spec 发现 1 项目录项分类错误被吞的问题，已按上述红→绿补齐并复跑全部验证。修正后的复核见工单完成记录。
