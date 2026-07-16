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

1. **更新 proposal.md 和 plan.md 的 status 字段**：
   - 正常归档：proposal.md 和 plan.md 均改为 `completed`
   - 放弃时：proposal.md 和 plan.md 均改为 `abandoned`
2. 创建 `.ai/changes/archive/` 目录（如不存在）

#### 🔴 强制扫描（不可跳过）

**必须使用工具实际列出 `.ai/changes/archive/` 目录内容。不可凭记忆或假设跳过此步。**

3. **扫描当天已有归档**：
   - 获取当天日期 `YYYYMMDD`
   - 使用 Glob 或 ls 列出 `.ai/changes/archive/` 中所有以 `YYYYMMDD` 开头的目录
   - 从每个目录名中解析 `NNN` 序号（格式 `YYYYMMDD-NNN-名称`，NNN 为前三位的三位数字）
   - **将扫描结果显式输出**（序号列表 + 目录名列表），确保人类可见

4. **确定归档序号**：
   - 如果当天无已有归档 → 序号 `001`
   - 如果当天有已有归档 → 取最大序号 +1（三位数补零）
   - **验证**：确认计算出的序号不在步骤 3 的已有序号列表中
   - **禁止**：未经步骤 3 扫描直接使用 `001`

5. **序号冲突二次校验**（在 rename 之前执行）：
   - 检查目标 NNN 是否已被当天**任何**归档使用（**无论 change 名称是否相同**）
   - 检查目标完整路径是否已存在
   - 如有任何冲突 → NNN 递增 1，重新检查，循环直到无冲突
   - 此校验覆盖两种场景：同序号不同名（如 `001-功能A` 和 `001-功能B`）和完整路径相同

6. 将 change 文件夹重命名为 `YYYYMMDD-NNN-名称`，移入 `.ai/changes/archive/`
   - 示例：.ai/changes/archive/ 中已有 `20260611-003-xxx`，当天归档时序号为 `004`

7. **清理同步备份**：如 change 目录下存在 `.sync-backup/`，删除。

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
- proposal.md 和 plan.md 的 status 均改为 `abandoned`
- 重命名为 `YYYYMMDD-NNN-名称-abandoned`，移入 `.ai/changes/archive/`（序号规则同上）
- project-log.md 记录为"已放弃"

---

## 💡 常见陷阱（Gotchas）

- **归档序号由扫描结果决定，不可跳过扫描**：步骤 4.3 必须实际列出 archive 目录内容。如果 agent 跳过扫描直接使用 `001`，会导致同一天出现重复序号。
- **碰撞检测覆盖序号冲突，非仅完整路径冲突**：步骤 4.5 会检测同一天内 NNN 是否已被使用（即使 change 名称不同）。旧版只检测完整路径相同，无法防止同序号不同名的情况。
- **归档前检查 plan.md 的 `## 文档变更` 章节**：如果有未处理的文档变更条目，归档意味着这些问题被永久留在文档中（直到下次 diagnose 发现）。务必确认 sync 已完成，或明确选择"不同步直接归档"。
- **归档后 change 目录被移动**：其他 skill 中缓存的 change 路径将失效。归档应在 change 生命周期的最后执行。
- **sync 异常退出可能导致 `.sync-backup/` 残留**：归档前检查并清理残留的备份目录。

---

## 联动设计

- **拒绝路径**：见「前置检查」
- **归档前提示（如有未同步变更）**：`📋 该 change 有文档变更尚未同步。建议先运行 /sdd-sync 更新项目文档。`
- **归档后提示**：`✅ Change 已归档：.ai/changes/archive/YYYYMMDD-NNN-名称`
