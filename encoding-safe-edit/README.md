# Encoding Safe Edit Plugin

文本编码安全编辑插件。在读取、修改或写入文本文件前自动探测编码，并以原编码安全替换，覆盖 GBK/GB18030/UTF-8/UTF-16，提供转码与事后验证，防止中文 Windows 默认 ANSI(GBK) 写回破坏 UTF-8。

## 系统要求

- 运行时：Python 3.8+（启动器按 `uv` → `python3` → `python` 探测；`--runtime auto|uv|python3|python` 可显式指定，默认 `auto`）。**v1.1.0 起 Python-only：已移除 Node 实现与内置 codec 数据表。**
- 启动器：`enc.ps1` / `enc` 为纯 ASCII 英文选择器（无 BOM）；其英文报错只出现在“解释器不可用”等启动期，工具业务错误一律中文。
- 平台：Windows / Linux / macOS（Windows 下 PowerShell 5.1+）

## 快速使用

```powershell
$enc = Join-Path "<SKILL_DIR>" "scripts\enc.ps1"

# 1) 读一次，拿到要替换的精确原文（read 内置编码检测；同文件同批次只读一次）
& $enc read file.txt
# 大文件先定位、再按行读段（同一条链路；find 只读）
& $enc find file.txt "目标串" --ignore-case --max-count 5
& $enc read file.txt --from-line 10 --to-line 20

# 2) 新建文件：只写入哨兵（锚点），内容随后用 replace/insert 写入；不接受 --encoding
& $enc create new_file.txt --line-ending crlf
#   整文写入：一条跨行 replace（search = 哨兵 + 行尾，replace = 全文）；增量构建：insert --where before（锚 = 哨兵），收尾把「哨兵 + 行尾」替换为 ""
#   首次写入非 ASCII 内容时必须显式 --encoding（纯 ASCII 文件 detect 只能给 ascii/low）

# 3) 一次 replace 落盘：内置 检测 → 解码 → 匹配 → 备份(.orig) → 原子写 → verify → 自动清理
#    ops 写为 UTF-8 无 BOM 的 JSON；中文内容必须走 --from-file（载体 UTF-8，可带 BOM）
& $enc replace file.txt --from-file ops.json

# 加行：用 insert（自动换行，避免 replace 漏 \n 造成行合并）
& $enc insert file.txt --from-file ops.json

# 例外（仅命中触发条件时才加）：
#   & $enc detect file.txt                                   # 编码歧义 / NUL-heavy / unknown / 已有乱码
#   & $enc replace file.txt --from-file ops.json --dry-run    # 多 op / 首次改该文件 / 大文件 / 不可逆
#   & $enc verify file.txt                                    # 需要出证据 / 审计排查
#   & $enc gc <dir>                                           # 维护：清理孤儿 .orig

# 语法与参数以 & $enc --help / & $enc <sub> -h 为准（无 help 子命令；--no-backup 已移除）
```

## 子命令速查

| 子命令 | 说明 |
|--------|------|
| `detect` | 输出编码、置信度、BOM、行尾与 `decodeHints` / `suggestedAction`（不提供“可直改”豁免；写入一律走 enc） |
| `find` | 定位子串（默认字面匹配，`--regex` 启用正则、`^`/`$` 按行锚定），返回行/列与上下文；支持 `--ignore-case` / `--max-count` / `--pattern-file`（只读） |
| `read` | 按原编码解码，以 UTF-8 输出，不修改原文件；支持 `--line N` / `--from-line N --to-line M` 行范围读取 |
| `create` | 新建文件：只写入一行 ASCII 哨兵 `__ENC_PLACEHOLDER__`（作为 replace/insert 的锚点），不接受内容；目标必须不存在、父目录必须存在；支持 `--line-ending` / `--bom` / `--dry-run` |
| `replace` | 按原编码搜索替换，保留原编码/BOM/行尾；默认事务化：写后验证通过自动清理 `.orig`，`--keep-backup` 保留快照 |
| `insert` | 在匹配 `anchor`（整行）的那一行前/后插入一整行/多行；自动处理换行，避免 `replace` 漏 `\n` 导致行合并 |
| `convert` | 转码，支持 BOM 与行尾策略；默认事务化：写后验证通过自动清理 `.orig` |
| `verify` | 扫描 U+FFFD 与转码痕迹，检测损坏；`suggestedAction` 按 `.orig` 是否存在条件化 |
| `cleanup` | 维护：删除 `<file>.orig` 单步撤销快照 |
| `gc` | 维护：清理孤儿 `.orig`（target 缺失），`--all` 递归全删 |
| `-h` / `--help` | 顶层与各子命令帮助（argparse 原生，逐个参数都有说明）；**无 `help` 子命令**；`--no-backup` 已移除 |
| `selfcheck` | 启动器诊断：列出候选运行时（uv / python3 / python）与 selected（schema B′） |

## 来源与许可证

参考了 `cppfile-encoding` skill 的"字节级替换 + 保留原编码"思路，但独立实现，未复制其代码/文案；v1.1.0 起 Python-only（`enc.py` 仅用标准库），已移除 `enc.js` 与内置 codec 数据表。

MIT License
