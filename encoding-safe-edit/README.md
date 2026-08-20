# Encoding Safe Edit Plugin

文本编码安全编辑插件。在读取、修改或写入文本文件前自动探测编码，并以原编码安全替换，覆盖 GBK/GB18030/UTF-8/UTF-16，提供转码与事后验证，防止中文 Windows 默认 ANSI(GBK) 写回破坏 UTF-8。

## 系统要求

- 运行时：Python 3.8+ 或 Node.js 18+（`enc` 启动器自动探测，Python 优先、Node 兜底；`--runtime auto|python3|python|py -3|uv|node` 可显式指定，默认 `auto`）
- 平台：Windows / Linux / macOS（Windows 下 PowerShell 5.1+）

## 快速使用

```powershell
$enc = Join-Path "<SKILL_DIR>" "scripts\enc.ps1"

# 1) 检测编码
& $enc detect file.txt

# 2) 安全替换（ops 写为 UTF-8 无 BOM 的 JSON，中文内容必须走 --from-file）
& $enc replace file.txt --from-file ops.json --dry-run
& $enc replace file.txt --from-file ops.json

# 3) 事后验证
& $enc verify file.txt
```

## 子命令速查

| 子命令 | 说明 |
|--------|------|
| `detect` | 输出编码、置信度、BOM、行尾、是否可安全直改 |
| `read` | 按原编码解码，以 UTF-8 输出，不修改原文件 |
| `replace` | 按原编码搜索替换，保留原编码/BOM/行尾，自动备份 `.orig` |
| `convert` | 转码，支持 BOM 与行尾策略 |
| `verify` | 扫描 U+FFFD 与转码痕迹，检测损坏 |
| `selfcheck` | 检查可用运行时 |

## 来源与许可证

参考了 `cppfile-encoding` skill 的"字节级替换 + 保留原编码"思路，但独立实现，未复制其代码/文案；`enc.gbkdata.js` 由 Python codec 数据实测生成。

MIT License
