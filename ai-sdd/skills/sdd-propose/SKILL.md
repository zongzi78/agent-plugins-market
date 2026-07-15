---
name: sdd-propose
description: >
  创建 change。接收用户的初步需求说明，产出专业的 proposal.md。不深入探索代码。
  触发词：创建change、提出需求、新建变更、新功能、propose、提一个需求、开始一个变更
---

# sdd-propose（创建 change）

## 定位

轻量级需求入口。接收用户的初步需求说明，产出专业的 proposal.md。不深入探索代码。

## 前置检查

1. `.ai/` 不存在 → 提示"请先执行 `/ai-sdd-init` 初始化项目环境"，终止
2. 读取 `.ai/supplement-rules.md`（如存在）→ §一（权限边界）确认需求是否在 Agent 自主决定范围内；项目特定约束节检查需求是否与架构约束冲突 → 如有冲突，proposal.md 中标记 `⚠️ 约束冲突：[编号]`

## 执行流程

### 步骤 1：收集需求

如用户未提供需求描述，通过 AskUserQuestion 询问三个问题：
- 要做什么？（一句话）
- 为什么要做？
- 预期影响哪些模块？

### 步骤 2：派生名称 + 检测碰撞

1. 从描述中派生名称。**优先使用中文**；不方便中文描述时可用英文，专有名词用英文。不确定时 AskUserQuestion 确认
2. 确定序号：**仅扫描 `.ai/changes/` 的直接子目录**（即第一级子目录），**完全排除 `.ai/changes/archive/` 目录及其内容**。从目录名中解析 `NNN` 前缀数字，取最大值+1（三位数补零）。若没有活跃 change，序号为 `001`
3. **碰撞检测**：扫描 `.ai/changes/` 中的活跃 change，名称冲突则追加 `-2`、`-3` 后缀

### 步骤 3：创建 change 目录和文件

1. 创建文件夹 `.ai/changes/NNN-名称/`（**不含日期前缀**，日期前缀仅归档时使用）
   - 示例：`.ai/changes/001-用户认证/`、`.ai/changes/003-fix-login-bug/`
2. 以更专业、更精准的角度重写用户需求，生成 `proposal.md` — **Read [templates/proposal-template.md](templates/proposal-template.md) now and use it as the structure template.**
3. 创建空的 `plan.md`（占位，仅含 front matter，后续由 `/sdd-explore` 填充）

### 步骤 4：更新 project-log.md

更新 `.ai/project-log.md` 的「活跃 Change」区段，添加一行记录。

### 步骤 5：输出摘要 + 引导

```
✅ Change 已创建：.ai/changes/NNN-名称/
   proposal.md — 需求提案
   plan.md     — 待填充（占位）

接下来可通过 /sdd-explore 深度探索代码并制定实施方案。
```

---

## Change Status 定义

| 状态 | 含义 | 设置时机 |
|------|------|----------|
| `draft` | 刚创建，待探索 | sdd-propose 创建时 |
| `planned` | 方案已确定 | sdd-explore 完成 plan.md 后 |
| `completed` | 已完成 | sdd-archive 归档时 |

---

## 💡 常见陷阱（Gotchas）

- **change 名称的派生逻辑**：优先使用中文（方便人类浏览），但专有名词用英文。"修复登录 Bug"不是好的 change 名，"修复登录超时未重定向问题"才是。
- **序号派生只扫描活跃 change**（`.ai/changes/` 一级子目录），完全排除 `archive/` 目录。如果扫描了 archive，序号会错误地越过已归档 change。
- **碰撞检测只在活跃 change 中检查**：不与 archive 重名检查。如果手动删除了 change 目录，序号会出现不连续——这是已知行为，不是 bug。

---

## 联动设计

- **拒绝路径**：见「前置检查」
- **完成后引导**：`✅ Change 已创建：.ai/changes/NNN-xxx/。接下来可通过 /sdd-explore 深度探索代码并制定实施方案。`
