---
name: sdd-review
description: >
  工件无关的统一质量闸门引擎。定义质量循环（审 + 修 + 回归）：审由独立 reviewer subagent 执行，修由主 agent 在循环内执行。不负责「审什么、按什么标准审」。
  被 sdd-explore（plan review）与 sdd-apply（变更产物 review）作为闸门引擎调用，也可作为公开审查工具独立调用。
  触发词：review、帮我审查、帮我 review、看看这份 plan、审这轮改动、审查这份文档
---

# sdd-review（质量循环引擎）

## 定位

sdd-review 是一个工件无关的**质量循环引擎**，不是新的流程阶段。它在内部**定义循环（loop）**与**档位（中 / 大 / 超大杯）**：循环 = 审 + 修 + 回归；「审」由独立 reviewer subagent 执行，「修」由主 agent 在循环内执行（见「评审独立性」与「循环驱动算法」）。它不负责「审什么、按什么标准审」——后者由工件所属 skill（sdd-explore 提供方案评审标准、sdd-apply 提供产物评审标准）通过 `criteria` 参数传入。

作为引擎时，按调用方传入的 `artifact` / `criteria` / `depth` / `max_rounds` / `artifact_path` / `workdir` / `context` 运行循环；惟在用户独立调用时，可按「目标类型 + 默认标准」做轻量推断（属引擎允许的例外）。

它只做质量循环引擎，不用于诊断/一致性检测（ai-sdd-check / ai-sdd-diagnose），不做文档影响映射（sdd-sync）。

## 评审独立性（铁律）

评审**必须**由独立的 reviewer subagent 执行。调用方 / 编排方 agent（sdd-explore、sdd-apply）不得自任 reviewer，也不得用自己刚审阅过该工件的上下文「直接读一遍」代替评审；评审动作须 dispatch 一个**独立上下文**的 reviewer subagent 执行。独立性是评审可信度的唯一来源——主 agent 对自身编排或生产的工件存在确认偏置，自审会系统性漏检。

每次 dispatch reviewer subagent 必须按 `prompts/reviewer.md` 模板构造其 prompt（见「循环驱动算法」入口）。

若运行环境无法派发 subagent（或无法获得与主 agent 隔离的独立上下文），须先向人类明确说明「独立性受限、评审不可信」，以受限方式继续并报告人类；此路径**不代表评审具独立性**，属兜底降级，非常规路径。

## 调用方式

### 作为闸门引擎（被 explore / apply 调用）

调用方（sdd-explore / sdd-apply）进入本引擎（同一主 agent 会话），传入 `artifact` / `criteria` / `depth` / `artifact_path` / `workdir` / `context`；引擎据此运行内部循环，产出「评审记录」（PASS / ESCALATE_TO_HUMAN / 暂停）。修复由主 agent 在循环内执行（见「循环驱动算法」）。

### 独立调用（用户直接触发）

用户直接调用时，可只给目标与（可选）深度，其余走默认：

- `/sdd-review <目标> [深度]`；`<目标>` 可省略（默认当前 change 的 plan 或最新的变更产物），`深度` 可省略（默认中杯）。
- 目标类型推断：`.md` 文档若非 change 交付产物 → 按文档/计划类归一到通用质量闸门（见下方「独立调用默认标准」）；变更产物（代码/文档/配置等，含作为 change 交付物的 `.md`）→ 按产物类归一到通用质量闸门；无法判断时向用户确认一次（不再追问其它）。
- 默认：深度=中杯；max_rounds=6；标准 = 按目标类型推导的通用质量闸门 + 约束注入。

### 独立调用默认标准（通用质量闸门）

独立调用（无事主 skill 提供 criteria）时，引擎使用内嵌的**通用质量闸门**兜底。它是**通用维度**，不含工件专属细则（工件专属细则以 explore/apply 传入的 criteria 为准）：

