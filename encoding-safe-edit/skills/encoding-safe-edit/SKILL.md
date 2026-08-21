---
name: encoding-safe-edit
description: 确保对任意文本文件的读取、编辑、写入不破坏原始编码（GBK/GB18030/UTF-8/UTF-16）。当 Agent 需要读取、修改或写入文本文件时使用：编码可能非 UTF-8（如含中文注释的 C/C++ 源文件、中文 Windows 上的 .ini/.conf/.properties、历史遗留文档），或看似 UTF-8 但中文 Windows 默认 ANSI(GBK) 写入会破坏它，或用户提到编码/乱码/GBK/GB2312/CP936/文件编码/损坏替换符（U+FFFD，�）。触发词：乱码、GBK、GB2312、CP936、编码损坏、中文注释、文件编码。自动探测编码并以原编码安全替换，提供转码与事后验证。
---

# 文本编码安全编辑（encoding-safe-edit）

在读取、修改、写入任何文本文件之前，先判断文件编码；detect 未判定可安全直改（非 UTF-8 / 带 BOM / 双合法 / 未知）的文件一律走本 skill 的 `enc` 工具，禁止用 Agent 原生写工具直接改。目标：对 GBK/GB18030/UTF-8/UTF-16 等编码的文件，保证"检测→解码→编辑→同编码写回"全程不破坏原始字节。

## 何时使用（触发）

- 读取、修改或写入任何文本文件之前（编码可能非 UTF-8，或看似 UTF-8 但中文 Windows 默认 ANSI(GBK) 写入会破坏它）。
- 修改含中文注释/字符串的 C/C++ 源文件或其他可能非 UTF-8 的文件。
- 用户提到 乱码 / GBK / GB2312 / CP936 / 文件编码 / 编码损坏 / U+FFFD（�）。
- 在中文 Windows 环境用 PowerShell `Get-Content` / `Set-Content` / `Out-File` 等默认编码行为读取或修改文本文件。
- 在中文 Windows 环境读取或修改 .ini / .conf / .properties / 历史遗留文档。
- 需要把文件转成另一种编码（含 BOM / 行尾策略）。

## 关键约束（先读，尾部会再次重申）

- **任何写操作前先 `enc detect`**；detect 未判定 `safeToEditDirectly: true`（非 UTF-8 / 带 BOM / 双合法 / 未知）时，写一律用 `enc replace` / `enc convert`。
- **fail-closed**：任一操作失败（编码未知、解码失败、编码失败、op 未匹配且未加 `--force`）→ **不写盘**，按退出码返回。
- **默认自动备份（单步撤销快照）**：每次写回前生成 `<file>.orig`（可用 `--no-backup` 关闭；不依赖 git）。**覆盖式**：只保留最近一次写前状态，不是历史备份；确认无误后 `enc cleanup <file>` 删除快照，不残留。
- **中文内容必须走文件**：含中文的 ops 用 `--from-file <ops.json>`，不要把中文直接塞进命令行参数（Windows 命令行会破坏中文）。
- **写回保留原编码、原 BOM、原行尾**（mixed 行尾逐行保留）；带 BOM 文件禁止原生编辑。
- 检测有歧义（ASCII / 双合法 / NUL-heavy / unknown）时**不许静默猜测**：看 detect 输出的 `decodeHints` 与项目约束（项目规则中声明的编码约定）决定，必要时用 `--encoding` 显式指定。
- 项目默认编码以项目约束（项目规则中声明的编码约定）为准；本 skill 不假定任何"默认编码"。

## 定位脚本

`enc` 工具位于本 skill 安装目录：`<SKILL_DIR>/scripts/enc`（Git Bash / Linux / macOS）或 `<SKILL_DIR>/scripts/enc.ps1`（Windows PowerShell）。先用变量定位：

```bash
# bash
ENC="<SKILL_DIR>/scripts/enc"
```

