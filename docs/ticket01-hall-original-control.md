# 工单 01：大厅原稿副本同流程宿主对照

## 结论

用户明确要求“直接拷贝一个原稿做相同的操作进行比对”后，使用未瘦身的 `测试psd比对/瘦身前psd/大厅.psb` 的新隔离复制件执行此前共享实例无编辑保存协议。

**原稿副本与瘦身副本的初始画面、操作后画面分别逐像素一致；两者操作前后的有符号 RGBA 像素差也完全一致。** 此前观察到的 234 像素微小变化在原稿副本中同样发生，未观察到 Python 瘦身对此操作新增的视觉差异。

这确认了该样本在 Photoshop 21.2.12 中保存共享嵌入内容时本身存在这一行为；不宣称已确定 Photoshop 内部具体重采样或颜色处理算法，也不推广为任意文件、任意 Photoshop 版本的结论。

## 相同操作与隔离安全

开始预检：Photoshop 21.2.12，打开文档数 0；可用内存约 32.47 GiB，磁盘剩余约 761 GiB。

1. 只读计算原稿 SHA-256，确认与原有验收输入指纹一致。
2. 完整复制约 1.70 GB 的原稿到新隔离目录，并核对复制件指纹。
3. 复用此前 `shared-only/actual-script.jsx`，仅替换计划中的隔离路径，宿主操作代码、图层 ID 和 `edit: false` 参数保持不变。
4. 打开复制件，导出初始 PNG；从共享实例 2724 打开 `飞行.psb`，不新增标记图层，直接保存关闭；从实例 2590 打开核查，然后不保存关闭。
5. 将大厅另存到新的隔离 PSB，关闭、重开，核查并导出 PNG。没有修改或保存用户原稿。
6. 脚本正常返回 `passed`，阶段日志包含完成记录；随后独立联机检查 Photoshop 文档数为 0。未超时、未结束 Photoshop，也未自动重试宿主操作。

原稿 SHA-256 前后仍为 `c3c253aa87de834e70d7792f5751b6f278995ced1dba4363fb96a7ba7803eb6b`。

## 像素对照结果

| 比较 | 结果 |
| --- | --- |
| 原稿副本操作前 vs 瘦身副本操作前 | RGBA 解码像素完全一致 |
| 原稿副本操作后 vs 瘦身副本操作后 | RGBA 解码像素完全一致 |
| 两组“操作后减操作前”的有符号差 | 完全一致 |
| 原稿副本操作前 vs 操作后 | 234 个像素改变 |
| RGB 差异包围区域 | `(1191,422)–(1234,456)` |
| RGBA 单通道最大绝对差 | 4/255 |

对照用的瘦身副本基线为 `.prototype-data/ticket01-continuation/sample-1/save-branch-diagnosis-r1/shared-only/`。这不是与 JSX 参考集比较，也不是借助压缩 PNG 的文件哈希判断视觉一致。

## PNG 元数据读取限制及证据处理

宿主操作第一次就已完整完成，但后处理读取原稿导出的 PNG 时，Pillow 报 `Too much memory used in text chunks: 75812016>MAX_TEXT_MEMORY`，因此外层首次脚本记录了 `failure.json`。此失败是图片文本元数据的读取限制，不是 Photoshop 超时，也不作为宿主或像素比较已经通过的证据。

随后不重跑 Photoshop，只对已有四份 PNG 创建派生副本：流式检查全部源 PNG chunk CRC，仅省略 `iTXt`、`tEXt`、`zTXt` 文本块；所有非文本块（包含压缩像素 IDAT）原样复制，不解压巨量文本、不提升 Pillow 全局安全上限、不重新编码像素。原 PNG 前后 SHA-256 一致。最终对这些派生文件用 Pillow 解码 RGBA，再计算完整图像和有符号差值比较，得到上表结果。原始失败记录原样保留。

本地证据根目录：`.prototype-data/hall-original-control/20261113_223956_880506/`。

- `plan.json`、`actual-script.jsx`、`host-stages.log`：与先前协议相同的宿主操作及完成记录。
- `isolated.psb`、`edited-roundtrip.psb`、原始 PNG：隔离副本与宿主输出；文件名中的 edited 是原协议命名，本轮 `edit: false`，未创建测试图层。
- `pixel-comparison/comparison.json`：最终比较结果、PNG 派生来源指纹、IDAT 指纹及移除文本块清单。
- `pixel-comparison/original_before.png`、`original_after.png`、`cleaned_before.png`、`cleaned_after.png`：可直接人工比对的无文本派生图片。

素材和完整本地证据不提交 Git。本轮没有修改清理代码、放宽字节保真或视觉检查，也不把用户此前的画板假设当作接受差异的授权。此前“缺少原稿同流程宿主对照”的证据缺口现已补齐；本次仅追加验收记录，不更改工单状态或后续工单依赖。
