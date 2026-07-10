---
name: sdd-apply
description: >
  智能执行引擎：分析 plan.md 任务依赖，自动编排串行/并行执行，
  subagent 执行独立任务 + 审查循环保障质量。
  触发词：执行、开始编码、实施、apply、开始开发、按计划实施、执行方案
---

# sdd-apply（执行编码）

## 定位

执行以下工作流：

1. 分析 plan.md 任务依赖，判定串行/并行执行顺序
2. 调度 subagent 执行独立任务（implementer → reviewer → fixer 三角色）
3. 通过审查循环保障每个任务的交付质量
4. 输出结构化变更摘要供 sdd-sync 消费

## ⚠️ 铁律

**只修改项目代码，绝不修改 .ai/doc/ 下的任何文件。**
文档变更是 /sdd-sync 的专属职责。apply 阶段加载 .ai/doc/ 文件仅用于上下文参考。
如实现过程中发现文档需要变更，记录到 plan.md 的「文档变更」表中，由 sync 阶段处理。

## 前置检查（Hard Gate）

1. 无活跃 change → 拒绝，提示"请先通过 /sdd-propose 创建 change"
2. plan.md 为空（仅占位 front matter）→ 拒绝，提示"请先通过 /sdd-explore 制定实施方案"
3. 有多个活跃 change → 用 AskUserQuestion 让用户选择
4. plan.md 有已完成任务（`- [x]`）→ 提示"检测到部分任务已完成（X/N），将从第一个未完成任务继续"（断点续传）
5. 当检测到 git 仓库且当前在 main/master 分支时 → 简短提醒"⚠️ 当前在 main 分支，建议确认是否需要创建功能分支"，不阻塞执行

## 执行流程

### 步骤 1：加载与审阅（批判性检查清单）

0. 读取 `.ai/supplement-rules.md`（如存在）：
   - §一（权限边界）→ 确认 implementer 决策范围
   - §二（强制暂停规则）→ 实现中遇到歧义时对照
   - §四（文档操作红线）→ reviewer 检查依据
   - 项目特定约束节 → 分类处理：
     - 提取所有 **ENV 约束**（启用=是）→ 注入 implementer 的 system prompt：
       "环境约束（来自 .ai/supplement-rules.md，必须遵守）：..."
     - 提取所有 **CI/AC/DP 约束**（启用=是）→ 传递给 reviewer（Part 3）
1. 读取 plan.md、proposal.md、相关 .ai/doc/ 文件（含 `04-问题与改进.md`，确认已知陷阱）
2. 逐项检查：
   - [ ] plan.md 中每个文件路径存在，或有创建步骤
   - [ ] 每个任务有验证步骤 + 预期输出
   - [ ] 任务引用依赖都已定义
   - [ ] 任务顺序尊重数据依赖
   - [ ] plan.md 覆盖了 proposal.md 的全部范围
   - [ ] `## 文档变更` 章节的每个目标文件路径正确
   - [ ] **文档操作红线**：确认已加载的 .ai/doc/ 文件仅用于上下文参考。任何情况下不修改这些文件——文档变更是 /sdd-sync 的专属职责
3. 冲突预扫描：
   - [ ] 检查是否有任务操作同一文件的同一区域（冲突风险）
   - [ ] 检查是否有任务间的隐式依赖未被 plan.md 标注
   - [ ] 检查 plan.md 的全局约束是否有与任务描述矛盾之处
   - 发现问题 → 一次性列出，向人类确认。**不可自行裁决或假设"应该是这样"**
4. 如有疑虑：向人类提出，不猜测

### 步骤 2：并行度分析与编排

1. 对 plan.md 任务清单中的每个任务进行分析：

   **并行判定标准**（满足全部条件 = 可并行）：
   - 操作的文件集合与其他并行任务不重叠
   - 不依赖其他任务的输出或副作用
   - 不修改其他任务需要读取的共享模块接口

   **串行判定标准**（满足任一条件 = 必须串行）：
   - 同一文件被多个任务修改
   - 任务 B 依赖任务 A 的产出（类型定义、函数签名、数据结构）
   - 任务 B 需要在任务 A 建立的模式/框架下工作
   - 基础设施任务（如"搭建项目结构"）必须在其他任务之前

2. 输出编排方案到 plan.md 或进度记录中，格式如：
   ```
   批次 1：Task A ∥ Task B（并行，操作不同文件，无依赖）
   批次 2：Task C（串行，依赖 A 的接口定义）
   批次 3：Task D ∥ Task E（并行，共享 C 的产出）
   ```

3. 特殊情况：
   - 所有任务都必须串行 → 按 plan.md 原始顺序执行，不启动 subagent
   - 只有一个任务 → 直接执行，不启动 subagent
   - 无并行编排 → 跳过自审，直接执行

