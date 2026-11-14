# Ticket 02 最终验收：未知数据原样保留，正常批次不受 Photoshop 弹窗阻塞

## 结论与范围

02 的七项验收已有对应证据。正常 Python 批处理继续使用现有区间补丁/保真门禁，不启动 Photoshop、不模拟点击、不拼合或栅格化。此前已有的正常清理路径无需为该素材增加格式转换；本轮补充真实兼容性验收、辅助警告白名单策略及回归。

**不是把素材转换成 CC2020 不再报警的格式。** Python 输出保留未知内容，所以 Photoshop 打开它时仍可能出现同样警告。辅助验收在用户明确授权下选择“保留图层”，不能据此说 Photoshop 没有丢弃未知数据，或保证任意素材原始外观无损。旧 JSX 未修改，正常清理也未增加 Photoshop 依赖。

主文档警告使用的是从真实素材原样提取的 PSB 独立打开，不是声称大厅父文档自身打开时报警；其与嵌入场景的源字节完全相同，没有合成未知字段或注入祖先数据。

## 材料、环境与授权

- Photoshop CC2020 21.2.12；Python 3.14.4、psd-tools 1.26.1；photoshop-python-api 0.24.2 仅用于测试。
- 用户再次授权继续 02；01:44 已过，实际实施开始于 2026-11-14 08:00（UTC+08:00）。未将之前权限失败的定时安排说成已执行。
- 预检证据 `.prototype-data/ticket02-focused/20261114_080040_565370/`：桌面可访问，宿主主窗口启用、无模态、版本21.2.12、0文档。
- 原稿 `测试psd比对/瘦身前psd/大厅v2.3.psd`：SHA-256 `c5dd3b016f9bb41b914b0409772f2376c32bc6f45c193936d8133b8a1fc003f3`。
- Python 清理稿使用先前真实 CLI 回归 `ticket02-batch-regression/r2` 的输出，SHA-256 `126243a932e0715f65068851828c21aa36bf4b28a3d7f1cf7a498ed7bcb7d56c`。它的整体结果仍是“部分清理”，23个非 PSD/PSB条目原样保留，不改称完整成功。
- 所有打开/修改/保存/关闭均在新隔离副本；上述两个受保护文件前后指纹不变。

## 真实未知内容的保留证明

从清理稿只读读取根智能对象 ID556 的 UUID，再在原稿的 linked framing 中按 UUID 定位原始字节区间、直接提取，不通过 PSD 重序列化生成“原稿”样本。

- 图层“组 2083”，嵌入 `组 2083.psb`。
- UUID `a22cae74-c224-cc46-8cd8-c3c07d939c58`。
- 原始与清理后的载荷均为 **45,900字节，整个载荷逐字节相同**。
- 共同 SHA-256：`60dcb46c42beb16f4e346aa5a825f0d419d3c46a0b7e0c49b84469bbb62ed22e`。
- 画布27×33，1个组、6个形状图层。离线读到的7个 ID/名称，与 Photoshop 选择保留图层后的结果对应；6个形状仍为 `LayerKind.SOLIDFILL`，没有变成单层拼合图像。

因此不必猜测究竟哪一个私有字段导致警告，即可证明 Python 没有丢弃或改写该分支的任何未知字节。该分支本身没有待删除的祖先数据，不能把它的原样复制当作祖先删除路径证据；真实大厅父文件的14处祖先删除、96文档扫描及保真门禁由原有真实批次记录覆盖。

## 警告白名单：仅辅助实机验收

用户授权仅在确认属于本轮隔离副本、完整文案和三个按钮均匹配时，自动选择“保留图层”。新增 `prototype/host_warning_policy.py` 是该外部窗口决策边界，无 Windows/Photoshop 导入，不接入正常清理。

完整文案沿用首次真实捕获；标题必须为 Adobe Photoshop、窗口类 PSDialogBox，且三个启用的按钮恰好是“保留图层 / 取消 / 拼合”。还需匹配既有 Photoshop PID、本轮run ID、指定隔离路径和宿主阶段：嵌入打开前须为 ID556且仅1文档；独立打开前须无文档、无图层ID。函数只返回“保留图层”的控件句柄，不按默认键或按钮顺序猜测。

本地监督器实际使用此策略：读日志中的实际根路径和文档数、窗口所属PID，在发消息前重新读取窗口/宿主阶段并核对控件归属，只对该按钮发送一次 `BM_CLICK`。其他窗口、归属变化或超时写 STOP，仅可结束自建 Python worker；不结束 Photoshop、不点击取消或其他按钮、不自动重试。实际成功的四个验收案例均未触发 STOP/超时。

TDD 记录：最初严格嵌入匹配测试观察到 `None != 101` 后实现策略；随后独立打开授权测试同样先失败，再增加明确的空文档阶段。最终5项测试覆盖精确允许、错误PID/run/文档/阶段、改动文字/按钮、禁用/重复控件及按钮顺序。

## 嵌入式智能对象实机验收

证据根目录：`.prototype-data/ticket02-focused/20261114_080707_992970/`。

原稿新副本与 Python 清理稿新副本分别只进入 ID556，不重跑全量遍历。每份：

