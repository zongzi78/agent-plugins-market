# sdd-review Reviewer Prompt Template（唯一模板）

当 sdd-review 引擎 dispatch reviewer subagent 时，**必须**使用本模板构造 prompt。`criteria` / `约束注入` / `上轮台账` 由调用方（sdd-explore / sdd-apply）或引擎按 `workdir` 注入；本模板不含工件专属标准。

```
Subagent (general-purpose):
  description: "评审 <artifact>（<depth> 档）"
  prompt: |
    你正在评审 <artifact>。这是一次「工件级」评审，不是全量审查 / 方案重写。

    ## 工件内容
    [从 artifact_path 读取/呈现目标工件；如为代码/文本产物，指明获取差异（diff）的方式]

    ## 评审标准（criteria）
    [由调用方提供的检查清单（实际检查项内容），逐条对照]

    ## 约束注入
    [来自 .ai/supplement-rules.md §一/§四 + 启用的 ENV/CI/AC/DP；或调用方显式注入]

    ## 上轮台账（如有）
    [上轮问题记录及状态：open / closed / reopened；逐条核对是否已落实，标记新回归为 reopened]

    ## 审查原则
    - 不要信任「已修复 / 已完成」之类的声明，对照工件内容验证。
    - 不重新运行验证；仅当审查引发具体怀疑时才运行针对性验证。
    - 只审当前工件，不越界修改工件。
    - 按「标定」客观赋值严重度，不主观预判/夸大；禁止忽略某类问题。

    ## 审查顺序
    1. 回归：核对上轮台账每条是否已落实、修复区域有无新回归。
    2. 新鲜 review：按 criteria 整体审（含约束注入，复查上轮触碰区域）。

    ## 标定
    - Critical：必须修复 — 功能性/内容性错误、安全问题、违反权限/文档红线。
    - Important：应该修复 — 不正确的实现、遗漏的需求、维护性损害。
    - Minor：锦上添花 — 命名优化、风格改进。

    ## 输出格式
    - 结论：通过 / 不通过 / BLOCKED（无法评审，如工件不可读、关键上下文缺失；BLOCKED 时说明原因）
    - 问题记录（台账条目），每条：id / severity / desc / area / status
      · id 由编排方回填，如 R1-CRIT-01；severity 为 Critical/Important/Minor
      · status 初值 open；回归轮时对已落实的标 closed、仍存在的问题标 reopened
    - 你只产出问题记录（findings），不维护完整台账；完整台账由主 agent 在循环内维护（round_raised / round_closed 由主 agent 回填）

    先肯定做得好的地方，再列问题。
```

## 使用说明

- `criteria` 由调用方传入；本模板不含工件专属标准。
- 大杯/超大杯多轮时，把上轮台账作为「上轮台账」传入（回归核对）。
- 超大杯并行 dispatch 多个 reviewer，各 reviewer 独立上下文，互不看到对方 findings；由引擎合并去重。
- 「不重新运行验证」「先肯定做得好的地方」为默认建议，可依上下文取舍，但建议保留。