```powershell
# PowerShell
$enc = Join-Path "<SKILL_DIR>" "scripts\enc.ps1"
```

`enc` / `enc.ps1` 是零依赖启动器：自动探测可用运行时（Python 优先，Node 兜底），转发到 `enc.py` / `enc.js`。无可用运行时则拒绝执行并给出提示（fail-closed）。

`--runtime` 接受 `auto`（默认）、`python3`、`python`、`py -3`、`uv`、`node`。`auto` 按 `python3 → python → py -3 → uv (uv run --no-project python) → node` 依次探测，第一个可用即转发；显式值只探测并只使用该命令，不可用时 fail-closed（退出码 1）。含空格的值（`py -3`）作为单个参数传入，PowerShell 中写成 `--runtime 'py -3'`。项目策略固定运行时（如工作区强制 uv）时用显式值：

```powershell
enc.ps1 --runtime uv detect <file>
```

固定由 uv 提供 Python 的环境可绕过启动器直接调用：`uv run --no-project <SKILL_DIR>/scripts/enc.py <subcommand> ...`；固定 Node 时直接调用 `node <SKILL_DIR>/scripts/enc.js <subcommand> ...`。直连跳过运行时探测与兜底，仅应在项目约束已固定运行时使用。

## 标准工作流（修改任意文本文件）

Read `references/detection-notes.md` 了解置信度与歧义细节（只需在检测结果可疑时）；Read `references/examples.md` 获取可照抄的完整示例（第一次使用本 skill 时）。下方各步骤中需要深度细节处会再次提示 Read。

1. **detect**：`enc detect <file>`，读取 JSON 的 `encoding` / `confidence` / `bom` / `lineEnding` / `safeToEditDirectly` / `suggestedAction`。
2. **决定编辑方式**：
   - `safeToEditDirectly: true`（utf-8/high 无 BOM 或 ascii/low）且项目允许 → 可用原生编辑；否则进入 3。
   - `encoding: unknown` → **禁止直接写**，按 `decodeHints` 或项目约束用 `--encoding` 显式指定后重试。
   - `confidence: medium`（双合法 / NUL-heavy）→ 看提示与项目约束；NUL-heavy 必须显式 `--encoding utf-16-le/be` 才能写。
3. **read（需要看内容时）**：`enc read <file> [--out <临时文件>]`。输出为 UTF-8；用 `--out` 写临时文件再读，规避控制台乱码。中文环境必用 `--out` 或直接读 stdout 字节。
4. **replace（修改）**：把 ops 写成 UTF-8 无 BOM 的 JSON 文件，然后：
   ```bash
   enc replace <file> --from-file <ops.json> [--dry-run] [--verbose]
   ```
   ops 格式：`[{"search":"...","replace":"...","label":"..."}]`；search/replace 按文件当前编码解释（Agent 以 UTF-8 书写，工具负责编码）。
5. **convert（转码）**：`enc convert <file> --to <目标编码> [--from <源编码>] [--bom add|remove|keep] [--line-ending keep|crlf|lf]`。源编码不在自动判定集（如 big5）时必须 `--from` 显式指定。Read `references/encoding-matrix.md` 了解各编码与平台默认行为差异（BOM/行尾策略拿不准时）。
6. **verify（事后验证）**：`enc verify <file>`。确认 `damaged: false`（无 U+FFFD、无转码痕迹）；若 `damaged: true`，从 `<file>.orig` 恢复并重新编辑。
7. **cleanup（收尾）**：`enc cleanup <file>`。verify 确认 `damaged: false` 后删除 `.orig` 快照，避免残留；若还需继续编辑可延后到全部改完再清理。

## 子命令速查

### detect
```bash
enc detect <file>
```
输出 JSON：`encoding`（utf-8 / gbk / gb18030 / utf-16le / utf-16be / ascii / unknown）、`confidence`（high / medium / low）、`bom`、`lineEnding`、`fffdCount`、`asciiOnly`、`decodeHints`、`safeToEditDirectly`、`suggestedAction`。**detect 对 unknown 文件仍返回退出码 0**（正常完成，是否可写由调用方决定）。

