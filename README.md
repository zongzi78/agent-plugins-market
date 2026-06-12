# Agent Plugins Market

统一的 AI Agent 插件市场，包含 Claude Code 和 OpenAI Codex 平台的插件。

## 包含的插件

| 插件 | 说明 | 分类 |
|------|------|------|
| [ai-sdd](./ai-sdd/) | AI-SDD v3 规范驱动开发方法论 | Development |
| [window-screenshot](./window-screenshot/) | Windows 窗口截图工具 | Productivity |

## 安装

### Claude Code

```
/plugin marketplace add zongzi78/agent-plugins-market
/plugin install ai-sdd@selfskill-plugins
/plugin install window-screenshot@selfskill-plugins
```

### OpenAI Codex

```
codex plugin marketplace add zongzi78/agent-plugins-market
```

安装后在 Plugins 列表中选择需要的插件。

## 快速开始

### AI-SDD

```
/ai-sdd-init
/sdd-propose 帮我实现 XXX 功能
```

详见 [ai-sdd/README.md](./ai-sdd/README.md)

### Window Screenshot

安装后，Agent 会在需要截图时自动使用。也可手动触发：

```
截一下当前窗口
```

详见 [window-screenshot/README.md](./window-screenshot/README.md)

## 添加新插件

1. 在仓库根目录下创建新的 plugin 文件夹
2. 添加 `.claude-plugin/plugin.json` 和/或 `.codex-plugin/plugin.json`
3. 在根目录的两个 marketplace.json 中添加对应条目
4. 提交推送，用户 `/plugin marketplace update` 即可获取

## 许可证

MIT License
