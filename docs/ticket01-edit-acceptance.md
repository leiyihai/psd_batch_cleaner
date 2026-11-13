# 工单 01：嵌入内容编辑保存与共享实例关联验收

## 结论与边界

本轮在用户确认继续后，使用 Photoshop 21.2.12 的空会话，对三份已授权真实样本的既有 Python 输出制作新隔离副本，完成深层嵌入编辑、逐层保存、主文档保存重开，以及共享实例关联验证。**三份样本的本轮编辑/关联协议均通过，但工单 01 仍未全部验收完成。**

这里的实际编辑是创建具有唯一名称的隐藏普通图层，不是只打开嵌入内容或修改 XMP。它验证图层新增和内容保存的可用性，不宣称任意绘画、滤镜或全部嵌入分支都已验证。每份仅取最深的一条原生 PSD/PSB 嵌入链，以及根文档中的一对共享原生嵌入实例。

大厅在保存嵌入内容后，相对初始根渲染发生局部差异；同样的差异在“不新增任何图层、仅执行相同嵌入保存”的对照中也发生，且编辑结果与对照逐像素一致。**这排除了差异仅由新增隐藏测试图层导致，但尚未逐层解释 Photoshop 重渲染或缓存更新的具体机制，不能宣称编辑保存全过程与初始图像无差异。** 另外两份样本相对初始根渲染也一致。

尚缺原生嵌入 PSD 的真实样本，未使用合成容器或新造宿主文件替代真实样本要求。本轮不解除 GUI 前置依赖，不涉及工单 02。

## 测试边界和协议

新增显式入口 `prototype.host_edit_acceptance`，其 JSX 为 `prototype/host_edit_acceptance.jsx`。正常清理不导入或调用这个入口。入口只接收单样本报告，要求已经运行且无打开文档的 Photoshop；输出目录必须位于报告目录下且尚不存在，不能与原稿或既有 Python 结果目录相互包含。

每份运行以下协议：

1. 复制既有 Python 结果，校验复制件 SHA-256；根据真实嵌入内容规划最深链及共享实例 ID。
2. 在独立副本上运行无编辑对照：打开同样的嵌入链和共享内容，不新增图层，逐层保存，再保存主文档并重新打开。
3. 在另一独立副本上先确认唯一标记不存在，再在最深嵌入文档新增隐藏普通图层，逐层保存；再次从父文档打开内容，核对标记存在。
4. 从共享实例 A 打开内容并新增另一个唯一隐藏普通图层，保存后从实例 B 打开，核对同一标记可见于图层结构。
5. 保存主文档至新文件并重开，再核对深层标记和 A/B 两个共享实例中的标记。
6. 比较编辑后保存前及重开后的根 PNG 解码像素，并比较最终编辑结果与无编辑对照；同时单独记录与初始渲染的比较，不隐藏其差异。
7. 检查既有 Python 输出指纹不变、结束文档数为 0。
8. opt-in 集成测试独立使用 psd-tools 解析实际保存文件：根图层 ID/名称/可见性与隔离输入一致；最深内容有唯一隐藏标记；A/B 的嵌入 ID 和内容字节相同，且内容中保留唯一隐藏共享标记。

真实集成测试位于 `tests/test_host_edit_acceptance.py`。普通测试默认跳过它，不连接 Photoshop；只有设置两个显式环境变量才执行。宿主脚本任何条件不满足即抛错，不把单纯打开成功解释为编辑成功。

## 三份样本的最终结果

本地报告根目录：`.prototype-data/ticket01-continuation/`。单样本派生报告的来源与重定位性质见 [上一轮记录](ticket01-host-continuation.md)。

| 样本 | 最深编辑链 | 共享实例图层 ID | 编辑保存/重开及共享检查 | 与无编辑对照渲染一致 | 与初始渲染一致 | 最终证据目录 |
| --- | ---: | --- | --- | --- | --- | --- |
| 大厅.psb | 4 | 2724、2590 | 通过 | 是 | 否 | `sample-1/edit-final-r3/` |
| 大厅v2.3.psd | 3 | 1873、1874 | 通过 | 是 | 是 | `sample-2/edit-final-r3/` |
| 通行证V3.psb | 3 | 1193、1194 | 通过 | 是 | 是 | `sample-3/edit-final-r3/` |

