---
name: ai-sdd-update
description: >
  AI-SDD 版本升级。两级操作：minor bump 仅更新 supplement-rules.md（轻量）；
  major bump 时额外调用 reverse ref 模式迁移 doc 文件（重量）。
  触发词：更新 AI-SDD 规则、同步 supplement-rules、更新 .ai 规则、update ai-sdd rules
---

# AI-SDD 版本升级

## 定位

⚠️ **本 skill 依赖 ai-sdd-reverse（major bump 时）。** 重量升级时通过调用 reverse 的 ref 模式来执行文档迁移。minor bump 不依赖 reverse。

当 AI-SDD 方法论版本升级时，更新项目中的 AI-SDD 体系文件。

**两级操作**：
- **minor bump**（仅 constitution 层变更）→ 轻量：替换 `supplement-rules.md`，秒级完成
- **major bump**（doc 模板也变了：文件名/角色/结构）→ 重量：替换 constitution + 调用 reverse ref 模式迁移 doc 文件

**update 不是独立引擎**——重量升级时，它通过精心设计的提示词，调用 reverse 的 ref 模式来完成文档迁移。

**精确边界**：
- ✅ 更新 `.ai/supplement-rules.md`（宪法层）
- ✅ major bump 时：调用 reverse ref 模式迁移 `.ai/doc/`（文档层）
- ✅ 提示检查 `.ai/project-rules.md` 是否需要同步调整
- ❌ 不修改 `.ai/project-log.md`（项目私有数据）
- ❌ 不修改 `.ai/project-rules.md`（项目私有规则）
- ❌ 不修改 skill 文件本身（体系层面的事）

## 前置检查

1. 检查 `.ai/supplement-rules.md` 是否存在 → 如不存在，提示先运行 `/ai-sdd-init`
2. 读取项目当前版本的 `version` 字段

## 执行流程

### 步骤 1：版本对比

1. 读取项目 `.ai/supplement-rules.md` 的 `version` 字段
2. 读取 `ai-sdd-init/templates/supplement-rules.md`（模板唯一权威源）的 `version` 字段
3. 比较两个版本号

### 步骤 2：判断是否需要更新

- **版本相同**：提示"已是最新版本（vX.Y），无需更新"，终止
- **版本不同**：继续步骤 3

### 步骤 3：模板一致性校验

对比 `ai-sdd-init/templates/`（模板唯一权威源）与项目部署的 `.ai/` 文件：
- `ai-sdd-init/templates/supplement-rules.md` vs 项目中 `.ai/supplement-rules.md`
- `ai-sdd-init/templates/project-log.md` vs 项目中 `.ai/project-log.md`
- `ai-sdd-init/templates/doc/`（5 个 doc 模板）vs 项目中 `.ai/doc/` 对应文件

如 init 的模板与项目文件有结构性差异（非 version 字段差异）→ 警告用户并列出不一致的文件。

> 注意：update 不再维护自己的 `templates/` 目录。模板的唯一权威源是 `ai-sdd-init/templates/`。

### 步骤 4：判断升级级别

对比新旧版本的 doc 模板，判断是 minor 还是 major bump：

#### 判定为 minor bump（仅 constitution 变更）：
- doc 文件名不变
- doc 角色区块（「📋 本文档角色」）不变
- doc 章节结构不变
- 仅 supplement-rules.md 有原则/规则层面的调整

#### 判定为 major bump（doc 体系变更）：
以下**任一条件**满足：
- doc 文件重命名（如 `01-需求.md` → `01-行为目录.md`）
- doc 角色区块的"应该写"/"不应该写"列表发生变更
- doc 新增或删除（如新增 `04-问题与改进.md`、`05-系统约束.md`）
- doc 章节结构重组（如 `02` 从"技术选型"变为"决策记录"）
- supplement-rules.md 的 version 发生 major 号跳跃（如 `1.x` → `2.x`）

- minor bump → 进入步骤 5a
- major bump → 进入步骤 5b

### 步骤 5a：轻量升级（minor bump）

