# 检测置信度与歧义细节（detection-notes.md）

> 深度参考，不承载关键行为。检测顺序与输出 schema 以 SKILL.md 为准；本节解释"为什么"与边界情况。

## 目录

- [1. 检测顺序（确定性，命中即停）](#1-检测顺序确定性命中即停)
- [2. 置信度规则](#2-置信度规则)
- [3. 歧义场景与处置](#3-歧义场景与处置)
- [4. decodeHints 说明](#4-decodehints-说明)
- [5. 平台严格度差异（已文档化）](#5-平台严格度差异已文档化)
- [6. 实现行为说明与已知边界](#6-实现行为说明与已知边界)

## 1. 检测顺序（确定性，命中即停）

① BOM（含 UTF-32 排除与正文严格校验）→ ② NUL 密度全局预检（>1%，BOM 命中除外）→ ③ 空文件/全 ASCII → ④ 严格 UTF-8 → ④a 双合法检测（UTF-8 与 GBK 均可解）→ ⑤ 严格 GBK → ⑥ 严格 GB18030 → ⑦ unknown。

- BOM 命中后仍需对去除 BOM 的剩余字节做同编码严格校验；校验失败 → `confidence: medium` + 损坏提示（"带 BOM 但正文无法严格解码，可能已损坏"）。
- NUL 预检命中 → 无论后续命中哪个类别，`confidence` 一律 `medium`，decodeHints 加 NUL 提示。
- ASCII/空文件 → `low`（ASCII 是 GBK/UTF-8 双合法歧义样本）。
- 双合法 → `utf-8` + `medium` + 提示 `valid in both utf-8 and gbk; follow project policy`。
- GBK-only → `gbk/high`；GB18030-only → `gb18030/high`；以上皆否 → `unknown/low`。

## 2. 置信度规则

| 场景 | confidence | 说明 |
|------|-----------|------|
| 空文件 / 纯 ASCII | low | 任何 DBCS 编码都"可解"，无判别力 |
| UTF-8 可解且 GBK 不可解（非 ASCII） | high | "GBK 可解"不是强证据，判别重心在"UTF-8 严格解码失败" |
| UTF-8 与 GBK 均可解（双合法） | medium | 贪婪 DBCS 使然；按项目策略处理 |
| NUL 密度 >1% | medium | 疑似无 BOM UTF-16/UTF-32 |
| GBK-only | high | 自动判定集内 |
| GB18030-only | high | 自动判定集内 |
| unknown | low | 不可写 |

## 3. 歧义场景与处置

- **ASCII / 空文件**：按项目约束（项目规则中声明的扩展名→编码映射）决定；不确定时问用户或按 UTF-8 处理但说明风险。
- **双合法**：UTF-8 中文的字节常可被 GBK 解码。不要凭"看起来正常"直接写；按项目默认编码处理，或 `--encoding` 显式指定。
- **NUL-heavy**：多为无 BOM UTF-16。写路径必须显式 `--encoding utf-16-le/be`（否则 fail-closed 退出码 1）。
- **Big5/Shift_JIS/EUC-KR 等**：其双字节内容几乎必被 GB18030 接受 → detect 报 gbk 或 gb18030（不会报这些编码）；必须 `--encoding` / `--from` 显式指定才能正确搜索/替换。半角片假名等单字节 ≥0x80 内容会落 unknown + 候选提示。
- **纯 CJK 无 BOM UTF-16 与 GBK**：无法可靠区分（无 NUL 信号），按 GBK 处理并保留风险说明。

## 4. decodeHints 说明

decodeHints 是**建议性**候选提示，不是判定结果：

- 双合法：`valid in both utf-8 and gbk; follow project policy`
- NUL-heavy：`contains many NUL bytes; maybe BOM-less UTF-16/UTF-32`
- BOM 正文损坏：`带 BOM 但正文无法严格解码，可能已损坏`
- UTF-32 BOM：`UTF-32 BOM detected but unsupported; convert with an external tool`
- unknown 候选：按 big5 → shift_jis → euc_jp → euc_kr → cp1252 顺序逐一严格试解，命中则 `could be <编码>`

## 5. 平台严格度差异（已文档化）

- .NET 严格 936 比 Python gbk / glibc iconv 宽松（接受孤立 0x80 → €，且部分 UTF-8 中文样本在 .NET 下"双合法"）。
- 因此同一文件：PS 探针可能报 `utf-8+gbk-dual` 或 `gbk`，bash 探针 / enc detect 报 `utf-8` 或 `gb18030`——三者都是诚实结果。
- BOM 正文损坏：enc detect 报 `utf-8/medium + 损坏提示`；PS/bash 探针报 `unknown`（语义等价：都需走 `enc`，无默认直写）。
- 原生探针是测试/开发用独立探测（零依赖），置信度细化与归一以 enc detect 为权威；不再作为发布物内门禁。

## 6. 实现行为说明与已知边界

（实现按本记录执行）

1. Big5/Shift_JIS 纯双字节内容在确定性顺序下必然落 gbk 或 gb18030，无法构造 unknown；"不自动判"落实为 detect 永不输出 big5/shift_jis。
2. `shift-jis` 夹具需含单字节 ≥0x80（半角片假名）才能触发 unknown + 候选提示。
3. NUL-heavy → `ascii/medium` + NUL 提示（验证 11 以"medium + NUL 提示、写路径需显式 `--encoding`"为核心）。
4. BOM 正文损坏：detect medium + 损坏提示；探针 unknown；写路径 fail-closed（退出码 1）。
5. `corrupted-fffd`（abc + U+FFFD + def）为 UTF-8 与 GBK 双合法 → `utf-8/medium`；内容损坏由 fffdCount 与 verify 呈现。
6. NUL-heavy 写路径要求显式 `--encoding`（否则 fail-closed 退出码 1）——防止按错误编码（ascii）改写无 BOM UTF-16。
7. GB18030 4 字节映射：分段线性（见 encoding-matrix.md §6）。