### read
```bash
enc read <file> [--out <utf8-path>] [--encoding <enc>]
```
按检测编码解码，内容以 UTF-8 输出到 stdout 或 `--out` 文件；**不修改原文件**。`--encoding` 用于默认候选集之外的显式编码（big5 / shift_jis / euc_jp / euc_kr / cp1252 等）。

### replace
```bash
enc replace <file> <ops-json> [--encoding <enc>] [--dry-run] [--no-backup] [--verbose] [--force]
enc replace <file> --from-file <ops-file> [--encoding <enc>] [--dry-run] [--no-backup] [--verbose] [--force]
```
- search/replace 与文件**当前编码**一致；写回保留原编码 / BOM / 行尾。
- 任一 op 未匹配 → 默认不写盘、退出码 2；`--force` 才写（且会在 warnings 里暴露未匹配项）。
- 先 `--dry-run` 预览，再真正写盘。

### convert
```bash
enc convert <file> --to <enc> [--from <enc>] [--bom add|remove|keep] [--line-ending keep|crlf|lf] [--dry-run] [--no-backup]
```
- `--to` / `--from` 支持 Python codec 注册表内的编码名（utf-8 / utf-16-le / utf-16-be / gbk / gb18030 / big5 / shift_jis / euc_jp / euc_kr / cp1252 等）。
- `--bom keep` = 保持"是否带 BOM"的状态（带则写目标编码的 BOM，不带则不写）；GBK 等无 BOM 概念的编码不产生 BOM 字节。
- 目标编码无法表示某字符、或源编码无法确定/无法严格解码 → 不写盘、退出码 1。

### 编码名与别名（--encoding / --to / --from 接受）

- UTF-8：`utf-8` / `utf8` / `utf_8` / `u8` / `utf` / `cp65001`
- UTF-16LE：`utf-16-le` / `utf16le` / `utf_16_le`
- UTF-16BE：`utf-16-be` / `utf16be` / `utf_16_be`
- GBK：`gbk` / `cp936` / `ms936` / `936` / `gb2312`
- GB18030：`gb18030` / `gb18030-2000`
- 遗留编码：`big5` / `shift_jis`（`shift-jis`）/ `euc_jp`（`euc-jp`）/ `euc_kr`（`euc-kr`）/ `cp1252`
- **拒绝（fail-closed）**：`utf-16` / `utf16` / `utf_16`（无 BOM 端序不定，歧义）；`utf-32` / `utf32` / `utf_32`（不支持，先用外部工具转码）。

### verify
```bash
enc verify <file> [--encoding <enc>]
```
扫描 U+FFFD、`?` 密度、经典乱码模式（`锟斤拷` 等），输出 `damaged` 与建议动作。

### cleanup
```bash
enc cleanup <file>
```
删除写操作生成的 `<file>.orig` 单步撤销快照。`.orig` 存在且为常规文件 → 删除并输出 `removed`；不存在 → 幂等返回 `removed: null`（退出码 0）；`<file>` 非常规文件或 `.orig` 是目录 → 不删除、退出码 1。

### selfcheck
```bash
enc selfcheck
```
输出可用运行时清单（区分"存在但不可执行"与"可用"），并给出候选顺序。

## 退出码

| 退出码 | 含义 | 处理 |
|-------|------|------|
| 0 | 成功（detect/read/convert/verify 正常完成；replace 全部匹配并应用；dry-run 校验通过；cleanup 已删除或无可删） | 继续 |
| 1 | 错误（参数错误、文件不存在、IO 失败、编码未知/解码失败/编码失败、cleanup 目标非常规文件或 `.orig` 为目录，**未写盘/未删除**） | 读 stderr/错误 JSON，修正后重试 |
| 2 | replace 存在未匹配项（未加 `--force` 时**未写盘**；加了 `--force` 时已写盘） | 检查 search 是否与文件实际内容/编码一致，必要时 `--encoding` |