4. 如有并行编排 → dispatch 一个 reviewer subagent 自审编排方案：
   - 检查并行任务是否确实操作不重叠的文件集
   - 检查串行排序是否尊重了隐式依赖
   - 自审通过 → 执行；发现风险 → 调整方案后执行

### 步骤 3：逐批次执行

1. 创建 TodoWrite（内容来自 plan.md 任务清单）

2. 对每个批次：

   **【串行批次 — 主 Agent 直接执行】**
   - 标记 in_progress → 严格按 plan 步骤执行 → 运行验证
   - 为修改的代码编写规范注释（设计意图、边界条件），禁止写入文档路径引用
   - 同步更新 plan.md checkbox（`- [ ]` → `- [x]`）
   - 按照 `审查循环` 章节，dispatch reviewer subagent 审查 → 不通过则 fix → re-review
   - 标记 completed

   **【并行批次 — subagent 执行】**
   - **Read [prompts/implementer.md](prompts/implementer.md) now** and use it as the template for constructing each implementer's prompt.
   - 为批次内每个任务**并行** dispatch implementer subagent
   - 使用 `prompts/implementer.md` 模板构造 prompt，填入：
     · 该任务的 plan.md 原文（精确步骤 + 验收标准）
     · 任务上下文（1-2句，该任务在整个 change 中的位置）
     · 相关的 .ai/doc/ 规范摘要
     · plan.md 的全局约束（命名规范、技术栈限制等）
   - 禁止在 prompt 中粘贴：会话历史、之前任务的执行摘要、无关代码
   - **所有 implementer 完成后**，逐个 dispatch reviewer：
     · 使用 `prompts/reviewer.md` 模板构造 prompt
     · 审查 spec 合规性 + 代码质量
     · 全部通过后，标记该批次所有任务 completed
     · 同步更新 plan.md checkbox

3. 遵循 plan 中的 commit 节奏

### 步骤 4：最终验证

1. 运行所有相关测试
2. 确认构建通过
3. 回顾 plan.md，确认所有 checkbox 已勾选
4. **铁律：没有验证证据不得声称完成**，若工作空间不具备运行测试的条件，应当 review 一遍 plan.md 和对应的修改，确认每个任务都已经执行
5. 每个验证结论附带具体证据（符号锚点 / 测试输出行 / diff 片段），不依赖主观判断词

### 步骤 5：输出结构化变更摘要

执行完成后，输出以下摘要（供 sdd-sync 和 sdd-archive 使用）：

```
## 变更摘要（apply 生成）

改动的符号:
  - 修改: ClassName::methodName() — 简要描述变更
  - 新增: ClassName::newMethod()
  - 删除: ClassName::removedMethod()
  - 新增文件: path/to/new/file
  - 删除文件: path/to/removed/file
```

此摘要追加到 plan.md 末尾。

---

## 审查循环

每个任务完成后（无论串行还是并行）执行审查循环：

### Reviewer 审查

**Read [prompts/reviewer.md](prompts/reviewer.md) now** and use it as the template for constructing each reviewer's prompt.

使用该模板 dispatch reviewer subagent，审查两项：
- **Spec 合规**：是否完整实现了 plan.md 中该任务的全部要求
- **代码质量**：逻辑是否正确、边界条件处理、是否符合项目规范、有无 YAGNI

### 审查结果处理

| 结果 | 处理 |
|------|------|
| 通过 | 任务完成，标记 completed |
| Critical/Important 问题 | dispatch fix subagent → re-review |
| Minor 问题 | 记录到 plan.md 该任务备注中，不阻塞流程 |
| 3轮不通过 | 暂停，报告人类，质疑方案本身 |

### Reviewer Prompt 构造

- 提供与 implementer 相同的任务原文作为验收标准
- 指明从哪里获取 diff
- 禁止预判问题严重程度
- 禁止指示 reviewer 忽略某类问题
- 最终全分支审查（如需要）是 Code Review 技能的责任，reviewer 只审当前任务

### Fixer Dispatch

**Read [prompts/fixer.md](prompts/fixer.md) now** and use it as the template for constructing each fixer's prompt.

- 将所有 Critical/Important 问题一并交给 fixer（不逐条派发）
- fixer 必须重跑相关测试并报告结果
- 修复后重新 dispatch reviewer 审查

### 跳过审查

以下情况可以跳过 reviewer，implementer 完成后直接标记完成：
- 纯文档修改（如更新 README.md、注释修正）
- 配置文件单行修改（如修改版本号、端口号）
- **同时满足以下三个硬性条件**：
  - (a) 变更行数 < 10 行（以 subagent 返回的 diff stat 为准，非人工估计）
  - (b) 变更仅涉及**单个文件**
  - (c) 变更类型为以下之一：字面量替换 / 类型修正 / 错误码新增 / 日志补充 / 断言添加
