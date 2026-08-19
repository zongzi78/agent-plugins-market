---
name: ai-sdd-init
description: >
  初始化 AI-SDD 项目结构。在项目中创建 .ai/ 目录，包含 supplement-rules.md、project-log.md、doc/、changes/、ref/（含 sources.md 外部依赖清单）。
  触发词：AI-SDD 初始化、初始化 .ai 目录、给项目加上 AI 规范、SDD 初始化、.ai init
---

# AI-SDD 项目初始化

## 定位

在项目中创建完整的 AI-SDD v3 结构（.ai/ 目录）。创建后，项目即可接入 AI-SDD 工作流。

## 前置检查

1. 检查当前目录下是否已有 `.ai/` 目录
   - 如不存在：跳过此步骤，进入执行流程
   - 如存在：进入步骤 2

2. 逐个检查以下**文件**是否已存在且非空（目录不检查冲突，已存在则跳过创建）：

   | 文件 | 检查方式 |
   |------|----------|
   | `.ai/supplement-rules.md` | 是否存在且非空 |
   | `.ai/project-log.md` | 是否存在且非空 |
   | `.ai/doc/00-架构.md` | 是否存在且非空 |
   | `.ai/doc/01-行为目录.md` | 是否存在且非空 |
   | `.ai/doc/02-决策记录.md` | 是否存在且非空 |
   | `.ai/doc/03-详细设计/_模板.md` | 是否存在且非空 |
   | `.ai/doc/04-问题与改进.md` | 是否存在且非空 |

3. 根据冲突情况处理：

   - **无冲突**（所有文件都不存在或为空）：正常执行**执行流程**步骤 1-3。已存在的目录跳过创建，仅创建缺失的文件和目录。
   - **有冲突**：列出冲突文件清单，用 AskUserQuestion 询问用户处理方式：
     - "覆盖" — 用模板内容覆盖冲突文件（其他已存在文件保持不变）
     - "跳过" — 跳过冲突文件，仅创建当前缺失的文件和目录
     - "取消" — 终止初始化，不做任何修改

4. **VCS 上下文探测**（始终执行；结果用于步骤 0-3 与 project-log 记录）：

   - **三层探测**：
     - **向上**：从当前目录逐级向上查找 `.git` / `.svn`（直至文件系统根）
     - **向下**：递归检查子目录是否存在嵌套 `.git`（深度 ≤ 3 层，避免过深扫描）
     - **当前目录**：确认自身是否为仓库根
   - **四态判定与处理**：
     - **git 仓库** → 直接用，不改动；后续初始化输出标注"VCS：git"
     - **SVN 工作树** → **检测态、非执行分支**：**不执行 git init**；提示"最终提交由人类在 SVN 完成"；安全层选择快照模式（此处仅记录该选择；改前备份由项目留痕规则执行，见 supplement-rules §6 与 sdd-apply「留痕纪律」）
     - **无 VCS** → 用 AskUserQuestion 询问（默认光标：选项 1）：
       - 1（推荐）**快照模式**：默认，不建仓，由 `.ai/backups/` 提供改前备份（此处仅创建目录并记录选择；改前备份由项目留痕规则执行，见 supplement-rules §6 与 sdd-apply「留痕纪律」）
       - 2 **git init 本地镜像**：说明三点——本地历史只存本机、无远端、需播种 `.gitignore`（须包含 `.ai/backups/` 与 `.sync-backup/`，防止备份目录入库；模板见 `templates/gitignore.md`）
       - 3 取消
     - **嵌套仓库** → 警告 + 明确边界："外层 init 不纳入嵌套仓库（<路径>），避免 git embedded repo"（若当前已是 git 仓库且下方含嵌套 `.git`：仍按 git 分支执行，同时输出嵌套警告）
   - 将探测结果与用户选择记录，待步骤 1 创建 `.ai/project-log.md` 后写入其「VCS 状态」区段（记录 VCS 状态，便于后续技能复用）

## 执行流程

### 步骤 0：自动模式判断

在执行目录和模板创建之前，AI 通过综合上下文自主判断当前是正向（greenfield）还是逆向（reverse）模式。

**正向模式（greenfield）的信号**：
- 项目根目录仅有框架脚手架文件（如刚执行完 create-react-app / npx create-next-app /uv init 等）
- 或：`src/` 下基本为空，无可识别的业务模块目录
- 或：用户在对话中明确表达"新项目"、"从零开始"、"新建"、"初始化新项目"

**逆向模式（reverse）的信号**：
- 项目根目录存在多个包含业务逻辑的源文件
- 或：存在数据库 schema / API 路由定义 / 业务模块目录等实质性代码
- 或：用户在对话中明确表达"现有项目"、"遗留项目"、"逆向文档化"、"给它做逆向"

**判断原则**：
- AI 已在项目工作空间中，可以直接扫描目录结构做出判断
- 不要仅凭单个文件判断——综合多个信号
- 结合「前置检查」步骤 4 的 VCS 探测结果：git 仓库且有大量提交 → 更可能是 reverse；无 VCS 的空目录 → 更可能是 greenfield
- 如有歧义（例如项目同时有脚手架文件和部分业务代码），用 AskUserQuestion 询问用户：
  "我看到项目里同时有脚手架文件和一些业务代码。你想对这个现有项目做逆向文档化（reverse 模式），还是在这个基础上开始一个新的正向设计（greenfield 模式）？"

