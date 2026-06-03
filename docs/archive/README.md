# CodeRunner-AI 文档归档

这里保存非计划类历史材料，例如已经完成、被当前文档替代，或仅用于历史追溯的旧实现指南。

当前有效文档入口保留在 [docs/README.md](../README.md)。计划类文档统一放在 [docs/plans/](../plans/README.md)，状态和审计类文档统一放在 [docs/status/](../status/README.md)。

## 目录约定

| 目录 | 内容 |
|---|---|
| `completed/` | 已完成的旧实现指南和阶段性增强方案 |

## completed/

- [AGENT_ENHANCEMENT_GUIDE.md](completed/AGENT_ENHANCEMENT_GUIDE.md)
- [AGENT_ENHANCEMENT_GUIDE_ZH.md](completed/AGENT_ENHANCEMENT_GUIDE_ZH.md)

## 迁移说明

为避免多套归档入口，以下目录已经不再使用：

- `docs/archive/plans/` -> 改为 `docs/plans/archive/`
- `docs/archive/status/` -> 改为 `docs/status/`
- `docs/archive/superpowers/plans/` -> 改为 `docs/plans/archive/superpowers/`

归档文件中的旧相对路径可能保留历史布局名称。判断当前实现时，以代码、运行时和 [docs/README.md](../README.md) 中列出的当前有效文档为准。
