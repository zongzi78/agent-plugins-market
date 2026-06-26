# Fixer Subagent Prompt Template

当 reviewer 发现 Critical/Important 问题后，dispatch fixer subagent 修复。

```
Subagent (general-purpose):
  description: "修复 Task N: [任务名称] 的审查问题"
  prompt: |
    你正在修复一个任务实现中的审查问题。

    ## 任务需求

    [从 plan.md 摘取该任务的完整文本]

    ## 需要修复的问题

    [reviewer 发现的 Critical/Important 问题列表，逐条列出：
     - 文件名
     - 问题描述
     - 为什么是问题
     - 修复建议（如 reviewer 提供了）]

    ## 你的工作

    1. 逐条修复上述问题
    2. 不做超出问题范围的改动
    3. 重跑相关测试并报告结果
    4. 报告修复内容

    **如果修复某个问题会引入新的风险，先报告再动手。**

    ## 报告格式

    - **状态：** DONE | BLOCKED
    - 修复了哪些问题（逐条对应）
    - 测试结果（一行摘要）
    - 新引入的改动（如有）
    - BLOCKED 时说明原因
```

## 使用说明

- 将所有 Critical/Important 问题一并交给一个 fixer（不逐条派发多个 fixer）
- fixer 的职责是修复，不是重新实现
- 修复后必须重新 dispatch reviewer 审查
- 如果 3 轮 fix → review 仍未通过，暂停并报告人类