所有 stdout 为 UTF-8；错误对象 JSON：`{"ok":false,"error":"...","exitCode":1,"hint":"..."}`。日志/调试信息走 stderr。

## 安全护栏

- **不接 shell**：ops 内容只做字节/文本匹配，绝不拼进命令执行；search 含 `; rm -rf`、`$(...)` 等只按字面处理。
- **原子写**：先写临时文件再替换；任何失败不产生半成品。
- **日志脱敏**：verbose 输出不包含文件中的凭据明文（如 `password=xxx`）。
- **路径校验**：目标必须是常规文件；ops 来自 `--from-file` 时同样校验。

## Gotchas / 注意事项

- **双向风险**：不仅 GBK 会被 UTF-8 写坏，中文 Windows 的 PowerShell 默认 ANSI(GBK) 也会破坏 UTF-8（含带 BOM 文件"读对写错"）。本 skill 的脚本统一走字节 API，规避该问题；**不要用 PowerShell `Get-Content`/`Set-Content`/`Out-File` 默认行为改文件**。
- **"双合法"很常见**：一段 UTF-8 中文的字节经常也能被 GBK 解码（`confidence: medium`）。此时不要凭"看起来对"直接写；按项目约束或 `decodeHints` 决定。
- **检测是启发式**：ASCII/空文件/双合法都有歧义；detect 只报告事实与置信度，**不静默猜测**。
- **Big5/Shift_JIS 等遗留编码不在自动判定集**：detect 不会输出 big5/shift_jis（它们的字节常被 GBK/GB18030 接受）；对这类文件必须 `--encoding big5` / `--from big5` 显式指定。
- **NUL-heavy（无 BOM UTF-16）**：detect 报 `ascii/medium` + NUL 提示，`safeToEditDirectly: false`；写路径必须显式 `--encoding utf-16-le/be`。
- **带 BOM 文件**：`safeToEditDirectly: false`，一律走 `enc replace`（自动保留 BOM）。
- **Windows 命令行/管道会破坏中文**：中文 ops 用 `--from-file`；不要依赖把中文作为命令行参数传入。
- **UTF-32 不支持**：detect 归 unknown；用显式 `--encoding` 也没有 UTF-32 解码路径，请先转码再处理。
- **`.orig` 是单步撤销快照**：连续多次写会覆盖旧快照；确认无误后 `enc cleanup <file>` 删除，避免残留。目标在 git 仓库时，删除前建议把 `*.orig` 加入 `.gitignore` 防误提交（快照只作写后即时的撤销手段，不是历史备份）。
- 性能：常规文本文件（<10MB）秒级；>50MB 不在目标范围。

## 关键约束（尾部重申，与头部一致）

- 写前 `enc detect`；`safeToEditDirectly: true` 之外一律走 `enc replace` / `enc convert`，禁止原生写工具直接改。
- fail-closed：任何失败不写盘（除非显式 `--force` 且已确认未匹配项）。
- 默认自动备份 `<file>.orig`（单步撤销快照，覆盖式）；确认后 `enc cleanup <file>` 清理。
- 写回保留原编码 / 原 BOM / 原行尾；带 BOM 文件禁止原生编辑。
- 中文 ops 走 `--from-file`；不静默猜测编码；项目默认编码以项目约束为准。

## 参考（深度，按需阅读）

- `references/encoding-matrix.md`：编码 / 平台 / 工具矩阵（需要了解各编码与平台默认行为的差异时读）。
- `references/detection-notes.md`：检测置信度与歧义细节（检测结果可疑时读）。
- `references/examples.md`：场景用例（需要一个可照抄的完整示例时读）。