三份运行的编辑后保存前/重开渲染均一致，既有 Python 输出指纹均未变，结束文档数均为 0。含独立文件解析的单文件真实集成测试逐份通过；首次 `edit-final-r1/` 约耗时 43、27、36 秒。这不是批处理性能重测，不替代此前内存和耗时记录。

每份目录包含：`host-edit-report.json`、`plan.json`、`actual-script.jsx`、`host-stages.log`、隔离输入、编辑后的保存文件、三个阶段 PNG，以及 `no-edit-control/` 下的独立对照计划、脚本、日志和文件。用户文件及完整本地证据不提交 Git。

## 失败 → 对照 → 通过证据

- 首先新增 opt-in CLI 集成测试，入口尚未实现时因模块不存在失败。
- 大厅 `sample-1/edit-r1/`：深层编辑和共享检查均完成，但与初始根渲染比较失败，整次命令退出 1。没有把这个失败改记为通过。
- `sample-1/no-edit-save-control-r1/`：一次性最小对照不新增任何图层，仅保存相同嵌入内容，也出现根渲染差异。差异范围为 `(1191, 422, 1234, 456)`；它与失败轮的编辑结果逐像素相同，二者差异区域为空。
- 正式协议加入独立无编辑对照，以及编辑后保存前/重开的比较；保留 `initial_cached_render_unchanged` 诊断字段，大厅仍明确为 false，不通过删除像素检查掩盖问题。
- 加入独立保存文件解析后，三份样本在 `edit-final-r1/` 分别完整复跑通过。

代码审查发现 COM 预检原先未纳入 watchdog，且超时证据写盘失败可能阻止退出。现将 COM 初始化、连接、文档数读取及清理纳入 120 秒时限，并以 `finally` 保证写盘失败仍退出；测试对子进程另设 140 秒外围时限。安全补强后在 `edit-final-r2/` 逐份复跑，再补齐 COM 清理时限并在 `edit-final-r3/` 最终逐份复跑通过（约 43、28、35 秒）。

Standards 和 Spec 双轴审查未发现硬规范违反或新增规格偏差；审查指出的超时风险已修正。普通回归 27 项通过，另 1 项显式实机测试默认跳过；四个既有运行模块、新入口及新测试共六个文件的 mypy 通过，新增 Python 文件编译检查通过。

所有宿主运行正常返回，未触发 watchdog；没有强制结束 Photoshop 或关闭用户已有文档。120 秒时限只退出验证进程，不能取消已经提交到 Photoshop 的脚本；发生超时时必须人工检查会话，不自动重试。

## 复现

安装开发依赖，人工确认 Photoshop 空闲且无打开文档。以下以大厅为例；再次运行必须更换尚不存在的输出目录：

```powershell
$env:PSD_HOST_EDIT_REPORT = '.prototype-data/ticket01-continuation/sample-1/acceptance.json'
$env:PSD_HOST_EDIT_OUTPUT = '.prototype-data/ticket01-continuation/sample-1/edit-new-run'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_host_edit_acceptance.py -v
Remove-Item Env:PSD_HOST_EDIT_REPORT, Env:PSD_HOST_EDIT_OUTPUT
```

直接 CLI 入口生成同样宿主证据，但不包含测试中的独立保存文件解析断言：

```powershell
.\.venv\Scripts\python.exe -m prototype.host_edit_acceptance `
  --report .prototype-data/ticket01-continuation/sample-1/acceptance.json `
  --output .prototype-data/ticket01-continuation/sample-1/edit-new-cli-run --timeout 120
```

普通回归及类型检查不启动 Photoshop：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports --follow-imports=silent --check-untyped-defs prototype/file_cleaner.py prototype/batch.py prototype/acceptance.py prototype/host_acceptance.py prototype/host_edit_acceptance.py tests/test_host_edit_acceptance.py
```

## 仍需完成

1. 补充含原生嵌入 PSD 的真实样本，且授权用于同样隔离验收。本地三份用户输入及四份既有官方小样本的原生嵌入头均未发现 PSD v1；两份官方 slice 样本内部也为 PSB v2，另两份为 PNG，不以外层 `.psd` 扩展名充数。
2. 对大厅嵌入保存所触发的局部渲染变化进一步归因，或由用户在明确该限制后确认是否接受本样本的宿主编辑结果；本轮不自动认定无损。
3. 补齐上述边界及最终逐样本结论后，才评估勾选工单完整宿主验收与最终分类项。
