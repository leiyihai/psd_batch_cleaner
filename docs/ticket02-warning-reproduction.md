# 工单 02：未知数据警告真实复现与批次继续验证

> 后续更新：嵌入及独立文档实机保留图层验收现已完成，见 [02最终验收记录](ticket02-closeout.md)。下文保留首次复现阶段的失败、覆盖限制和待办历史，不代表最终状态。

## 首次复现阶段结论（78f04ea）

**已复现真实“未知数据”警告，但 02 尚未验收完成。** 这不是普通保存确认或另存为窗口，也不是以隐藏对话框代替复现。最终由窗口文本采集和用户现场确认共同建立复现证据。

- 输入：用户指定的 `测试psd比对/瘦身前psd/大厅v2.3.psd`。
- 原稿 SHA-256：`c5dd3b016f9bb41b914b0409772f2376c32bc6f45c193936d8133b8a1fc003f3`。
- 宿主：Photoshop 21.2.12（CC 2020），每轮开始前确认空闲、0 个文档；仅打开新隔离副本。
- 触发点：根文档智能对象 **“组 2083”**，图层 ID **556**，嵌入文件名 `组 2083.psb`；原生内容类型已由只读图谱确认。
- **捕获弹窗时**最后宿主阶段为 `before-edit root/556 组 2083`，尚无 `opened root/556`，说明警告发生在进入该嵌入内容的操作中。之后用户取消，日志追加“用户取消了操作”等异常终止记录；这不改变触发点，也不能仅据该日志推断会话已无文档。

本轮未点击“保留图层”或“拼合”，未验证该分支在选择保留图层后仍可编辑，不宣称未知内容已兼容或修复。也未复现主文档直接打开时的未知数据警告。

## 捕获到的实际文案

> 此文档包含未知数据，将扔掉未知数据以保持图层可编辑。若要改为保留原始外观，请选择“拼合”以将复合数据作为拼合的图像载入。

实际按钮为 **保留图层 / 取消 / 拼合**。这里不应按按钮顺序或模糊“默认是”发送确认；需要选择的是语义明确的“保留图层”，绝不是“拼合”。警告同时明确 Photoshop 保留图层可能丢弃未知数据，这仅是辅助测试副本的宿主行为，不授权正常 Python 清理丢弃任意未知字段，也不能据此宣称原始外观必然无损。

## 诊断边界及测试依赖

根据用户要求，仅将 `photoshop-python-api==0.24.2` 加到 Windows 的 `requirements-dev.txt`。安装时使用 comtypes 1.5.0；运行依赖 `requirements.txt`、正常 Python 批处理和旧 JSX 均未增加此依赖。

本轮库只用于被 Git 忽略的本地诊断 worker：连接已运行的 CC 2020、打开隔离副本、执行日志化的 JSX 或单步操作。使用前先确认运行中的 Photoshop；不使用自动关闭用户文档或退出 Photoshop 的 Session 上下文。完整本地工具、计划、脚本和用户素材不提交 Git。

日志化 JSX 以原有清理核心为基础，在打开、保存、关闭及遍历边界加入记录、时限和 STOP 检查；不会修改仓库旧核心。非 PSD/PSB 与外链内容明确跳过，以避免启动其他应用或写外链。因此它是**原生分支诊断**，不是完整、原样运行旧脚本的全部格式覆盖。

## 普通操作弹窗与真实警告的区分

此前多轮失败记录保留，不倒改为成功：

1. 首轮在根打开前出现普通文件选择窗口，未进入递归。
2. 后续达到 `root/4919/16` 的 `图层 13.psb`，出现保存关闭确认；原观察器仅检查 `#32770`，漏掉 Photoshop 的 `PSDialogBox`。用户截图及只读窗口枚举确认这是普通保存提示，不是未知数据警告。
3. 改用 Python API 把保存和关闭拆开后，强制 `DisplayAllDialogs` 仍导致该分支的另存为交互并超时。只读状态探针确认该文档有存在的临时 `fullName`，不是没有路径的新文档。
4. 相同 Python API 选定链，改为 `DisplayErrorDialogs` 后，两级嵌入均保存、关闭完成，结束文档数为 0。该对照支持强制显示全部操作窗口是测试工具普通提示的影响因素，不表示未知数据问题已解决。
5. 较大范围原生诊断在 120 秒协作时限内完成 69 次打开后同步抛出停止异常，清理回到 0 文档；不是将长运行当作已全部通过。根据持续推进的日志和约 163 个原生路径候选，将后续诊断的协作时限设为 360 秒，外部自建 worker 时限为 400 秒，不结束 Photoshop。
6. 最终一轮约 3 分钟进入 `root/556` 时，由已识别 `PSDialogBox` 的观察器捕获上面的真实文案；用户也现场确认“遇到了”。

最终诊断对根 `app.open` 使用 NO（所以不评估根打开警告）；原生 edit-contents 操作周围设置 ALL，保留原核心的 `executeAction(..., DialogModes.NO)`；保存使用 ERROR，清理使用 NO。这些差异均作为诊断边界，不把无弹窗的其他阶段或跳过路径冒充兼容性通过。

