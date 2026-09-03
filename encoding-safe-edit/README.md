# Encoding Safe Edit Plugin

文本编码安全编辑插件。在读取、修改或写入文本文件前自动探测编码，并以原编码安全替换，覆盖 GBK/GB18030/UTF-8/UTF-16，提供转码与事后验证，防止中文 Windows 默认 ANSI(GBK) 写回破坏 UTF-8。

## 系统要求

- 运行时：Python 3.8+ 或 Node.js 18+（`enc` 启动器自动探测，**uv 优先（Python 系）**、Node 兜底；`--runtime auto|uv|python3|python|py -3|node` 可显式指定，默认 `auto`）
- 平台：Windows / Linux / macOS（Windows 下 PowerShell 5.1+）

## 快速使用

```powershell
$enc = Join-Path "<SKILL_DIR>" "scripts\enc.ps1"

# 1) 检测编码
& $enc detect file.txt

# 1.5) 定位文本 / 按行读取（只读，不修改文件）
& $enc find file.txt "目标串" --ignore-case --max-count 5
& $enc read file.txt --from-line 10 --to-line 20

# 2) 安全替换（ops 写为 UTF-8 无 BOM 的 JSON，中文内容必须走 --from-file）
& $enc replace file.txt --from-file ops.json --dry-run
& $enc replace file.txt --from-file ops.json

# 写后自动验证，damaged:false 则自动清理 .orig，无需手动 cleanup
# 需要保留快照用于人工确认时加 --keep-backup：
#   & $enc replace file.txt --from-file ops.json --keep-backup

# 2.5) 在匹配 anchor（整行）的行前/后插入一整行（自动换行，避免 replace 漏 \n 行合并）
& $enc insert file.txt --from-file ops.json

# 3)（可选）事后复核
& $enc verify file.txt

# 4)（维护）清理历史/孤儿快照
& $enc gc <dir>

# 完整命令面见：& $enc --help   （--no-backup 已移除，不会出现在帮助中）
```

## 子命令速查

| 子命令 | 说明 |
|--------|------|
| `detect` | 输出编码、置信度、BOM、行尾、是否可安全直改 |
| `find` | 按字面量在解码文本中定位子串，返回行/列与上下文；支持 `--ignore-case` / `--max-count` / `--pattern-file`（只读） |
| `read` | 按原编码解码，以 UTF-8 输出，不修改原文件；支持 `--line N` / `--from-line N --to-line M` 行范围读取 |
| `replace` | 按原编码搜索替换，保留原编码/BOM/行尾；默认事务化：写后验证通过自动清理 `.orig`，`--keep-backup` 保留快照 |
| `insert` | 在匹配 `anchor`（整行）的那一行前/后插入一整行/多行；自动处理换行，避免 `replace` 漏 `\n` 导致行合并 |
| `convert` | 转码，支持 BOM 与行尾策略；默认事务化：写后验证通过自动清理 `.orig` |
| `verify` | 扫描 U+FFFD 与转码痕迹，检测损坏；`suggestedAction` 按 `.orig` 是否存在条件化 |
| `cleanup` | 维护：删除 `<file>.orig` 单步撤销快照 |
| `gc` | 维护：清理孤儿 `.orig`（target 缺失），`--all` 递归全删 |
| `help` | `enc --help`/`enc help <sub>`；`--no-backup` 已移除 |
| `selfcheck` | 检查可用运行时 |

## 来源与许可证

参考了 `cppfile-encoding` skill 的"字节级替换 + 保留原编码"思路，但独立实现，未复制其代码/文案；`enc.gbkdata.js` 由 Python codec 数据实测生成。

MIT License
