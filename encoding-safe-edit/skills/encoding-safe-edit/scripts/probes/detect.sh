#!/usr/bin/env bash
# detect.sh - encoding-safe-edit 零依赖门禁探针（bash/sh：iconv + coreutils）
# 输出单个类别令牌：utf-8-bom / utf-16le / utf-16be / nul-heavy / ascii / utf-8+gbk-dual / utf-8 / gbk / gb18030 / unknown
# 命中即 exit（早停）；ASCII 判定用 tr 删字节法。
f="$1"
[ -f "$f" ] || { echo unknown; exit; }
# ① BOM（含 UTF-32 排除与正文严格校验）
head=$(head -c 4 "$f" | od -An -tx1 | tr -d ' \n')
case "$head" in
  fffe0000|0000feff) echo unknown; exit ;;
  efbbbf*)  if tail -c +4 "$f" | iconv -f UTF-8 -t UTF-8 >/dev/null 2>&1; then echo utf-8-bom; else echo unknown; fi; exit ;;
  fffe*)    if tail -c +3 "$f" | iconv -f UTF-16LE -t UTF-16LE >/dev/null 2>&1; then echo utf-16le; else echo unknown; fi; exit ;;
  feff*)    if tail -c +3 "$f" | iconv -f UTF-16BE -t UTF-16BE >/dev/null 2>&1; then echo utf-16be; else echo unknown; fi; exit ;;
esac
# ② NUL 密度预检（>1% 则 nul-heavy，enc detect 归一为 medium + decodeHints）
nulcount=$(LC_ALL=C tr -d '\001-\377' < "$f" | wc -c)
size=$(wc -c < "$f")
if [ "$size" -gt 0 ] && awk -v n="$nulcount" -v s="$size" 'BEGIN{exit !(n/s>0.01)}'; then echo nul-heavy; exit; fi
# ③ 空文件 / 全 ASCII
if [ ! -s "$f" ] || [ -z "$(LC_ALL=C tr -d '\000-\177' < "$f")" ]; then echo ascii; exit; fi
# ④ 严格 UTF-8 → 4a 双合法
if iconv -f UTF-8 -t UTF-8 "$f" >/dev/null 2>&1; then
  if iconv -f GBK -t UTF-8 "$f" >/dev/null 2>&1; then echo utf-8+gbk-dual; else echo utf-8; fi
  exit
fi
# ⑤ ⑥ ⑦
if iconv -f GBK -t UTF-8 "$f" >/dev/null 2>&1; then echo gbk; exit; fi
if iconv -f GB18030 -t UTF-8 "$f" >/dev/null 2>&1; then echo gb18030; exit; fi
echo unknown