- **目标回应**：是否回应了初始需求/目标；有无越界新增。
- **结构**：粒度是否可验证；依赖/顺序是否合理。
- **覆盖**：风险与注意事项是否覆盖每个改动点。
- **红线**：是否违反权限边界 / 文档红线（`.ai/doc/`）。
- **一致性**：设计与代码/产物现实是否匹配（此项为评审准则，非系统性一致性检测；系统性检测属 ai-sdd-check / ai-sdd-diagnose）。

若所审目标是 AI-SDD 工件（plan.md / 变更产物），且所在项目存在 `.ai/supplement-rules.md`，则读取并注入 §一/§四 + 启用的 ENV/CI/AC/DP 约束。

> 独立调用使用上述通用闸门；被 explore/apply 调用时，用调用方传入的 `criteria`（工件专属标准）替代。

## 输入参数

| 参数 | 类型 | 说明 | 必填 |
|------|------|------|------|
| `artifact` | enum | `plan.md` \| `变更产物`（代码/文档/配置等；独立调用时由目标推断） | 调用方调用时是 / 独立调用时可省略 |
| `criteria` | 引用/内联 | 评审检查清单**内容**（由调用方提供，传入的是实际检查项而非仅名称；独立调用时按目标类型推导默认标准） | 调用方调用时是 / 独立调用时可省略 |
| `depth` | enum | `中杯` \| `大杯` \| `超大杯`（默认中杯） | 否 |
| `max_rounds` | int | 默认 6 | 否 |
| `artifact_path` | path \| path[] | 目标工件位置（单个路径或文件列表） | 调用方调用时是 / 独立调用时可省略 |
| `workdir` | path | 读取约束/文档根 | 调用方调用时是 / 独立调用时可省略 |
| `context` | 文本 | 调用方共享上下文（背景 / 约束 / 前一阶段信息）；引擎提取评审所需部分注入 reviewer subagent（避免把整段会话历史塞给 subagent）。上轮台账作为独立传递项，不走 context | 否 |

> 约束注入来自 `workdir` 下的 `.ai/supplement-rules.md`（§一、§四 + 启用的 ENV/CI/AC/DP）；不在 `workdir` 时由调用方显式传入 criteria 文本。
## 深度档位

### 档位定义

| 档 | 内容 | 是否默认 |
|----|------|---------|
| 附随改动豁免（非档位） | 附带改动 / 非交付性说明（无可评审内容） | 自动 |
| 中杯 | 单轮评审，fix → re-review 回归 | 默认（所有可执行产物/计划） |
| 大杯 | 中杯 + 回归台账（跨轮） | 用户声明 |
| 超大杯 | 大杯 + 多 reviewer 并行 + 多轮回归 | 用户声明 |

### 附随改动豁免（自动，不进档位）

满足以下任一条件的变更，自动跳过 review（无可评审内容）：
- 随产物变更**附带**的纯注释、空行、格式改动（不改语义）；
- 非交付性的附加说明（如修正既有 README 的一处笔误、补充一句注释）。

**豁免是客观判定**，不按「行数多少」裁决。凡**交付物本身**为文档/配置/说明等（作为 change 的交付内容）时**不得豁免**，一律默认中杯。豁免属「无可评审内容」的客观判定，与深度档位降级无关（见「档位选择与单向严格」）。

### 档位选择与「单向严格」

- 默认 = 中杯（explore 与 apply 统一，已确认）。
- 人类在 prompt 声明 `用大杯/超大杯` 可上调。
- **agent 只能向上，不能向下**：不得把中杯降到「跳过」、不得把大杯降到中杯；要降级必须显式询问人类。
  （「附随改动豁免」是客观判定「无可评审内容」，与深度档位无关，不属此处「降级/跳过评审深度」。）

### MAX_ROUNDS

- **默认 6**。
- 单工件评审达到 6 轮仍未通过 → ESCALATE_TO_HUMAN，报告人类、质疑方案本身（触发「方案/设计可能有问题」信号）。
- 超大杯若用「连续 2 轮无新增才算稳定」，则该稳定判定嵌套在 6 轮上限之内。
## 循环驱动算法

