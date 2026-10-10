---
name: encoding-safe-edit
description: 文本文件安全读写（encoding-safe-edit）：按文件原始编码读/写/改，防止 GBK/GB18030/UTF-8/UTF-16 互转损坏。读取或修改任何文本文件、处理乱码或编码问题时使用。触发词：乱码、GBK、GB2312、CP936、编码损坏、中文注释、文件编码、U+FFFD。
---

# 文本编码安全编辑（encoding-safe-edit）

本 skill 提供文本文件的编码安全读写通道：自动检测原编码（GBK / GB18030 / UTF-8 / UTF-16 等）并按原编码回写，内置 fail-closed、写前备份、写后验证。所有读写都经 `enc` 完成；强制使用要求见项目 / 全局约束层。

## 默认路径（按此执行，不要自行加步骤）

读内容（按需选一种）：

| 场景 | 命令 |
|---|---|
| 一般文件 / 要看全文 | `enc read <file>` |
| 大文件、位置未知 | `enc find <file> <pattern>` 取行号 → `enc read <file> --from-line N --to-line M`（同一条链路） |

改内容（既有文件）：

```
1) enc read <file>                       # 需要精确原文时；同文件同批次只读一次；检测已内置
2) 写 ops.json（%TEMP%，UTF-8；同批修改合并为多个 op；含中文必须走文件）
3) enc replace <file> --from-file ops.json
   # 内置：检测 → 解码 → 匹配 → 备份(.orig) → 原子写 → verify → 自动清理
```

新建文件：

```
enc create <file> --line-ending lf --bom none
enc insert <file> --from-file ins.json         # 锚点 = 哨兵 __ENC_PLACEHOLDER__
enc replace <file> --from-file fin.json        # 删除哨兵行
```

注脚：同文件同批次——一次 read、一份 ops、一次 replace；环境定位一次即可（见「定位脚本」）。

## 例外清单（仅命中时执行）

- `enc detect` 单独运行：编码歧义（ASCII 文件将引入非 ASCII、双合法）、NUL-heavy、unknown、`fffdCount>0`、与项目编码约定冲突（漂移疑点）、或项目门禁要求时；纯读不跑（read 已内置探测）。
- `enc read --out <tmp>`：内容用于机器消费、超大输出 / 需要留证、环境编码未知时；与读回合并进同一次 exec（见下例）；人眼直读用 stdout。
- `--dry-run`：多 op、短 / 泛 search 串、大文件、首次操作该文件、不可逆改动时使用；未命中会先 exit 2（预览需 `--force`）；免风险 ≠ 免成本。
- `enc verify`：`--keep-backup` 收尾、需要出证据、审计排查时单独运行；默认由写路径内置验证覆盖。

合并调用示例（确定性衔接一次 exec 完成）：

```
& $enc read '<file>' --out $o; if ($LASTEXITCODE -eq 0) { Get-Content -LiteralPath $o -Raw -Encoding UTF8 }
```

## 安全底线（不可让渡）

- fail-closed：任一操作失败（编码未知、解码 / 编码失败、op 未匹配且未加 `--force`）→ 不写盘，按退出码返回。
- 写路径恒先备份：`<file>.orig` 单步撤销快照，写后内部 verify 通过即自动清理；`--keep-backup` 保留；`--no-backup` 已移除。
- 写回保留原编码 / 原 BOM / 原行尾（mixed 行尾仅限制多行 op / insert）。
- 中文内容走 `--from-file`（ops / pattern 载体），不塞命令行参数。
- `.orig` 是单步快照，不是历史备份；历史回滚靠版本控制或 change-backup。

## 子命令速查

- 读：`detect`（编码决策）/ `find`（定位）/ `read`（解码输出）/ `verify`（只读体检）
- 写：`replace`（字面替换）/ `insert`（整行插入，加行优先用它）/ `create`（哨兵新文件）/ `convert`（转码）
- 维护：`cleanup`（删单文件 `.orig`）/ `gc`（清孤儿 `.orig`）
- 参数与语法以 `enc <sub> -h` 为准（argparse 原生；无 `help` 子命令）。

## 定位脚本

```powershell
$enc = Join-Path "<SKILL_DIR>" "scripts\enc.ps1"   # PowerShell（Windows）
```
```bash
ENC="<SKILL_DIR>/scripts/enc"                      # Git Bash / Linux / macOS
```

定位一次即可；运行时诊断用 `enc selfcheck`（候选 uv → python3 → python；异常时可用 `--runtime` 强制指定）。

## 退出码

0 = 成功；1 = 错误（参数错误 / IO / fail-closed）；2 = 业务性预期分支（未命中）。

## Gotchas（高信号陷阱）

- 「双合法」很常见：一段 UTF-8 中文的字节常也能按 GBK 解码（medium）——写回须显式 `--encoding`，不凭肉眼判断。
- NUL-heavy 可能是无 BOM 的 UTF-16/UTF-32：detect 报 ascii/medium，写路径必须显式 `--encoding utf-16-le/be`。
- Big5 / Shift_JIS 等不在自动判定集：须 `--encoding big5` / `--from big5` 显式指定。
- `replace` 是字面匹配、不自动补换行：插入整行优先用 `insert`；改用 `replace` 时 replace 串须自带 `\n`。
- 英文错误 = 启动期问题：`enc.ps1` / `enc` 是纯 ASCII 英文选择器，只在启动阶段（解释器不可用等）报错；工具业务错误一律由 `enc.py` 输出中文。

## 反模式（不要做）

- 写后回读全文自检（写路径已内置 verify）；每次顺手 `--dry-run` / `enc verify`。
- 同一会话重复全量读同一文件；每步 `Test-Path` 校验。
- 把中文内容塞进命令行参数；把 ops / pattern 载体写进工程树。

## 参考（按需阅读）

- `references/detection-notes.md`：检测置信度与歧义细节（结果可疑时读取）。
- `references/encoding-matrix.md`：编码 / 平台 / 工具矩阵（BOM / 行尾策略拿不准时读取）。
- `references/examples.md`：完整可照抄示例（首次使用或需要样例时读取）。
