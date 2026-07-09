---
name: ai-sdd-update
description: >
  AI-SDD 版本升级。两级操作：minor bump 仅更新 supplement-rules.md（轻量）；
  major bump 时额外调用 reverse ref 模式迁移 doc 文件（重量）。
  触发词：更新 AI-SDD 规则、同步 supplement-rules、更新 .ai 规则、update ai-sdd rules
---

# AI-SDD 版本升级

## 定位

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

当用户选择"立即迁移"时，将 `.ai/doc/` 作为 ref 路径传入 reverse，注入以下提示词：

```
## 场景：AI-SDD 版本升级 — 文档体系迁移

项目正在从 AI-SDD v[旧版本] 升级到 v[新版本]。

### 升级背景

本次升级涉及文档体系的以下结构性变更：

[此处逐项列出变更，例如：]
- 01-需求.md → 01-行为目录.md：角色从"需求清单"变为"可观察行为清单"
  - 新增必须内容：行为粒度标准（四条件）、行为状态标注（活跃/不完整/疑似废弃）
  - 删除不应出现的内容：数据域定义（→03）、需求漂移判断（→04）
- 02-技术选型.md → 02-决策记录.md：角色从"技术清单"变为"决策知识库"
  - 新增必须内容：D-XXX 决策条目、推断理由、状态标记
  - 删除不应出现的内容：版本风险判断（→04）、API 细节（→03）
- 新增：04-问题与改进.md — 七范畴问题目录（AV/DR/FD/VR/MT/DD/CD）
- 各文档的角色边界已重新定义，详见模板顶部的「📋 本文档角色」区块

### Ref 文档的性质

你要处理的 ref 文档（`.ai/doc/` 下的所有文件）是**按旧版本模板和角色定义生成的**。
它们的**内容可能仍然正确**（反映了代码事实），但**结构、组织方式、内容归属
需要适配新版本**。

关键区别：
- **与 rebuild 不同**：ref 文档**不一定腐烂**——它们可能准确反映了代码，
  只是组织方式与新版不兼容
- **与首次 reverse 不同**：有大量现有内容可以复用，不是从零开始

### 你的任务

#### 任务 1：结构迁移（Structural Migration）
按新版模板的角色区块约束，将旧文档的内容重新分配到新结构中。

迁移规则：
- 内容在新版模板中有对应章节 → 迁移到对应章节
- 内容在新版模板中没有对应章节，但符合某份文档的角色定义 → 放入最匹配的文档
- 内容在新版模板中没有对应章节，且不符合任何文档的角色定义 → 删除（旧版本特有内容，新版本不再需要）
- **不确定归属的内容** → 放入最可能的文档并标注 `⚠️ 待确认：从旧版[文件名]迁移，归属待人类确认`

迁移时，逐文档、逐章节处理。不批量操作，确保每条内容都被考虑到。

#### 任务 2：新增补齐（Generate New Sections）
新版模板有、但旧文档中没有的章节/条目类型，从代码生成补齐。

检查清单（逐文档）：
- [ ] `00-架构.md`：是否有新版要求的"认知边界地图"章节？
- [ ] `01-行为目录.md`：每个行为条目是否满足新版的行为粒度标准（四条件）？
- [ ] `02-决策记录.md`：是否从"技术清单"转为"D-XXX 决策条目"格式？
- [ ] `03-详细设计/*.md`：是否按新版的内容条件（而非旧版权重等级）展开章节？
- [ ] `04-问题与改进.md`：是否包含七范畴（AV/DR/FD/VR/MT/DD/CD）？
  如旧版没有此文件 → 调用 ai-sdd-diagnose 从代码生成

对于需要从代码生成补齐的内容，遵循 reverse 对应阶段的 SOP 标准。

#### 任务 3：格式适配（Format Adaptation）
确保每份文档：
- 顶部有最新的「📋 本文档角色」区块
- front matter 字段与新版模板一致
- 使用了新版的章节结构和标题层级
- 引用了正确的编号体系（B-XXX、D-XXX、AV-XXX 等）

#### 任务 4：元信息保留（Metadata Preservation）
以下内容在迁移时优先保留：
- `02-决策记录.md` 中 `status=Confirmed` 的决策条目（保留理由，迁移到新格式）
- `01-行为目录.md` 中人类确认的行为状态裁决
- `project-log.md` 中的变更时间线
- 各类时间戳（`last_code_verified` 等）

如元信息的格式与新版本不兼容 → 转换为新格式，保留语义。
如元信息引用了旧版本特有的编号/章节 → 更新为新版本的对应引用。

#### 任务 5：版本记录
在 project-log.md 中记录本次迁移：

```
### [日期] AI-SDD 版本升级 v[旧] → v[新]
**升级类型**：major bump（文档体系迁移）
**迁移内容**：
  - [列出每个文件的迁移操作]
**人类确认**：已确认
```

### 质量要求

与首次 reverse 相同：遵循全部正向 6 条 + 负向 5 条质量规则。
特别强调：
- **不丢失信息**：旧文档中的有效内容必须在新结构中找到对应位置
- **不伪造信息**：只迁移代码可以验证的内容。旧文档中有但代码无法验证的陈述 →
  标注 `⚠️ 待确认：来自旧版文档，无法从代码验证`
- **宁可多留不丢**：不确定归属的内容放入最可能的文档并标注，而不是直接删除
```

---

## 版本号规则

- `major.minor.patch` 格式（如 1.7.3）
- **major 变更**：breaking changes，AI 行为有重大调整
- **minor 变更**：向后兼容的功能补充
- **patch 变更**：bug 修复，不影响功能

## 注意事项

- 本 skill 负责触发版本升级流程，模板的权威来源是 `ai-sdd-init/templates/`
- skill 文件的更新是 AI-SDD 体系层面的事，需要人工维护
- 版本号与 AI-SDD skill 版本同步，记录在 `supplement-rules.md` 的 `version` 字段
