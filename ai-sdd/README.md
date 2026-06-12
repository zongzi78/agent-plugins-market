# AI-SDD Plugin

AI-SDD (AI-Assisted Spec-Driven Development) v3 方法论插件。

一套完整的规范驱动开发工作流，让你的 AI 编码助手从"无脑写代码"升级为"有章法的协作开发"。

## 技能列表

### 环境技能（低频）

| 技能 | 调用方式 | 说明 |
|------|---------|------|
| ai-sdd-init | `/ai-sdd-init` | 项目初始化，创建 `.ai/` 目录结构 |
| ai-sdd-reverse | `/ai-sdd-reverse` | 遗留项目逆向文档化 |
| ai-sdd-check | `/ai-sdd-check` | 文档健康检查（漂移检测） |
| ai-sdd-rebuild | `/ai-sdd-rebuild` | 文档严重漂移时重建 |
| ai-sdd-update | `/ai-sdd-update` | supplement-rules.md 版本更新 |

### 工作流技能（高频）

| 技能 | 调用方式 | 说明 |
|------|---------|------|
| sdd-propose | `/sdd-propose` | 创建 change（需求入口） |
| sdd-explore | `/sdd-explore` | 深度探索 + 制定实施方案 |
| sdd-apply | `/sdd-apply` | 按 plan 执行编码 |
| sdd-sync | `/sdd-sync` | 设计变更同步回 `.ai/doc/` |
| sdd-archive | `/sdd-archive` | 归档完成的 change |

## 快速开始

1. 在项目中初始化 AI-SDD：`/ai-sdd-init`

2. 在配置文件中添加指令：
   - **Claude Code** — 在 `CLAUDE.md` 中：`请先阅读 .ai/supplement-rules.md，然后按照其中的规则行事。`
   - **Codex** — 在 `AGENTS.md` 中：`请先阅读 .ai/supplement-rules.md，然后按照其中的规则行事。`

3. 开始开发：`/sdd-propose 帮我实现 XXX 功能`

4. 按引导走完工作流：`/sdd-propose → /sdd-explore → /sdd-apply → /sdd-sync → /sdd-archive`

## 工作流

```
/sdd-propose → /sdd-explore → /sdd-apply → /sdd-sync → /sdd-archive
(创建)         (探索)         (执行)        (同步)       (归档)
```

## 什么是 AI-SDD

- **怎么想**（supplement-rules.md）— 思维框架和行为原则
- **做什么**（`.ai/doc/`）— 需求、架构、设计
- **怎么做**（/sdd-* 工作流技能）— 开发流程和工具

## 许可证

MIT License
