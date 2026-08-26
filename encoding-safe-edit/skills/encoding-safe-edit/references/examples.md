# 场景用例（examples.md）

> 深度参考：可照抄的完整示例。实际行为以 SKILL.md 为准。

## 目录

- [1. 场景 A：修改 GBK 的 C/C++ 源文件（最常见事故）](#1-场景-a修改-gbk-的-cc-源文件最常见事故)
- [2. 场景 B：UTF-8 带 BOM 文件](#2-场景-butf-8-带-bom-文件)
- [3. 场景 C：把 GBK 转成 UTF-8](#3-场景-c把-gbk-转成-utf-8)
- [4. 场景 D：Big5 繁体文件（显式编码）](#4-场景-dbig5-繁体文件显式编码)
- [5. 场景 E：日文 Shift_JIS（显式编码）](#5-场景-e日文-shift_jis显式编码)
- [6. 场景 F：事后验证与备份恢复](#6-场景-f事后验证与备份恢复)
- [7. 场景 G：dry-run 与批量替换](#7-场景-gdry-run-与批量替换)
- [8. 场景 H：看似 UTF-8 的普通文件被中文 Windows 默认 ANSI 写坏](#8-场景-h看似-utf-8-的普通文件被中文-windows-默认-ansi-写坏)

## 1. 场景 A：修改 GBK 的 C/C++ 源文件（最常见事故）

```bash
ENC="<SKILL_DIR>/scripts/enc"

# 1) 先确认编码（GBK 文件应报 gbk/high）
$ENC detect src/monitthread.cpp

# 2) 把要改的"search/replace"写成 UTF-8 无 BOM 的 JSON 文件
#    ops.json: [{"search":"旧注释","replace":"新注释","label":"note1"}]

# 3) 先 dry-run 预览
$ENC replace src/monitthread.cpp --from-file ops.json --dry-run --verbose

# 4) 确认无误后真正替换（自动生成 src/monitthread.cpp.orig 备份）
#    默认事务化：写后自动验证，damaged:false 则自动删除 .orig，无需手动 cleanup
$ENC replace src/monitthread.cpp --from-file ops.json

# 5)（可选）事后验证；默认写后已自动验证，如需人工复核可执行
$ENC verify src/monitthread.cpp
```

要点：不要用 Agent 原生 Edit/Write 直接改 GBK 文件；不要用命令行传中文 ops。

## 2. 场景 B：UTF-8 带 BOM 文件

```powershell
$enc = Join-Path "<SKILL_DIR>" "scripts\enc.ps1"

& $enc detect header.h
# encoding: utf-8, bom: utf-8

# 带 BOM 文件禁止原生编辑；用 enc replace（自动保留 BOM）
& $enc replace header.h --from-file ops.json
& $enc verify header.h
```

## 3. 场景 C：把 GBK 转成 UTF-8

```bash
ENC="<SKILL_DIR>/scripts/enc"
$ENC convert legacy.ini --to utf-8 --bom remove --line-ending keep
$ENC verify legacy.ini
```

需要带 BOM 则 `--bom add`；目标编码无法表示的字符会 fail-closed（退出码 1、不写盘）。

## 4. 场景 D：Big5 繁体文件（显式编码）

```bash
ENC="<SKILL_DIR>/scripts/enc"
$ENC detect big5file.txt
# 注意：可能报 gb18030/high（Big5 双字节可被 GB18030 接受）；不要按此直接搜简体
$ENC read big5file.txt --encoding big5
# ops.json: [{"search":"中文","replace":"測試"}]
$ENC replace big5file.txt --from-file ops.json --encoding big5
$ENC convert big5file.txt --to utf-8 --from big5
```

## 5. 场景 E：日文 Shift_JIS（显式编码）

```bash
ENC="<SKILL_DIR>/scripts/enc"
$ENC read sjis.txt --encoding shift_jis
# ops.json: [{"search":"日本語","replace":"テスト"}]
$ENC replace sjis.txt --from-file ops.json --encoding shift_jis
$ENC convert sjis.txt --to utf-8 --from shift_jis
```

## 6. 场景 F：事后验证与备份恢复

```bash
ENC="<SKILL_DIR>/scripts/enc"
$ENC verify file.txt
# damaged: false -> 安全；默认写后已自动清理 .orig，无需 cleanup
# 仅当使用过 --keep-backup、仍留有 .orig 时，才需要：
#   $ENC cleanup file.txt
# damaged: true  -> 从备份恢复并重新编辑
cp file.txt.orig file.txt
```

verify 会扫描 U+FFFD、`?` 密度、经典乱码模式（`锟斤拷` 等）。

注意：`.orig` 只保留**最近一次写前**的状态（覆盖式单步快照）；若之后又对该文件执行过写操作，恢复的是上一写前版本。默认写后验证通过会自动删除 `.orig`；仅当使用 `--keep-backup` 或 `damaged:true` 时 `verify` 才会提示你清理/恢复。

## 7. 场景 G：dry-run 与批量替换

```bash
ENC="<SKILL_DIR>/scripts/enc"
# 多个 op 批量替换；任一个未匹配都会 fail-closed（退出码 2，不写盘）
cat > ops.json <<'EOF'
[
  {"search":"旧A","replace":"新A","label":"a"},
  {"search":"旧B","replace":"新B","label":"b"},
  {"search":"旧C","replace":"新C","label":"c"}
]
EOF
$ENC replace file.txt --from-file ops.json --dry-run
# 确认全部命中后再执行
$ENC replace file.txt --from-file ops.json
```

## 8. 场景 H：看似 UTF-8 的普通文件被中文 Windows 默认 ANSI 写坏

在中文 Windows（代码页 936）上，PowerShell `Get-Content` / `Set-Content` 默认按 ANSI(GBK) 处理文本：
即使文件本身是 UTF-8 无 BOM，也可能被整体转成 GBK、出现落单字节变 `?`，或带 BOM 文件"读对写错"。

```powershell
$enc = Join-Path "<SKILL_DIR>" "scripts\enc.ps1"

# 1) detect 确认编码（utf-8/high、无 BOM）
& $enc detect notes.md

# 2) 不要用 Set-Content 默认行为；用 enc replace 走字节路径
#    ops.json: [{"search":"旧文本","replace":"新文本","label":"note"}]
& $enc replace notes.md --from-file ops.json --dry-run --verbose
& $enc replace notes.md --from-file ops.json

# 3) 事后验证
& $enc verify notes.md
```

要点：即便 detect 报 utf-8/high，写入仍一律走 `enc replace`（无豁免）；任何工具的默认行为都可能破坏编码；
在中文 Windows 上仍优先走 `enc`，或显式 UTF-8 读写并 `verify`。