- 连续 3 个同类型任务审查均一次通过 → 后续同类型可降级为抽查

**硬性限制**：
- **累计阈值**：同一 change 内所有 <10 行的子任务累计变更行数 ≥50 行时，必须执行至少一次完整审查
- **同文件限制**：同一文件的变更累计 ≥3 次（即使每次都 <10 行），后续该文件的变更不能跳过审查
- **逻辑任务判定**：如果 plan.md 中多个 <10 行的任务属于同一逻辑功能，视为一个逻辑任务，累计行数判定

---

## Subagent 调度规范

### 三种角色

| 角色 | 职责 | 输入 | 产出 |
|------|------|------|------|
| implementer | 按 plan 步骤实现代码 | 任务原文 + 相关文件路径 + 全局约束 | 代码变更 + 自验证结果 |
| reviewer | 审查 spec 合规 + 代码质量 | 任务原文 + implementer 的 diff | 通过/不通过 + 问题清单 |
| fixer | 修复 reviewer 发现的问题 | 问题清单 + 原任务原文 | 修复 + 重跑测试结果 |

### 模型选择

- **implementer**：使用当前会话模型。如任务涉及复杂架构判断，考虑使用更强模型
- **reviewer / fixer**：与 implementer 同级或略低，审查是校对工作，不改变设计

### Implementer 状态处理

| 状态 | 处理方式 |
|------|---------|
| 完成 | 继续 reviewer 审查 |
| 完成但有疑虑 | 先读 concerns，涉及正确性/范围则处理后再审查；仅是观察则记录并继续审查 |
| 需要更多上下文 | 补充信息，重新 dispatch |
| 阻塞 | 1) 补充上下文重试 2) 拆小任务 3) 报告人类 |

---

## 执行原则

- **连续执行**：不要在每个任务间询问"是否继续"。人类调用 sdd-apply = 授权执行全部任务。只在遇到阻塞、歧义、或全部完成时暂停
- **最小旁白**：任务间不要输出进度摘要或反思，TodoWrite 和 plan.md checkbox 已经记录了状态
- **冲突即停**：发现 plan 描述与代码现实矛盾时，不自行裁决，立即报告
- **禁止并行操作同一文件**：即使编排方案将两个任务标记为并行，如果它们操作同一文件的不同区域，降级为串行执行
- **绝不碰 .ai/doc/**：即使发现文档中有明显的笔误或过时信息，也不在 apply 阶段修改。记录到 plan.md → 由 sync 处理。apply 修改文档 = 数据不一致

---

## 💡 常见陷阱（Gotchas）

- **并行任务共享隐式约定**：implementer 只看到自己的任务 prompt，看不到其他并行任务的上下文。如果两个任务共享隐式约定（如相同的工具函数签名），implementer 可能做出冲突的决策。编排时优先将可能共享约定的任务串行化。
- **跳过审查的累计效应**：3 个 <10 行的变更合并后可能引入复杂的交互 bug。如果同模块连续有多个跳过审查的任务，应降级为抽查模式而非继续跳过。
- **subagent prompt 膨胀**：容易因为想给 implementer "更多上下文"而粘贴会话历史——这会导致 token 爆炸。严格遵循模板：只传任务原文 + 1-2 句上下文 + 全局约束。
- **变更摘要遗漏**：implementer 可能在实现 task A 时"顺便修了" task B 范围的小问题。务必在步骤 5 变更摘要中交叉检查 git diff，确保遗漏的变更被记录。

## 暂停条件（8 种）

1. **任务描述不清** → 询问，不猜测
2. **发现设计问题** → 暂停，建议更新 plan.md 或回退到 sdd-explore
3. **遇到错误/阻塞** → 报告等待指导
4. **用户中断**
5. **连续验证失败3次** → 停止，质疑方案本身
6. **发现代码中已存在与 plan.md 矛盾的设计** → 暂停，报告具体矛盾点
7. **审查循环3轮未通过** → 暂停，质疑方案本身
8. **subagent 连续返回 BLOCKED** → 暂停，报告具体阻塞原因

---

## 联动设计

- **拒绝路径**：见「前置检查」
- **完成后引导**：`✅ 所有任务已完成（N/N），审查全部通过。接下来可通过 /sdd-sync 将设计变更同步到项目文档（sync 将分析 apply 生成的变更摘要），然后通过 /sdd-archive 归档本次 change。`
- **暂停时提示**：`⏸ 实施暂停（M/N 任务完成）。问题解决后可再次运行 /sdd-apply 继续（支持断点续传）。`