### 本地证据路径

- 首轮普通文件窗口：`.prototype-data/ticket02-reproduction/20261113_230820_015731/`。
- 保存关闭阻塞：`.prototype-data/ticket02-reproduction/20261113_231202_218315/`，含 UI 类枚举，确认实际为 `PSDialogBox`。
- Python API 强制全部窗口的阻塞：`.prototype-data/ticket02-api-probe/20261113_232251_553267/`。
- 文档路径/保存状态探针：`.prototype-data/ticket02-save-state/20261113_232727_976214/save-state.json`。
- Python API 单步链成功：`.prototype-data/ticket02-api-probe/20261113_232901_412429/`，含阶段日志及 `documents_after: 0`。
- 120 秒协作终止：`.prototype-data/ticket02-reproduction/20261113_233026_961997/`。
- **真实未知数据警告**：`.prototype-data/ticket02-reproduction/20261113_233652_672159/`，含 `observation.json` 的完整按钮/文本、`host-stages.log`、计划、实际 JSX 和截图；截图部分被终端遮挡，完整文案依据控件文本而非截图推测。

捕获真实警告后，观察器写入 STOP，仅终止自建 worker，没有点击按钮或结束 Photoshop。停止 worker 不能取消已交给宿主的 JSX；已请用户选择“取消”并确认会话退出后再继续，不自动重试。原稿指纹核对不变。**捕获时为“警告已捕获、等待人工取消”；后续日志确认用户取消并触发异常退出，但本轮没有再次联机确认会话文档数，不能称为“已完成清理并关闭全部文档”。**

## 正常 Python 批次继续验证

在单独进程里通过现有 `prototype.batch.run`，顺序处理该真实文件的复制件及官方正常小样本 `smart-object-slice.psd`，不调用 Photoshop、不点击弹窗、不拼合。结果：

| 顺序 | 输入 | 结果 | 字节数变化 | 用时 |
| --- | --- | --- | --- | ---: |
| 1 | 大厅v2.3.psd 的新复制件 | 部分清理，23 个非 PSD/PSB 条目原样保留 | 912,933,942 → 144,069,210 | 24.10 秒 |
| 2 | smart-object-slice.psd 的新复制件 | 无需清理，原样复制 | 1,081,897 → 1,081,897 | 0.13 秒 |

两份输出均发布，原始文件和输入复制件的指纹均不变。该进程的 Photoshop、win32com、pythoncom、comtypes 模块加载清单为空，证据在 `.prototype-data/ticket02-batch/20261113_233345_353219/real-pair-result.json`。这是已确认真实警告源文件的批处理继续证据；不替代未知分支宿主保留图层、可编辑性和视觉检查。

新增可重复的 opt-in CLI 验收测试 `tests/test_warning_sample_batch.py`，直接经过正常批处理 CLI 和报告，检查部分清理状态、后续正常文件完成、输出存在及所有输入指纹不变。无 Photoshop 自动化调用，普通套件默认跳过，显式实跑约 29 秒通过，本地证据 `.prototype-data/ticket02-batch-regression/r1/`。审查后补充输出路径必须归属指定输出目录的断言，并在 `r2/` 最终复跑通过（约 32 秒）。

```powershell
$env:PSD_WARNING_BATCH_SOURCE = 'E:/psd_batch_cleaner/测试psd比对/瘦身前psd/大厅v2.3.psd'
$env:PSD_WARNING_BATCH_NORMAL = 'E:/psd_batch_cleaner/.prototype-data/original/smart-object-slice.psd'
$env:PSD_WARNING_BATCH_OUTPUT = 'E:/psd_batch_cleaner/.prototype-data/ticket02-batch-regression/new-run'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_warning_sample_batch.py -v
Remove-Item Env:PSD_WARNING_BATCH_SOURCE, Env:PSD_WARNING_BATCH_NORMAL, Env:PSD_WARNING_BATCH_OUTPUT
```

## 本轮回归与审查

普通套件共 30 项：27 项通过，3 项 opt-in 测试默认跳过。新增真实批次测试已单独显式实跑通过，不将默认跳过计作通过；8 个相关 Python 文件的 mypy 通过。Standards/Spec 审查指出的输出路径断言和证据时点表述已补强，未改动正常清理代码或旧 JSX。

## 首次复现时的后续计划（现状见最终验收记录）

1. 用户取消当前诊断弹窗、确认无文档后，只针对 ID 556 运行最小验证，不再全量等待。
2. 以明确“保留图层”策略，在原稿和 Python 输出的隔离副本上分别核对该分支图层、实际编辑持久化和渲染结果；不以默认确认或关闭窗口显示代替策略检查。
3. 在真实警告分支范围核对未修改未知字节的保留/安全拒绝结果，补充可重复回归；已有整体区间门禁和合成测试不是关闭 02 的充分条件。
4. 主文档直接打开的警告场景尚无复现证据，需独立覆盖或明确记录材料缺口，不能从嵌入警告推定。
5. 02 保持未完成，03 及后续 GUI 工单仍受依赖阻塞。
