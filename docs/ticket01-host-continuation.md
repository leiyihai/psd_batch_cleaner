# 工单 01：另外两份真实样本的宿主保存重开验收

## 范围与结论

用户确认 Photoshop 已就绪后，联机预检确认 Photoshop 21.2.12、打开文档数为 0。使用现有 `prototype.host_acceptance`，对最终自动报告的另外两份 Python 输出逐份执行隔离副本验收，两次命令退出码均为 0。

**本记录仅补齐大厅v2.3.psd、通行证V3.psb 的现有保存重开验收，不代表工单 01 完成。** 未执行嵌入内容实际编辑保存、共享实例关联行为验收；原生嵌入 PSD 的真实样本仍缺失。本次不解除 GUI 前置依赖，也不涉及工单 02。

此前大厅样本的证据、资源测量及三份输入/参考指纹见 [真实文件验收记录](real-file-acceptance.md)。本记录不修改此前的历史结论。

## 输入与证据来源

原自动报告为 `.prototype-data/user-acceptance-final/20261113_194622_237572/acceptance.json`。该报告含重命名前绝对路径，因此本轮仅在被 Git 忽略的 `.prototype-data/ticket01-continuation/sample-{1,2,3}/acceptance.json` 生成单样本派生报告，重定位项目根路径，并保留 `_workspace_relocation` 来源、原报告 SHA-256 和路径迁移说明。

派生报告不是新自动验收结果，不覆盖历史报告。宿主工具只复制派生报告引用的既有 Python 输出，不打开大体积原稿、不写入 JSX 参考文件。每份宿主输出使用此前不存在的 `host-r1` 隔离目录。

## 结果

| 样本 | 打开的嵌入链深度 | 保存重开图层快照 | 保存重开 PNG 解码像素 | 检查链上祖先字段 | Python 输出 SHA-256 | 结束文档数 |
| --- | ---: | --- | --- | --- | --- | ---: |
| 大厅v2.3.psd | 3 | 完全一致 | 一致 | 保存前后均不存在 | 前后一致 | 0 |
| 通行证V3.psb | 3 | 完全一致 | 一致 | 保存前后均不存在 | 前后一致 | 0 |

图层快照摘要（保存前后相同）：

- 大厅v2.3.psd：`1a83f662ca95146833dab1c657d75a16f5b223d0376b55d57f3da4f87579974f`。
- 通行证V3.psb：`b78d2a8207b9b8bc330b9f41dcf2a7635a7c8131354ed8d2a4d23b52e97557d5`。

本工具检查所选最深嵌入链，不表示通过 Photoshop 遍历全部嵌入分支；PNG 比较针对根文档。未将打开嵌入内容当作已完成实际编辑保存。三份结果原有“部分清理”分类不因本轮宿主通过而变为完整清理。

本地证据：

- `.prototype-data/ticket01-continuation/sample-2/host-r1/host-report.json`
- `.prototype-data/ticket01-continuation/sample-3/host-r1/host-report.json`
- 对应样本子目录内的 `snapshots.json`、隔离输入、`roundtrip.psd`/`roundtrip.psb`、`before.png` 和 `after.png`。

这些用户素材及完整证据不提交 Git。两次均正常返回，没有触发时限，没有强制结束 Photoshop 或自动重试。

## 复现

仅在人工确认 Photoshop 空闲且没有打开文档后运行。以下为本次命令；再次运行时须更换尚不存在的输出目录：

```powershell
.\.venv\Scripts\python.exe -m prototype.host_acceptance `
  --report .prototype-data/ticket01-continuation/sample-2/acceptance.json `
  --output .prototype-data/ticket01-continuation/sample-2/host-r1 --timeout 65
.\.venv\Scripts\python.exe -m prototype.host_acceptance `
  --report .prototype-data/ticket01-continuation/sample-3/acceptance.json `
  --output .prototype-data/ticket01-continuation/sample-3/host-r1 --timeout 65
```

超时仅退出验证进程，不能保证取消 Photoshop 内已提交的操作；一旦超时须人工检查会话，不自动重试。

## 后续验收

1. 在隔离副本上验证嵌入内容实际编辑、保存及重新打开后的持久化。
2. 验证共享同一嵌入内容的多个图层实例仍保持关联。
3. 补充原生嵌入 PSD 真实样本及相应验收。
4. 完成约定样本的最终分类和全部必需证据后，才评估关闭工单 01。