1. 展示 supplement-rules.md 的变更摘要（新增/修改/删除的章节和规则）
2. 如果 `.ai/project-rules.md` 存在 → 提示检查是否需要同步调整
3. 人类确认后：
   - 用 `ai-sdd-init/templates/supplement-rules.md` 中 `<!-- SUPPLEMENT-RULES-CUT -->` **标记之上**的方法论规则层替换项目 `.ai/supplement-rules.md` 的对应部分
   - **保留**标记之下的项目特定约束节（含所有 AC/DP/CI/ENV 约束条目）不变
   - 保留项目中 YAML front matter 中的项目特定字段（如有）
4. 输出升级摘要，终止

```
supplement-rules.md 方法论规则层已更新到 vX.Y（minor bump）。
项目特定约束节未被修改。

提醒：
  - .ai/doc/ 未被修改（本次升级不涉及文档体系变更）
  - .ai/project-log.md 未被修改（项目私有数据）
  - 如有 .ai/project-rules.md，请自行检查是否需要同步调整
  - skill 文件的更新需手动进行（体系层面的事）
```

### 步骤 5b：重量升级（major bump）

1. 展示完整变更摘要：
   - supplement-rules.md 的变更
   - doc 模板的结构性变更（文件名映射、角色变更、章节变更）
   - project-log.md 格式变更（如有）

2. 人类确认后，先用最新模板替换 `.ai/supplement-rules.md`

3. **提示 doc 迁移**（用 AskUserQuestion 询问）：

```
检测到文档体系结构性变更。建议运行文档迁移以适配新版本。

  A) 立即迁移 — 调用 reverse ref 模式，将现有 doc 迁移到新结构
  B) 稍后手动迁移 — 仅更新 constitution 层，doc 保持旧结构
     （⚠️ 旧结构 doc 可能与新版 skill 不兼容）
```

4. 如用户选 A → 调用 reverse ref 模式，注入"版本迁移"专用提示词（见下方）
5. 如用户选 B → 记录待迁移状态到 project-log.md

6. 输出升级摘要：

```
supplement-rules.md 已更新到 vX.Y（major bump）。

文档迁移状态：
  [已完成 / 待迁移 — 记录在 project-log.md 中]

提醒：
  - .ai/project-log.md 未被修改（项目私有数据，除迁移记录外）
  - 如有 .ai/project-rules.md，请自行检查是否需要同步调整
  - skill 文件的更新需手动进行（体系层面的事）
```

### 步骤 6：版本迁移提示词（major bump 专用）

当用户选择"立即迁移"时，将 `.ai/doc/` 作为 ref 路径传入 reverse。

**Read [references/migration-prompt.md](references/migration-prompt.md) now and inject it into the reverse call.**

该提示词定义了五个任务：结构迁移 → 新增补齐 → 格式适配 → 元信息保留 → 版本记录。

---

## 版本号规则

- `major.minor.patch` 格式（如 1.7.4）
- **major 变更**：breaking changes，AI 行为有重大调整
- **minor 变更**：向后兼容的功能补充
- **patch 变更**：bug 修复，不影响功能

## 💡 常见陷阱（Gotchas）

- **major bump 的文档迁移可能耗时很长**：它本质上是一次完整的 reverse ref 模式运行。不要在对话上下文中将它与其他任务混合——迁移提示词需要独立的注意力。
- **选 B（稍后手动迁移）可能导致旧 doc 与新版 skill 不兼容**：新版 skill 可能依赖新版 doc 中的字段/章节。如果选了 B，尽快安排迁移。
- **模板一致性校验（步骤 3）易误报**：version 字段差异是预期的——update 的目的就是更新版本。只关注结构性差异（章节缺失、角色区块变更）。

---

## 注意事项

- 本 skill 负责触发版本升级流程，模板的权威来源是 `ai-sdd-init/templates/`
- skill 文件的更新是 AI-SDD 体系层面的事，需要人工维护
- 版本号与 AI-SDD skill 版本同步，记录在 `supplement-rules.md` 的 `version` 字段
