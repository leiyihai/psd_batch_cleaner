# 历史 Photoshop JSX 工具

这里保留项目原有的 Photoshop Deep Cleaner Plus 脚本及参考资料。它们需要 Photoshop 执行，**不属于当前 Python 清理链路的依赖**。

原项目：<https://github.com/julysohu/photoshop_deep_cleaner>；原作者：<https://github.com/julysohu>。旧说明和演进过程仍可在 Git 历史中查看。

## 文件

- `PsDeepCleanerPlus.jsx`：处理当前文档。
- `PsDeepCleanerPlusForFolder.jsx`：按原脚本提示处理文件夹。
- `CleanerCore.jsxinc`、`Common.jsxinc`：公共实现，须与入口脚本放在同一目录。
- `Demo.jsx`：开发演示代码，不是正式清理入口。
- `reference/`：原有 ExtendScript 调试说明和 Photoshop JavaScript PDF 参考资料。

本次仅移动脚本，未修改其清理逻辑。所有 `#include` 依赖仍在同一目录。Python 运行及验证命令请见 [项目首页](../../README.md)。

## 使用

1. 先备份文件。旧脚本的行为与 Python 独立副本发布机制不同，不应假定它提供同等文件安全保证。
2. 在 Photoshop 中，通过 **文件 → 脚本 → 浏览** 选择本目录的入口脚本。
3. 按脚本提示执行；不要同时运行 Python 宿主验收工具。

旧脚本通过 Photoshop 的 XMP 接口清理文档祖先元数据，并递归处理智能对象。对未知数据警告、任意嵌入格式及共享实例的兼容性不能仅凭旧脚本存在推定通过；Python路径的已验收范围见 [01最终记录](../../docs/ticket01-closeout.md)、[02最终记录](../../docs/ticket02-closeout.md)；这些结论不等于对旧脚本所有行为完成了验收，旧脚本逻辑未随本次迁移修改。

## 参考

- [本地 ExtendScript Debugger 说明](reference/extendscript-debugger.md)
- <https://marketplace.visualstudio.com/items?itemName=Adobe.extendscript-debug>
- <https://extendscript.docsforadobe.dev/scripting-xmp/accessing-the-xmp-scripting-api.html>
- <https://github.com/adobe/xmp-docs/blob/master/XMPNamespaces/photoshop.md>
- <https://helpx.adobe.com/photoshop/using/scripting.html>