```
# 所有 reviewer 均为独立上下文 subagent（评审独立性铁律）；每次构造 reviewer prompt 必须按 prompts/reviewer.md 模板
ledger = []
round = 1
loop:
  # 回归（Regression）—— 所有档位都执行
  if ledger 非空:
    reviewer_subagent 核对 ledger 每条：是否已落实？修复区域有无新回归？
    # 结果写入 ledger 状态（open→closed / 新回归→reopen）
  # 新鲜 review（Fresh）
  findings = reviewer_subagent 按 criteria 整体审（含约束注入，复查上轮触碰区域）
  if reviewer_subagent 连续返回 BLOCKED: result = 暂停; break
  # 分级（Triage）
  merge(findings, ledger)   # 关闭已解决、新增新问题
  # 收口（Exit）
  if 台账中无未关闭的 Critical/Important 且 findings 无 Critical/Important:   # Minor 不阻塞、仅记录
    result = PASS; break   # 以台账+findings 为准（reviewer「通过/不通过」供引擎判断，非唯一依据）
  if round >= max_rounds:
    result = ESCALATE_TO_HUMAN; break   # 质疑方案本身
  if 触发暂停条件（reviewer 连续 BLOCKED / 用户中断 / 发现设计矛盾）:
    result = 暂停; break
  # 修复（Fix）—— 由主 agent 在循环内执行，不 dispatch 独立 fixer subagent
  主 agent 针对 open 的 Critical/Important 逐项修复：只修 open 项、不越界、全部修完后重跑验证并报告
  round += 1
emit result + ledger 作为「评审记录」
```

> 超大杯的稳定判定（连续 2 轮无新增 Critical/Important）与暂停 / ESCALATE_TO_HUMAN 退出见「各档位行为」「停止与暂停条件」；本伪代码为通用骨架。

> 中杯：因无跨轮需求，`ledger` 只保存「单次修复前后」状态（隐式回归），`max_rounds` 实际只需 1-2 轮即收敛；大杯/超大杯才用跨轮台账。

## 问题台账数据结构

每条 issue 含字段：

| 字段 | 含义 | 必填 |
|------|------|------|
| `id` | `R<提出轮>-<SEV>-<序号>`，如 `R1-CRIT-01` | 是 |
| `severity` | `Critical` \| `Important` \| `Minor` | 是 |
| `desc` | 问题描述 | 是 |
| `round_raised` | 提出轮 | 是 |
| `status` | `open` \| `closed` \| `reopened` | 是 |
| `round_closed` | 关闭轮（closed 时） | 否 |
| `area` | 触达文件/章节 | 否 |

> `reopened` 表示「上一轮已修、本轮回归发现仍未好」，需重新进入修复（由主 agent 在循环内处理）。
> 严重度缩写（CRIT/IMP/MIN）与问题编号规则为 AI-SDD 体系约定（见 .ai/doc 与 supplement-rules）。
> 台账由主 agent 在循环内维护，每轮注入 reviewer subagent（跨轮信息传递）；中杯无跨轮台账，仅记录单次修复前后。
## 各档位行为

**中杯**：产出 → 独立 reviewer subagent 单轮审 → 有 Critical/Important 则**主 agent 在循环内修** → re-review **必须**验证修复落实、有无新回归（必须回归）。无跨轮台账；中杯通常 1-2 轮收敛，未收敛则继续至 `max_rounds=6` 上限（达到上限按「停止与暂停条件」处理）。

**大杯**：产出 → 独立 reviewer subagent 第 1 轮审 → 建台账 → **主 agent 在循环内修** → 每轮先「回归台账」再由独立 reviewer subagent「新鲜 review」→ 直到台账全 closed 且本轮无新 Critical/Important。

**超大杯**：同大杯，但每轮并行 dispatch N 个独立 reviewer（各自独立上下文）合并发现，N 不设硬上限（建议 3）；并通过「连续 2 轮无新增 Critical/Important」判稳定，嵌套在 `max_rounds=6` 内。

## reviewer 角色与 prompt 模板

