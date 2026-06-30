---
name: ai-sdd-update
description: >
  更新项目中的 AI-SDD 行为准则（supplement-rules.md）到最新版本。
  只更新"宪法层"，不修改项目私有文件。
  触发词：更新 AI-SDD 规则、同步 supplement-rules、更新 .ai 规则、update ai-sdd rules
---

# AI-SDD 体系更新

## 定位

当 AI-SDD 方法论版本升级时，更新项目中的 `.ai/supplement-rules.md` 到最新版。

**精确边界**：
- ✅ 更新 `.ai/supplement-rules.md`（宪法层）
- ✅ 提示检查 `.ai/project-rules.md` 是否需要同步调整
- ❌ 不修改 `.ai/project-log.md`（项目私有数据）
- ❌ 不修改 `.ai/doc/`（项目私有规范）
- ❌ 不修改 `.ai/project-rules.md`（项目私有规则）
- ❌ 不修改 skill 文件本身（体系层面的事）

## 前置检查

1. 检查 `.ai/supplement-rules.md` 是否存在 → 如不存在，提示先运行 `/ai-sdd-init`
2. 读取当前文件的 `version` 字段

## 执行流程

### 步骤 1：版本对比

1. 读取项目中 `.ai/supplement-rules.md` 的 `version` 字段
2. 读取本 skill 的 `templates/supplement-rules.md` 中的 `version` 字段
3. 比较两个版本号

### 步骤 2：判断是否需要更新

- **版本相同**：提示"已是最新版本（vX.Y），无需更新"，终止
- **版本不同**：继续步骤 3

### 步骤 3：模板一致性校验

在展示变更内容之前，检查本 skill 的模板与 `/ai-sdd-init` 的模板是否一致：

1. 对比两个 skill 的 `templates/` 目录中对应文件是否一致：
   - `templates/supplement-rules.md`
   - `templates/project-log.md`
   - `templates/doc/`（5 个 doc 模板）
2. 如不一致 → 警告用户"init 和 update 的模板不一致，update 的模板可能不是最新版"，列出不一致的文件
3. 如一致 → 继续步骤 4

### 步骤 4：展示变更

1. 读取两个版本的完整内容
2. 对比差异，生成变更摘要：
   - 新增了哪些章节/规则
   - 修改了哪些内容
   - 移除了哪些内容

### 步骤 5：确认并替换

1. 展示变更摘要
2. 用本 skill 的 `templates/` 中的最新版替换项目中的 `.ai/supplement-rules.md`
3. 保留项目中可能存在的 YAML front matter 中的 `updated_by` 等项目特定字段（如有）

### 步骤 6：后续提示

```
supplement-rules.md 已更新到 vX.Y。

提醒：
  - project-log.md 未被修改（项目私有数据）
  - .ai/doc/ 未被修改（项目私有规范）
  - 如有 .ai/project-rules.md，请自行检查是否需要同步调整
  - skill 文件的更新需手动进行（体系层面的事）
```

---

## 版本号规则

- `major.minor` 格式（如 1.0, 2.0, 2.1）
- **major 变更**：breaking changes，AI 行为有重大调整
- **minor 变更**：向后兼容的补充（如新增一条质量规则）

## 注意事项

- 本 skill 只管"宪法层"（supplement-rules.md），不管 skill 文件本身
- skill 文件的更新是 AI-SDD 体系层面的事，需要人工维护
- 设计文档 `AI-SDD-Skill设计文档.md` 中有"方法论变更 → 影响的 skill"映射表