注：模式判断仅在 `.ai/` 目录不存在时（首次 init）有意义。如果 `.ai/` 已存在，自动模式判断不再执行，直接进入前置检查的冲突处理分支（覆盖/跳过/取消）。

### 步骤 1：创建目录结构

在项目根目录下创建：

```
.ai/
├── supplement-rules.md          ← 从本 skill 的 templates/ 复制（version 字段与当前 AI-SDD 版本同步）
├── project-log.md               ← 从本 skill 的 templates/ 复制
├── doc/
│   ├── 00-架构.md               ← 从本 skill 的 templates/doc/ 复制
│   ├── 01-行为目录.md            ← 从本 skill 的 templates/doc/ 复制
│   ├── 02-决策记录.md            ← 从本 skill 的 templates/doc/ 复制
│   ├── 03-详细设计/
│   │   └── _模板.md             ← 从本 skill 的 templates/doc/03-详细设计_模板.md 复制
│   └── 04-问题与改进.md          ← 从本 skill 的 templates/doc/ 复制
├── changes/
│   └── archive/                 ← 空目录
└── ref/
    ├── sources.md               ← 外部依赖清单（从本 skill 的 templates/ 复制）
    └── cache/                   ← 本地缓存（可选，应加入 .gitignore）
```

**按 VCS 探测结果的条件动作**（在创建上述目录后执行）：

- 无 VCS 且用户选择**快照模式**（选项 1）→ 额外创建 `.ai/backups/` 空目录（预留目录；改前备份由项目留痕规则执行，见 supplement-rules §6 与 sdd-apply「留痕纪律」）
- 无 VCS 且用户选择 **git init**（选项 2）→ 在项目根执行 `git init`（本地镜像，无远端），并播种 `.gitignore`（内容从本 skill 的 `templates/gitignore.md` 复制，须包含 `.ai/backups/` 与 `.sync-backup/`）
- SVN 工作树 → **不**执行 git init、不创建 `.ai/backups/`（仅记录选择；备份目录由首次改前备份时自动创建）
- git 仓库 → 不做任何额外动作

### 步骤 2：输出工具集成指引

完成创建后，输出以下文本：

```
.ai/ 目录已创建完成。包含：
  .ai/supplement-rules.md      — AI-SDD 行为准则（"宪法"，纯原则层）
  .ai/project-log.md           — 项目日志（活跃 Change + 变更时间线）
  .ai/doc/                     — 规范文档目录（架构、行为目录、决策记录、详细设计、问题与改进）
  .ai/changes/                 — 变更管理目录（活跃 change + 归档）
  .ai/ref/                     — 外部依赖清单（sources.md + cache/）
  VCS 状态：<git / SVN（最终提交由人类完成）/ 快照模式（无 VCS，.ai/backups/ 预留）>

请在你的 AI 工具配置中添加以下指令：

  请先阅读 .ai/supplement-rules.md，然后按照其中的规则行事。

常见的配置位置：
  Claude Code    → CLAUDE.md
  Cursor         → .cursorrules
  Windsurf       → .windsurfrules
  Codex          → AGENTS.md
  通用           → 你的 AI 工具的指令/规则文件

如有项目私有规则（编码规范、命名约定等），可创建 .ai/project-rules.md，
并在配置中追加：请同时阅读 .ai/project-rules.md 作为项目私有规则补充。
```

> 若选择了 **git init 本地镜像**：已执行本地 `git init`（无远端）并播种 `.gitignore`（含 `.ai/backups/` 与 `.sync-backup/`）；后续如需远端，由人类自行添加。
> 若 VCS 为 **SVN**：不执行 git init；请记住最终提交由人类在 SVN 完成。

### 步骤 3：输出 v3 工作流介绍

输出 AI-SDD v3 工作流和技能体系概览：

```
AI-SDD v3 工作流概览：

日常功能开发流程：
  /sdd-propose → /sdd-explore → /sdd-apply → /sdd-sync → /sdd-archive
  (创建change)   (探索规划)     (执行编码)    (同步文档)   (归档)

工程环境技能（低频使用）：
  /ai-sdd-init      — 项目初始化（本技能）
  /ai-sdd-reverse   — 遗留项目逆向文档化
  /ai-sdd-check     — 文档健康检查（漂移检测）
  /ai-sdd-rebuild   — 文档严重漂移时重建
  /ai-sdd-diagnose  — 代码问题诊断（可独立运行或被reverse调用）
  /ai-sdd-update    — AI-SDD 版本升级

工作流技能（高频使用）：
  /sdd-propose   — 创建 change（需求入口）
  /sdd-explore   — 深度探索 + 制定实施方案
  /sdd-apply     — 按 plan 执行编码
  /sdd-sync      — 设计变更同步回 .ai/doc/
  /sdd-archive   — 归档完成的 change
```

---

## 💡 常见陷阱（Gotchas）

- **初始化后 .ai/doc/ 下的模板文件只有 front matter 结构**：内容全部需要由 reverse 填充。不要试图在 init 阶段就填写内容。
- **自动模式判断（greenfield vs reverse）的信号列表是启发式的**：如果项目同时在 git 中有超过 100 次提交且目录结构简单，可能误判。不确定时询问人类。
- **模板中的「📋 本文档角色」区块是各 skill 判断写入范围的依据**：如果模板被修改，所有下游 skill 的行为都会受影响。修改模板前确认对整套 skill 的影响。
- **`ref/` 结构中仅 `sources.md` 从模板生成**：`cache/` 为空目录，由人类按需使用。其他 skill 不会自动维护 ref/ 下的内容——这完全是人类管理的空间。
