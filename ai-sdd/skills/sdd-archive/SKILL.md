---
name: sdd-archive
description: >
  归档完成的 change。检查完成状态、同步状态，执行归档移动。
  触发词：归档、完成change、收尾、archive、结束变更、change完成
---

# sdd-archive（归档 change）

## 定位

完成 change 的归档工作。

## 前置检查

1. 无活跃 change → 拒绝，提示"没有活跃的 change 需要归档"

## 执行流程

### 步骤 1：选择 change

如有多个活跃 change，用 AskUserQuestion 询问用户选择；**绝不自动选择**。

### 步骤 2：检查任务完成情况

读取 plan.md，统计 `- [x]` vs `- [ ]` 数量：

- **完成率 0%**：强烈警告"该 change 没有任何已完成任务"，AskUserQuestion（选项：放弃 / 继续归档 / 取消）
- **完成率 < 100% 但 > 0%**：警告 + 列出未完成任务，AskUserQuestion 确认是否继续
- **完成率 100%**：继续下一步

### 步骤 3：检查文档同步状态

1. 读取 plan.md 的 `## 文档影响评估` 表格
2. 如有未同步项：警告并列出，AskUserQuestion（选项：先同步再归档 / 不同步直接归档 / 取消）
3. 如选择先同步：提示运行 `/sdd-sync`
4. 如计划中有 `## 04 更新计划`：检查条目是否已在 sync 阶段处理，未处理则提示
5. **回归诊断建议**（可选，推荐执行）：
   - 建议在归档前运行 `/ai-sdd-diagnose --layer=D --depth=L1` 对本次 change 涉及的代码做快速回归检查
   - 如 diagnose 发现新问题 → 评估是否需要先修复后归档，或记录到 project-log.md 供后续处理
   - 如跳过此步 → 归档继续，但需在归档摘要中注明"未执行回归诊断"

### 步骤 4：执行归档（含日期重编号）

1. **更新 proposal.md 的 status 字段**：
   - 正常归档：改为 `completed`
   - 放弃时：改为 `abandoned`
2. 创建 `.ai/changes/archive/` 目录（如不存在）
3. **确定归档序号**：
   - 获取当天日期 `YYYYMMDD`
   - 扫描 `.ai/changes/archive/` 中以该日期开头的文件夹，取其中最大序号+1（三位数补零）
   - 如果当天无已有归档，序号从 `001` 开始
4. 将 change 文件夹重命名为 `YYYYMMDD-NNN-名称`，移入 `.ai/changes/archive/`
   - 示例：.ai/changes/archive/ 中已有 `20260611-003-xxx`，当天归档时序号为 `004`
5. **碰撞检测**：如果目标路径已存在，追加 `-a`、`-b` 后缀
6. **清理同步备份**：如 change 目录下存在 `.sync-backup/`，删除。

### 步骤 5：更新 project-log.md

1. 从「活跃 Change」区段移除该 change 的行
2. 在「变更时间线」区段追加归档记录

### 步骤 6：输出归档摘要

```
✅ Change 已归档：.ai/changes/archive/YYYYMMDD-NNN-名称
   任务完成：X/Y
   文档同步：已同步/未同步
```

---

## 放弃 change 功能

用户选择"放弃"时：
- proposal.md status 改为 `abandoned`
- 重命名为 `YYYYMMDD-NNN-名称-abandoned`，移入 `.ai/changes/archive/`（序号规则同上）
- project-log.md 记录为"已放弃"

---

## 💡 常见陷阱（Gotchas）

- **归档前检查 plan.md 的 `## 文档变更` 章节**：如果有未处理的文档变更条目，归档意味着这些问题被永久留在文档中（直到下次 diagnose 发现）。务必确认 sync 已完成，或明确选择"不同步直接归档"。
- **归档后 change 目录被移动**：其他 skill 中缓存的 change 路径将失效。归档应在 change 生命周期的最后执行。
- **sync 异常退出可能导致 `.sync-backup/` 残留**：归档前检查并清理残留的备份目录。

---

## 联动设计

- **拒绝路径**：见「前置检查」
- **归档前提示（如有未同步变更）**：`📋 该 change 有文档变更尚未同步。建议先运行 /sdd-sync 更新项目文档。`
- **归档后提示**：`✅ Change 已归档：.ai/changes/archive/YYYYMMDD-NNN-名称`
