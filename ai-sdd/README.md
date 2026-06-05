# AI-SDD Plugin for Claude Code

AI-SDD (AI-Assisted Spec-Driven Development) v3 方法论插件。

一套完整的规范驱动开发工作流，让你的 AI 编码助手从"无脑写代码"升级为"有章法的协作开发"。

## 安装

### 方式一：从 Community Marketplace 安装

```
/plugin marketplace add anthropics/claude-plugins-community
/plugin install @claude-community/ai-sdd
```

### 方式二：从 GitHub 本地安装

```bash
git clone https://github.com/<owner>/ai-sdd-plugin.git
claude --plugin-dir ./ai-sdd-plugin
```

### 方式三：复制到 skills 目录

```bash
cp -r ai-sdd-plugin ~/.claude/skills/ai-sdd
```

## 技能列表

### 环境技能（低频）

| 技能 | 调用方式 | 说明 |
|------|---------|------|
| init | `/ai-sdd:init` | 项目初始化，创建 `.ai/` 目录结构 |
| reverse | `/ai-sdd:reverse` | 遗留项目逆向文档化 |
| check | `/ai-sdd:check` | 文档健康检查（漂移检测） |
| rebuild | `/ai-sdd:rebuild` | 文档严重漂移时重建 |
| update | `/ai-sdd:update` | supplement-rules.md 版本更新 |

### 工作流技能（高频）

| 技能 | 调用方式 | 说明 |
|------|---------|------|
| propose | `/ai-sdd:propose` | 创建 change（需求入口） |
| explore | `/ai-sdd:explore` | 深度探索 + 制定实施方案 |
| apply | `/ai-sdd:apply` | 按 plan 执行编码 |
| sync | `/ai-sdd:sync` | 设计变更同步回 `.ai/doc/` |
| archive | `/ai-sdd:archive` | 归档完成的 change |

## 快速开始

1. 在项目中初始化 AI-SDD：

   ```
   /ai-sdd:init
   ```

2. 在 `CLAUDE.md` 中添加：

   ```
   请先阅读 .ai/supplement-rules.md，然后按照其中的规则行事。
   ```

3. 开始开发：

   ```
   /ai-sdd:propose 帮我实现 XXX 功能
   ```

4. 按引导走完工作流：

   ```
   /ai-sdd:propose → /ai-sdd:explore → /ai-sdd:apply → /ai-sdd:sync → /ai-sdd:archive
   ```

## 工作流

```
propose → explore → apply → sync → archive
(创建)    (探索)    (执行)   (同步)  (归档)
```

- **propose**: 轻量级需求入口，产出 `proposal.md`
- **explore**: 深度代码探索 + 思维风暴，产出 `plan.md`
- **apply**: 严格按 plan 执行编码，含溯源注释和验证铁律
- **sync**: 将设计变更智能合并回项目规范文档
- **archive**: 归档完成的 change，更新项目日志

## 什么是 AI-SDD

AI-SDD 管三件事：

- **怎么想**（supplement-rules.md）— 思维框架和行为原则
- **做什么**（`.ai/doc/`）— 需求、架构、设计
- **怎么做**（sdd-* 工作流技能）— 开发流程和工具

适合希望 AI 在写代码时有章法、可追溯、可审计的开发团队。

## 许可证

MIT License
