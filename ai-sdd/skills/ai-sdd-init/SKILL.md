---
name: ai-sdd-init
description: >
  初始化 AI-SDD 项目结构。在项目中创建 .ai/ 目录，包含 supplement-rules.md、project-log.md、doc/、changes/、ref/。
  触发词：AI-SDD 初始化、初始化 .ai 目录、给项目加上 AI 规范、SDD 初始化、.ai init
---

# AI-SDD 项目初始化

## 定位

本 skill 在项目中创建完整的 AI-SDD v3 结构（.ai/ 目录）。创建后，项目即可接入 AI-SDD 工作流。

## 前置检查

1. 检查当前目录下是否已有 `.ai/` 目录
   - 如存在：提示"项目已有 .ai/ 目录，如需重新初始化请先删除"，终止

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
- 如有歧义（例如项目同时有脚手架文件和部分业务代码），用 AskUserQuestion 询问用户：
  "我看到项目里同时有脚手架文件和一些业务代码。你想对这个现有项目做逆向文档化（reverse 模式），还是在这个基础上开始一个新的正向设计（greenfield 模式）？"

注：模式判断仅在 `.ai/` 目录不存在时（首次 init）有意义。如果 `.ai/` 已存在，前置检查会终止流程。

### 步骤 1：创建目录结构

在项目根目录下创建：

```
.ai/
├── supplement-rules.md          ← 从本 skill 的 templates/ 复制
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
└── ref/                         ← 空目录，用于存放参考资料
```

### 步骤 2：输出工具集成指引

完成创建后，输出以下文本：

```
.ai/ 目录已创建完成。包含：
  .ai/supplement-rules.md      — AI-SDD 行为准则（"宪法"，纯原则层）
  .ai/project-log.md           — 项目日志（活跃 Change + 变更时间线）
  .ai/doc/                     — 规范文档目录（架构、行为目录、决策记录、详细设计、问题与改进）
  .ai/changes/                 — 变更管理目录（活跃 change + 归档）
  .ai/ref/                     — 参考资料目录

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
  /ai-sdd-update    — supplement-rules.md 版本更新

工作流技能（高频使用）：
  /sdd-propose   — 创建 change（需求入口）
  /sdd-explore   — 深度探索 + 制定实施方案
  /sdd-apply     — 按 plan 执行编码
  /sdd-sync      — 设计变更同步回 .ai/doc/
  /sdd-archive   — 归档完成的 change
```