1. 根打开采用NO，随后在 edit-contents 周围观察已知未知数据警告；各捕获并处理1次，日志和完整窗口/按钮记录在 `original/authorized-clicks.json`、`cleaned/authorized-clicks.json`。
2. 核对7个原有图层的ID、层级、名称、类型、可见性和27×33 RGB/8bit画布。
3. 无编辑保存作为对照；再重命名原有形状图层ID1632，新增隐藏的1×1实像素层。
4. 保存嵌入回父智能对象、保存隔离父文档，关闭并重新打开父文档，再进入 ID556。
5. 断言形状重命名持久化、新像素层仍为NORMAL且隐藏、像素边界为1×1、图层总数由7到8；编辑后与重开后的完整结构快照相同。
6. 关闭自有文档，两个案例各自 `documents_after: 0`，原稿和既有清理稿指纹不变。

`paired-result.json` 比较父文档 before/control/edited/after 与子文档 before/edited/after 共7组图像，清理前后逐RGBA像素相同。`final-audit.json` 进一步核对离线/宿主图层，并确认原稿与清理稿各自“父文档初始→无编辑保存对照”“对照→隐藏像素编辑”均为 **0个差异像素**。隐藏编辑和重命名不改变可见渲染，重开后也不改变。本结论针对这份素材及这些操作，不扩大为任意未知特性的保留承诺。

## 独立主文档实机验收

真实45,900字节PSB直接提取为独立输入；正常 Python `clean_file` 输出为“无需清理”，全文件字节相同。在 `standalone-error/` 对原始独立副本和 Python 输出独立副本分别：

- 使用 `app.open`、`DialogModes.ERROR` 打开，**各观察并按白名单处理1次真实未知数据警告**，不是靠NO模式假定默认策略。
- 检查7个原始图层，执行同样的形状重命名及隐藏1×1像素编辑，保存、关闭、重新打开，验证结构和编辑持久化。
- before/edited/after 三组27×33图像在原稿与输出之间逐像素相同，编辑前后可见渲染相同；各自关闭后0文档。

早先 `standalone/` 使用 `executeAction(Opn,...,NO)`，虽完成编辑保存对照，但没有出现警告，**不计入警告覆盖**。后续使用新隔离副本只改变打开方式，`standalone-error/` 才是主文档警告证据。全部实际脚本和阶段记录保留，不覆盖既有尝试。

## 正常批次与保护性拒绝

- 真实完整问题文件＋后续官方正常文件的无交互 CLI 批次，沿用 `docs/ticket02-warning-reproduction.md` 的 r2 证据；正常进程没有加载 Photoshop 自动化模块。问题文件“部分清理”，后续“无需清理”，两份输出发布且所有原稿不变。
- 新增 `tests/test_warning_branch_acceptance.py`：真实已捕获警告的PSB→它的明确截断损坏复制件→小型正常PSD。通过现有 `prototype.batch.run` 验证状态为“无需清理 / 失败 / 无需清理”，损坏项报告原因、无输出，后续正常项仍完成；所有输入不变，真实未知PSB整个输出哈希仍等于上述原始哈希。
- 初次r1使用同一有效PSB作为后续输入；最终r2明确替换为独立的2×2正常PSD，再次实跑通过。最终证据 `.prototype-data/ticket02-unknown-branch-regression/r2/`，不把r1称为普通无警告样本。
- 现有回归继续覆盖区间保真、opaque padding、linked v8后缀/未知条目保留、解析错误、缺失已知后缀、不能验证的替代图层、旧路径非保真往返拒绝以及单文件失败后继续。不能可靠校验的结构仍拒绝发布，没有为本次警告放宽门禁。

可重复运行（要求已保留本地真实提取材料，输出目录必须不存在）：

```powershell
$env:PSD_WARNING_BRANCH_SOURCE='E:/psd_batch_cleaner/.prototype-data/ticket02-focused/20261114_080707_992970/original/extracted-556.psb'
$env:PSD_WARNING_BRANCH_OUTPUT='E:/psd_batch_cleaner/.prototype-data/ticket02-unknown-branch-regression/new-run'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_warning_branch_acceptance.py -v
Remove-Item Env:PSD_WARNING_BRANCH_SOURCE, Env:PSD_WARNING_BRANCH_OUTPUT
```

真实文件、二进制提取件、图像、本地工具和宿主完整脚本均留在 Git 忽略的 `.prototype-data/`，不上传设计素材。新增测试缺少显式环境变量时跳过，不自动连接 Photoshop。

## 最终回归

- 普通套件36项：32通过、4项显式opt-in默认跳过，不将skip算成真实验收。
- 真实未知分支/损坏/后续正常PSD的opt-in回归在`ticket02-unknown-branch-regression/r2/`单独实跑通过。
- 完整真实问题文件＋后续官方正常文件的CLI opt-in最终在`ticket02-batch-regression/r3/`重新实跑通过，约27秒；保留“部分清理”分类。
- 11个相关Python文件mypy通过；新增3个Python文件py_compile通过。
- 最终Standards审查：0项硬违规、0项需报告的异味；Spec审查：0项剩余规格缺口/越界/实现错误，确认7/7证据在声明范围内充分。审查只读核对真实证据，不连接Photoshop，不以自动测试代替实机证据。

## 完成边界

七项验收分别由：嵌入/独立主文档真实警告、明确按钮策略、直接Python清理和实机结构/编辑/像素、保护性拒绝、后续文件继续、授权且有界的宿主辅助、真实字节保留及自动回归支撑。没有要求或实现普通Python处理中的弹窗自动点击。

01、02 的前置验收均已满足，03因此具备依赖条件；**本轮只完成02，不实施03或其他GUI工单**。本地triage没有completed状态，Status继续为ready-for-agent，用Completion及本完成记录表示真正完成。