**reviewer 输入**：工件内容 + criteria + 约束注入 + 上轮台账（如有）。
**reviewer 输出**：通过 / 不通过 / BLOCKED（无法评审，如工件不可读、关键上下文缺失；BLOCKED 时说明原因）+ 问题记录（台账条目：id / severity / desc / area / status；round_raised / round_closed 由主 agent 回填）。
**reviewer 约束**：按「标定」客观赋值严重度，不主观预判/夸大；禁止忽略某类问题；只审当前工件，不越界修改工件。

**修复（Fix）**：由主 agent 在循环内执行，不 dispatch 独立 fixer subagent；见「循环驱动算法」。

**Read [prompts/reviewer.md](prompts/reviewer.md) now** and use it as the template for constructing each reviewer's prompt.
## 评审记录（留痕）格式

写入调用方指定位置（explore / apply 写到 plan.md 末尾；独立调用时直接输出）：

```
## 评审记录
- 工件：plan.md / 变更产物（<file list>）
- 独立性：完整 / 受限（受限降级时记录并说明，见「评审独立性铁律」）
- 档位：大杯
- 轮数：3
- 问题清单：
  - R1-CRIT-01 边界未处理 → closed in R2
  - R1-IMP-02 命名不规范 → closed in R2
  - R3-MIN-05 注释冗余 → closed in R3
- 结果：PASS
```

## 停止与暂停条件

| 条件 | 行为 |
|------|------|
| 台账中无未关闭的 Critical/Important + 本轮无新 Critical/Important（Minor 不阻塞、仅记录） | PASS，结束 |
| 达到 `max_rounds`（默认 6） | ESCALATE_TO_HUMAN，质疑方案本身 |
| reviewer 连续返回 BLOCKED | 暂停，报告具体阻塞原因 |
| 用户中断 | 暂停，保留当前台账（可恢复） |
| 发现工件与 plan 冲突的设计矛盾（仅 artifact=变更产物 场景） | 暂停，报告矛盾点，不自行裁决 |
| 发现 plan 与代码/产物现实矛盾（artifact=plan.md 场景） | 暂停，报告矛盾点，不自行裁决 |

---

## 💡 常见陷阱（Gotchas）

- **不要替调用方制定策略**：引擎不感知、不推断、不制定深度/闸门/档位；只执行传入的 `depth` / `max_rounds` / `criteria`。惟独立调用时可按「目标类型 + 默认标准」做轻量推断（见上）。
- **criteria 永远是调用方的事**：本 skill 不内嵌 plan/产物专属标准；那些留在 sdd-explore / sdd-apply。独立调用时的「通用质量闸门」仅是兜底（属允许例外），被调用时标准一律来自调用方传入的 `criteria`。
- **达到 max_rounds 即暂停**：不要「再多跑一轮试试」；这是收敛信号，应报告人类并质疑方案本身。
- **中杯也必须回归**：主 agent 修复 → re-review 时必须验证修复落实 + 无新回归；虽无跨轮台账，但不可只重跑一遍即判通过。
- **谁修**：修由主 agent 在循环内执行（针对 open 的 Critical/Important 逐项修复），reviewer 只审不改；不要派发独立 fixer subagent。
- **超大杯并行 reviewer 独立上下文**：各 reviewer 互不看到对方 findings；由引擎合并去重。
- **禁止主 agent 自审**：reviewer 必须派发独立 subagent；不要为了省 token 用主 agent 的上下文「直接读一遍」。凡是没有 dispatch 独立 reviewer subagent 的评审，都不是合规评审。

## 联动设计

- **被调用方**：sdd-explore（plan review）、sdd-apply（变更产物 review）。
- **完成后输出**：`评审记录`（PASS / ESCALATE_TO_HUMAN / 暂停）。调用方负责将其写入 plan.md 末尾及后续（approve / auto-apply / 暂停报告）。修复由主 agent 在循环内执行（评审由独立 reviewer subagent 完成）。
- **拒绝路径**：参数缺失或 artifact 类型无法判断时（独立调用），向用户确认一次，不反复追问。