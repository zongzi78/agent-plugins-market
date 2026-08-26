# 编码 / 平台 / 工具矩阵（encoding-matrix.md）

> 深度参考，不承载关键行为（关键行为见 SKILL.md）。内容基于 2026-08-19 本机实测（Windows PowerShell 5.1.26100，cp936）与 Python/iconv/.NET 行为核对。

## 目录

- [1. 各编码速览](#1-各编码速览)
- [2. 平台默认行为（为什么必须显式走字节）](#2-平台默认行为为什么必须显式走字节)
- [3. 工具能力矩阵](#3-工具能力矩阵)
- [4. 严格解码器差异](#4-严格解码器差异)
- [5. BOM 与行尾](#5-bom-与行尾)
- [6. 本 skill 的支持边界](#6-本-skill-的支持边界)

## 1. 各编码速览

| 编码 | 别名/说明 | 单字节 | 双字节 | 4 字节 | 是否自动判定 |
|------|-----------|--------|--------|--------|--------------|
| ASCII | US-ASCII | 0x00-0x7F | — | — | 是（low 置信度） |
| UTF-8 | — | 0x00-0x7F | 2/3 字节序列 | 4 字节序列 | 是 |
| UTF-8 + BOM | EF BB BF 前缀 | 同上 | 同上 | 同上 | 是（bom=utf-8） |
| GBK | CP936（Windows 上的 GBK） | 0x00-0x7F | 0x81-0xFE × 0x40-0xFE（不含 0x7F） | — | 是 |
| GB18030 | GBK 的超集（国标） | 0x00-0x7F | 全覆盖 23940 对 | 有（线性映射，见 §6） | 是 |
| UTF-16LE / BE | 带 BOM 才自动判定 | — | 2 字节/码元 | — | 是（仅带 BOM） |
| UTF-32 | LE/BE | — | — | 4 字节 | 否（归 unknown） |
| Big5 | 繁体中文 | 0x00-0x7F | 0x81-0xFE × 0x40-0x7E/0xA1-0xFE | — | 否（显式 --encoding） |
| Shift_JIS | 日文 | 0x00-0x7F + 0xA1-0xDF（半角片假名） | 0x81-0x9F/0xE0-0xEF × 0x40-0x7E/0x80-0xFC | — | 否 |
| EUC-JP | 日文（JIS X 0208/0212） | 0x00-0x7F | 0xA1-0xFE × 0xA1-0xFE；0x8E+半角 | 0x8F + 2 字节（JIS X 0212） | 否 |
| EUC-KR | 韩文 | 0x00-0x7F | 0xA1-0xFE × 0xA1-0xFE | — | 否 |
| cp1252 | Windows 西欧 | 0x00-0xFF（0x81/8D/8F/90/9D 未定义） | — | — | 否 |

## 2. 平台默认行为（为什么必须显式走字节）

| 平台/工具 | 默认文本行为 | 风险 |
|-----------|--------------|------|
| PowerShell 5.1（中文系统） | `Get-Content`/`Set-Content` 默认 ANSI(=GBK)；`Out-File` 默认 UTF-16LE；`-Encoding UTF8` 写会加 BOM、LF→CRLF | 破坏 UTF-8（静默部分损坏 / 整体转 GBK / BOM 丢失） |
| PowerShell 7+ | 默认 utf8NoBOM | 对 GBK 文件按 UTF-8 读会大面积 U+FFFD（E8 实验） |
| cmd 重定向 | 字节透传 | 安全，但 cmd 无解码判定能力 |
| Node.js | 文本 API 默认 UTF-8 | 对 GBK 文件会损坏（同 UTF-8 假设） |
| Python | 文本 IO 需显式 encoding；默认依赖 locale | 显式指定即可 |
| Git Bash / Linux | iconv 需显式 -f/-t | 探针可靠 |

结论：**任何 Agent 原生写工具都默认按 UTF-8 落盘**——这正是事故根源。本 skill 的脚本一律用字节 API + 显式编码。

## 3. 工具能力矩阵

| 能力 | enc.py | enc.js | probes/detect.ps1 | probes/detect.sh |
|------|--------|--------|-------------------|------------------|
| detect（自动判定集） | ✓（权威） | ✓ | 门禁级 | 门禁级 |
| detect（unknown 候选提示） | ✓ | ✓ | ✗ | ✗ |
| read / replace / convert / verify | ✓ | ✓ | ✗ | ✗ |
| 显式遗留编码（big5 等） | ✓ | ✓ | ✗ | ✗ |
| 依赖 | Python 3.7+ 标准库 | Node + 自带 codec 数据（enc.gbkdata.js） | .NET（PS 内置） | iconv + coreutils |

- `enc`/`enc.ps1` 启动器探测顺序：`python3 → python → py -3 → uv(run python) → node`；Python 可用优先，Node 兜底。`--runtime` 支持 `auto/python3/python/py -3/uv/node`：`auto` 按上述顺序，显式值只探测并只使用该命令，不可用即 fail-closed。
- 固定运行时的工作区可直连：`uv run --no-project <SKILL_DIR>/scripts/enc.py <subcommand> ...` 或 `node <SKILL_DIR>/scripts/enc.js <subcommand> ...`；直连跳过运行时探测与兜底。
- 双实现一致性契约：enc.js 与 enc.py 严格语义一致（以 enc.py 为基准）；codec 数据由 Python 标准库 codec 实测生成并内置（`enc.gbkdata.js`）。

## 4. 严格解码器差异

| 解码器 | 对"中文测试"的 UTF-8 字节 | 对孤立 0x80 | 对 GB18030 4 字节 `81 30 81 30` |
|--------|---------------------------|-------------|--------------------------------|
| .NET `Encoding.GetEncoding(936)`（默认） | 可解（不抛异常） | 映射为 € | "解码"为 ??（宽松，不可用于严格判定） |
| .NET 严格 936（ExceptionFallback） | 可解（宽松于 Python） | 仍接受（→€） | 抛异常 |
| Python gbk / cp936 | **抛错（严格）** | 抛错 | 抛错 |
| glibc iconv GBK | 抛错/拒绝（严格） | — | 抛错 |
| Python gb18030 | — | — | 可解（U+0080） |

结论：同一 UTF-8 中文文件在 .NET 探针下可能判"双合法"，在 Python/iconv 侧判 utf-8/high——两者都诚实。**enc detect 以 Python 为权威**；原生探针仅作门禁（§SKILL.md）。

## 5. BOM 与行尾

- BOM：UTF-8=`EF BB BF`、UTF-16LE=`FF FE`、UTF-16BE=`FE FF`、UTF-32LE=`FF FE 00 00`、UTF-32BE=`00 00 FE FF`。
- 带 BOM 文件一律走 `enc replace`，自动保留 BOM。
- `--bom keep` 语义 = 保持"是否带 BOM"状态；目标编码无 BOM 概念（GBK 等）则不产生 BOM 字节。
- 行尾枚举：crlf / lf / cr / mixed / unknown；mixed 文件 replace 按行记录原行尾、逐行还原。

## 6. 本 skill 的支持边界

- 自动判定默认集：UTF-8（含 BOM）/ GBK / GB18030 / UTF-16（带 BOM）；其余经 `--encoding` / `--from` / `--to` 显式指定。
- UTF-32 不支持（detect 归 unknown；显式 `--encoding`/`--to`/`--from` 亦拒绝，需先用外部工具转码）。
- 无 BOM UTF-16：ASCII-heavy 经全局 NUL 密度预检降为 medium + 提示；纯 CJK 无 BOM UTF-16 与 GBK 无法可靠区分 → 按 GBK 处理并保留风险说明。
- GB18030 4 字节映射（enc.js 数据依据）：BMP 区 idx 0–39419（分段线性，206 段），增补区 idx 189000–1237575（cp = idx − 123464），idx 39420–188999 为非法空洞。U+10000 编码为 `90 30 81 30`（不是 `81 30 81 30`）。
- Big5 / Shift_JIS / EUC-JP / EUC-KR 双字节内容几乎都能被 GB18030 2 字节区接受（实测 23940/23940 全覆盖）→ detect 不会判出这些编码，必须显式指定。
