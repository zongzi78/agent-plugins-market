#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""encoding-safe-edit skill 主实现（Python，首选运行时）。

子命令：detect / find / read / replace / convert / verify / cleanup / gc
安全语义：fail-closed、默认自动备份、dry-run、原子写、BOM/行尾保留、日志脱敏、不接 shell。
stdout 强制 UTF-8；错误对象 schema：{"ok":false,"error":str,"exitCode":int,"hint":str|null}。
"""
import sys
import os
import re
import json
import time
import shutil
import tempfile
import codecs
import bisect

if sys.version_info >= (3, 7):
    try:
        # newline="" disables \n -> \r\n translation on Windows (byte parity with enc.js)
        sys.stdout.reconfigure(encoding="utf-8", newline="")
        sys.stderr.reconfigure(encoding="utf-8", newline="")
    except Exception:
        pass

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNMATCHED = 2

# 自动判定候选集：UTF-8 / GBK / GB18030 / UTF-16(BOM)；显式编码支持 Python codec 注册表任意名。
AUTO_ENCODINGS = ("utf-8", "gbk", "gb18030")
HINT_CODECS = ("big5", "shift_jis", "euc_jp", "euc_kr", "cp1252")
MOJIBAKE_PATTERNS = ("锟斤拷", "锘", "鈥", "Ã©", "Ã¤")
DEFAULT_Q_RATIO = 0.05

HINT_DUAL = "valid in both utf-8 and gbk; follow project policy"
HINT_NUL = "contains many NUL bytes; maybe BOM-less UTF-16/UTF-32"
HINT_BOM_CORRUPT = "带 BOM 但正文无法严格解码，可能已损坏"
HINT_UTF32 = "UTF-32 BOM detected but unsupported; convert with an external tool"


# ---------------------------------------------------------------- 基础工具
def err_json(error, exit_code, hint=None):
    return {"ok": False, "error": error, "exitCode": exit_code, "hint": hint}


def emit(obj, exit_code=EXIT_OK):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")
    return exit_code


def log(msg):
    sys.stderr.write(msg + "\n")


def read_bytes(path):
    return _retry(_open_read, path)


def _open_read(path):
    with open(path, "rb") as f:
        return f.read()


def _retry(fn, *args, **kwargs):
    """对瞬态 PermissionError（Windows 文件锁）重试；其余异常直接抛。"""
    import time as _t
    last = None
    for _ in range(4):
        try:
            return fn(*args, **kwargs)
        except PermissionError as e:
            last = e
            _t.sleep(0.1)
    raise last


def is_regular_file(path):
    return os.path.isfile(path)


def strict_decode(data, encoding):
    """严格解码；失败返回 None。data 不含 BOM。"""
    try:
        return data.decode(encoding, errors="strict")
    except (UnicodeDecodeError, LookupError, ValueError):
        return None


def strict_encode(text, encoding):
    """严格编码；失败返回 None。"""
    try:
        return text.encode(encoding, errors="strict")
    except (UnicodeEncodeError, LookupError, ValueError):
        return None


def bom_of(data):
    """返回 (bom_kind, rest)。bom_kind ∈ none/utf-8/utf-16le/utf-16be/utf-32le/utf-32be。"""
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8", data[3:]
    if data.startswith(b"\xff\xfe\x00\x00"):
        return "utf-32le", data[4:]
    if data.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32be", data[4:]
    if data.startswith(b"\xff\xfe"):
        return "utf-16le", data[2:]
    if data.startswith(b"\xfe\xff"):
        return "utf-16be", data[2:]
    return "none", data


def bom_bytes(kind):
    return {None: b"", "none": b"", "utf-8": b"\xef\xbb\xbf", "utf-16le": b"\xff\xfe", "utf-16be": b"\xfe\xff"}.get(kind, b"")


def normalize_explicit(enc):
    """归一显式编码名；不支持/有歧义返回 None（utf-16 无 BOM 端序不定、utf-32 不支持）。"""
    if enc is None:
        return None
    e = enc.lower()
    aliases = {
        "utf8": "utf-8", "utf_8": "utf-8", "u8": "utf-8", "utf": "utf-8", "cp65001": "utf-8",
        "utf16le": "utf-16-le", "utf_16_le": "utf-16-le",
        "utf16be": "utf-16-be", "utf_16_be": "utf-16-be",
        "cp936": "gbk", "ms936": "gbk", "936": "gbk", "gb2312": "gbk",
        "gb18030-2000": "gb18030",
    }
    e = aliases.get(e, e)
    if e in ("utf-16", "utf_16", "utf16"):
        return None
    if e.startswith("utf-32") or e.startswith("utf_32") or e.startswith("utf32"):
        return None
    return e


def decode_with_bom(data, encoding):
    """按编码解码（自动处理 BOM 剥离）；返回 (text, actual_bom_kind) 或 None。
    actual_bom_kind 反映文件真实 BOM（none/utf-8/utf-16le/utf-16be），不是编码名。"""
    encoding = normalize_explicit(encoding)
    if encoding is None:
        return None
    if encoding == "utf-8":
        kind, body = bom_of(data)
        if kind not in ("none", "utf-8"):
            return None
        t = strict_decode(body, "utf-8")
        return (t, kind) if t is not None else None
    if encoding in ("utf-16-le", "utf-16le", "utf_16_le"):
        kind, body = bom_of(data)
        if kind not in ("none", "utf-16le"):
            return None
        t = strict_decode(body, "utf-16-le")
        return (t, kind) if t is not None else None
    if encoding in ("utf-16-be", "utf-16be", "utf_16_be"):
        kind, body = bom_of(data)
        if kind not in ("none", "utf-16be"):
            return None
        t = strict_decode(body, "utf-16-be")
        return (t, kind) if t is not None else None
    # 其余编码：按原样严格解码（不剥 BOM）
    t = strict_decode(data, encoding)
    return (t, "none") if t is not None else None


def encode_with_bom(text, encoding, bom):
    """按编码 + BOM 策略严格编码；失败返回 None。bom: none/utf-8/utf-16le/utf-16be。"""
    encoding = normalize_explicit(encoding)
    if encoding is None:
        return None
    if encoding == "utf-8":
        out = strict_encode(text, "utf-8")
        if out is None:
            return None
        return bom_bytes(bom) + out
    if encoding in ("utf-16-le", "utf-16le", "utf_16_le"):
        out = strict_encode(text, "utf-16-le")
        if out is None:
            return None
        return bom_bytes(bom) + out
    if encoding in ("utf-16-be", "utf-16be", "utf_16_be"):
        out = strict_encode(text, "utf-16-be")
        if out is None:
            return None
        return bom_bytes(bom) + out
    out = strict_encode(text, encoding)
    return out


def detect_line_ending(text):
    if "\r\n" in text:
        if "\n" in text.replace("\r\n", "") or "\r" in text.replace("\r\n", ""):
            return "mixed"
        return "crlf"
    if "\r" in text:
        if "\n" in text:
            return "mixed"
        return "cr"
    if "\n" in text:
        return "lf"
    return "unknown"


def normalize_lf(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_keepends(text):
    """按行拆分，保留行终止符；返回 [(content_without_term, term)]。"""
    lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)
    out = []
    for ln in lines:
        if ln == "":
            continue
        m = re.match(r"^(.*?)(\r\n|\r|\n|)$", ln)
        out.append((m.group(1), m.group(2)))
    # 处理空文件/纯终止符等边界
    if not out and text == "":
        return []
    return out


def atomic_write(path, data):
    """写临时文件后原子替换；失败清理临时文件并抛异常。"""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".enc-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # POSIX：保留原文件权限位（mkstemp 默认 0600 会收窄 0755/0644）；Windows 不做（无意义且会干扰只读清理）
        if os.name != "nt":
            try:
                os.chmod(tmp, os.stat(path).st_mode & 0o7777)
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            # Windows 上若 tmp 已被 chmod 成只读，先恢复可写再清理
            if os.name == "nt":
                os.chmod(tmp, 0o600)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_with_backup(path, data, backup=True):
    """先备份后原子写。备份 = <path>.orig（覆盖策略）。"""
    if backup:
        _retry(shutil.copy2, path, path + ".orig")
    atomic_write(path, data)


# ---------------------------------------------------------------- detect
def detect_file(path):
    data = read_bytes(path)
    bom_kind, body = bom_of(data)
    d = {
        "file": os.path.abspath(path),
        "encoding": "unknown",
        "confidence": "low",
        "bom": "none",
        "lineEnding": "unknown",
        "fffdCount": 0,
        "asciiOnly": True,
        "decodeHints": [],
        "suggestedAction": "unknown: ask",
    }
    # ① BOM
    if bom_kind in ("utf-32le", "utf-32be"):
        d["encoding"] = "unknown"
        d["confidence"] = "low"
        d["decodeHints"] = [HINT_UTF32]
        return d
    if bom_kind in ("utf-8", "utf-16le", "utf-16be"):
        enc = {"utf-8": "utf-8", "utf-16le": "utf-16-le", "utf-16be": "utf-16-be"}[bom_kind]
        t = strict_decode(body, enc)
        d["bom"] = bom_kind
        d["asciiOnly"] = all(b < 0x80 for b in body)
        if t is not None:
            d["encoding"] = {"utf-8": "utf-8", "utf-16le": "utf-16le", "utf-16be": "utf-16be"}[bom_kind]
            d["confidence"] = "high"
            d["lineEnding"] = detect_line_ending(t)
            d["fffdCount"] = t.count("\ufffd")
            d["suggestedAction"] = "use replace tool" if bom_kind == "utf-8" else "use replace/convert tool"
        else:
            d["encoding"] = {"utf-8": "utf-8", "utf-16le": "utf-16le", "utf-16be": "utf-16be"}[bom_kind]
            d["confidence"] = "medium"
            d["decodeHints"] = [HINT_BOM_CORRUPT]
            d["suggestedAction"] = "use replace tool / follow project policy"
        return d
    # ② NUL 密度全局预检
    nul_heavy = len(data) > 0 and (data.count(0) / len(data)) > 0.01
    # ③ 空文件 / 全 ASCII
    ascii_only = all(b < 0x80 for b in data)
    if ascii_only:
        d["encoding"] = "ascii"
        d["confidence"] = "medium" if nul_heavy else "low"
        d["asciiOnly"] = True
        if nul_heavy:
            d["decodeHints"] = [HINT_NUL]
            d["suggestedAction"] = "use replace/convert tool with explicit --encoding"
        else:
            d["suggestedAction"] = "use replace tool"
        if data == b"":
            d["lineEnding"] = "unknown"
        else:
            d["lineEnding"] = detect_line_ending(data.decode("ascii", errors="strict"))
        return d
    # ④ 严格 UTF-8
    utf8_ok = strict_decode(data, "utf-8") is not None
    gbk_ok = strict_decode(data, "gbk") is not None
    if utf8_ok:
        d["encoding"] = "utf-8"
        d["asciiOnly"] = False
        if gbk_ok:
            d["confidence"] = "medium"
            d["decodeHints"] = [HINT_DUAL]
            d["suggestedAction"] = "use replace tool / follow project policy"
        else:
            d["confidence"] = "high"
            d["suggestedAction"] = "use replace tool"
        d["lineEnding"] = detect_line_ending(data.decode("utf-8", errors="strict"))
        d["fffdCount"] = data.decode("utf-8", errors="strict").count("\ufffd")
        if nul_heavy:
            d["confidence"] = "medium"
            d["suggestedAction"] = "use replace/convert tool with explicit --encoding"
            d["decodeHints"] = [HINT_NUL]
        return d
    # ⑤ 严格 GBK
    if gbk_ok:
        d["encoding"] = "gbk"
        d["confidence"] = "medium" if nul_heavy else "high"
        d["asciiOnly"] = False
        d["lineEnding"] = detect_line_ending(data.decode("gbk", errors="strict"))
        d["fffdCount"] = data.decode("gbk", errors="strict").count("\ufffd")
        if nul_heavy:
            d["decodeHints"] = [HINT_NUL]
            d["suggestedAction"] = "use replace/convert tool with explicit --encoding"
        else:
            d["suggestedAction"] = "use replace tool"
        return d
    # ⑥ 严格 GB18030
    gb18030_ok = strict_decode(data, "gb18030") is not None
    if gb18030_ok:
        d["encoding"] = "gb18030"
        d["confidence"] = "medium" if nul_heavy else "high"
        d["asciiOnly"] = False
        d["lineEnding"] = detect_line_ending(data.decode("gb18030", errors="strict"))
        d["fffdCount"] = data.decode("gb18030", errors="strict").count("\ufffd")
        if nul_heavy:
            d["decodeHints"] = [HINT_NUL]
            d["suggestedAction"] = "use replace/convert tool with explicit --encoding"
        else:
            d["suggestedAction"] = "use replace tool"
        return d
    # ⑦ unknown
    d["encoding"] = "unknown"
    d["confidence"] = "low"
    d["asciiOnly"] = False
    d["suggestedAction"] = "unknown: ask"
    hints = []
    for c in HINT_CODECS:
        if strict_decode(data, c) is not None:
            hints.append("could be %s" % c)
    if nul_heavy:
        hints.append(HINT_NUL)
    d["decodeHints"] = hints
    return d


# ---------------------------------------------------------------- 写路径公共
def resolve_source_encoding(path, data, explicit):
    """返回 (encoding, bom_kind, decode_error) 或 (None, None, errmsg)。
    fail-closed 规则：unknown / NUL-heavy 未显式指定编码时，read/replace/convert 一律拒绝。"""
    if explicit:
        enc = normalize_explicit(explicit)
        if enc is None:
            low = explicit.lower()
            if low in ("utf-16", "utf_16", "utf16"):
                return None, None, "encoding '%s' is ambiguous; use utf-16-le or utf-16-be" % explicit
            return None, None, "encoding '%s' is not supported (UTF-32); convert with an external tool" % explicit
        bom_kind, _ = bom_of(data)
        return enc, bom_kind, None
    det = detect_file(path)
    enc = det["encoding"]
    if enc == "unknown":
        return None, None, "unknown encoding; specify --encoding explicitly"
    if det["confidence"] == "medium" and HINT_NUL in det["decodeHints"]:
        return None, None, "NUL-heavy file (possible BOM-less UTF-16/UTF-32); specify --encoding utf-16-le/be explicitly"
    bom_kind, _ = bom_of(data)
    return enc, bom_kind, None


def load_ops(ops_arg, from_file):
    if from_file:
        if not os.path.isfile(from_file):
            return None, "ops file not found: %s" % from_file
        try:
            with open(from_file, "r", encoding="utf-8") as f:
                raw = f.read()
        except (OSError, UnicodeDecodeError) as e:
            return None, "cannot read ops file: %s" % e
    else:
        raw = ops_arg
    try:
        ops = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, "ops JSON parse error: %s" % e
    if not isinstance(ops, list):
        return None, "ops must be a JSON array"
    cleaned = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or "search" not in op or not isinstance(op["search"], str) or op["search"] == "":
            return None, "ops[%d] must be an object with non-empty string 'search'" % i
        if "replace" in op and not isinstance(op["replace"], str):
            return None, "ops[%d].replace must be a string" % i
        if "label" in op and not isinstance(op["label"], str):
            return None, "ops[%d].label must be a string" % i
        cleaned.append({
            "search": op["search"],
            "replace": op.get("replace", ""),
            "label": op.get("label", "op%d" % (i + 1)),
        })
    return cleaned, None


def apply_ops(text, ops):
    """在解码后文本上应用 ops；返回 (new_text, counts, whole_text_mode) 或 (None, None, "error: ...")。
    多行 op（search/replace 含换行）在 mixed 行尾文件上无法保证"逐行保留原行尾"→ fail-closed。"""
    counts = [0] * len(ops)
    whole = any(("\n" in normalize_lf(o["search"])) or ("\n" in normalize_lf(o["replace"])) for o in ops)
    if whole:
        if detect_line_ending(text) == "mixed":
            return None, None, "cannot apply multi-line op to a mixed-line-ending file (fail-closed); normalize line endings first"
        cur = normalize_lf(text)
        for i, o in enumerate(ops):
            s = normalize_lf(o["search"])
            r = normalize_lf(o["replace"])
            c = cur.count(s)
            counts[i] = c
            if c:
                cur = cur.replace(s, r)
        if "\r\n" in text:
            end = "\r\n"
        elif "\r" in text:
            end = "\r"
        else:
            end = "\n"
        new_text = cur.replace("\n", end)
        return new_text, counts, True
    # 逐行模式
    lines = split_keepends(text)
    new_lines = []
    for content, term in lines:
        for i, o in enumerate(ops):
            s = o["search"]
            r = o["replace"]
            c = content.count(s)
            counts[i] += c
            if c:
                content = content.replace(s, r)
        new_lines.append(content + term)
    return "".join(new_lines), counts, False


_CRED_RE = re.compile(r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|authorization|credential)\s*[:=]\s*)[^\s,;\"\']+")

def redact(text, limit=60):
    """日志脱敏：掩码 key=value 型凭据 + 截断；不输出文件内明文凭据。"""
    t = _CRED_RE.sub(lambda m: m.group(1) + "***", text)
    return t if len(t) <= limit else t[:limit] + "..."


def verbose_hex(data, label):
    # 先对文本样本脱敏再 hex（避免 hex 可逆泄露文件头明文，如 password=...）
    sample = redact(data[:64].decode("utf-8", "replace"))
    log("[verbose] %s bytes=%d first64=%s" % (label, len(data), " ".join("%02x" % b for b in sample.encode("utf-8"))))


# ---------------------------------------------------------------- 子命令

def _build_fold_map(text):
    """返回 (casefold 后的文本, orig_idx)。orig_idx[i] = 折叠文本第 i 个码点对应的原始码点下标。"""
    parts = []
    orig = []
    for i, ch in enumerate(text):
        f = ch.casefold()
        parts.append(f)
        for _ in f:
            orig.append(i)
    return "".join(parts), orig


def _clip(s, n):
    return s if len(s) <= n else s[:n] + "…"


def _locate(off, starts, rows):
    """根据全局码点偏移定位 (1-based line, 1-based col, 行内容)。"""
    i = bisect.bisect_right(starts, off) - 1
    if i < 0:
        i = 0
    if i >= len(rows):
        i = len(rows) - 1
    content, term = rows[i]
    return i + 1, off - starts[i] + 1, content


def cmd_find(path, pattern, pattern_file, explicit, ignore_case, max_count, verbose=False):
    if pattern is None:
        if pattern_file is None:
            return emit(err_json("find requires a pattern or --pattern-file", EXIT_ERROR), EXIT_ERROR)
        try:
            raw = open(pattern_file, "rb").read()
        except OSError as e:
            return emit(err_json("cannot read pattern file: %s" % e, EXIT_ERROR), EXIT_ERROR)
        if raw.startswith(codecs.BOM_UTF8):
            raw = raw[3:]
        try:
            pattern = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            return emit(err_json("pattern file is not valid UTF-8: %s" % e, EXIT_ERROR), EXIT_ERROR)
        pattern = re.sub(r"(?:\r\n|\r|\n)$", "", pattern, count=1)
    if not pattern:
        return emit(err_json("empty pattern", EXIT_ERROR), EXIT_ERROR)
    if not is_regular_file(path):
        return emit(err_json("not a regular file: %s" % path, EXIT_ERROR), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO error: %s" % e, EXIT_ERROR), EXIT_ERROR)
    enc, bom, de = resolve_source_encoding(path, data, explicit)
    if de:
        return emit(err_json(de, EXIT_ERROR, "use --encoding to specify the file encoding"), EXIT_ERROR)
    res = decode_with_bom(data, enc)
    if res is None:
        return emit(err_json("strict decode failed as %s" % enc, EXIT_ERROR), EXIT_ERROR)
    text, bom_kind = res
    det = None if explicit else detect_file(path)
    line_end = det["lineEnding"] if det else detect_line_ending(text)
    work = normalize_lf(text)
    rows = split_keepends(work)
    starts = []
    off = 0
    for content, term in rows:
        starts.append(off)
        off += len(content) + len(term)
    if ignore_case:
        search, orig_idx = _build_fold_map(work)
        pat = normalize_lf(pattern).casefold()
        if not pat:
            return emit(err_json("empty folded pattern", EXIT_ERROR), EXIT_ERROR)
        patlen = len(pat)
        step = patlen
    else:
        search = work
        orig_idx = None
        pat = normalize_lf(pattern)
        patlen = len(pat)
        step = patlen
    matches = []
    total = 0
    pos = 0
    while True:
        idx = search.find(pat, pos)
        if idx < 0:
            break
        total += 1
        if total <= max_count:
            o_off = orig_idx[idx] if ignore_case else idx
            line_no, col, row_text = _locate(o_off, starts, rows)
            matches.append({
                "line": line_no,
                "col": col,
                "text": _clip(row_text, 200),
                "snippet": _clip(row_text.strip(), 200),
            })
        pos = idx + step
        if step <= 0:
            break
    if verbose:
        log("[verbose] find pattern=%s matchCount=%d" % (redact(pattern), total))
    return emit({"ok": True, "file": os.path.abspath(path), "encoding": enc, "bom": bom_kind,
                 "lineEnding": line_end, "matchCount": total, "matches": matches}, EXIT_OK)


def cmd_detect(path):
    if not is_regular_file(path):
        return emit(err_json("not a regular file: %s" % path, EXIT_ERROR), EXIT_ERROR)
    try:
        d = detect_file(path)
    except OSError as e:
        return emit(err_json("IO error: %s" % e, EXIT_ERROR), EXIT_ERROR)
    return emit(d, EXIT_OK)


def cmd_read(path, out, explicit, line=None, from_line=None, to_line=None):
    if not is_regular_file(path):
        return emit(err_json("not a regular file: %s" % path, EXIT_ERROR), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO error: %s" % e, EXIT_ERROR), EXIT_ERROR)
    enc, bom, de = resolve_source_encoding(path, data, explicit)
    if de:
        return emit(err_json(de, EXIT_ERROR, "use --encoding to specify the file encoding"), EXIT_ERROR)
    res = decode_with_bom(data, enc)
    if res is None:
        return emit(err_json("strict decode failed as %s" % enc, EXIT_ERROR), EXIT_ERROR)
    text, bom_kind = res
    if line is None and from_line is None and to_line is None:
        if out:
            try:
                with open(out, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
            except OSError as e:
                return emit(err_json("cannot write out file: %s" % e, EXIT_ERROR), EXIT_ERROR)
            return emit({"ok": True, "out": os.path.abspath(out), "encoding": enc, "bom": bom_kind,
                         "bytesWritten": len(text.encode("utf-8"))}, EXIT_OK)
        det = detect_file(path) if not explicit else None
        sys.stdout.write(text)
        if det:
            log("detect: encoding=%s confidence=%s bom=%s lineEnding=%s" % (
                det["encoding"], det["confidence"], det["bom"], det["lineEnding"]))
        return EXIT_OK
    rows = split_keepends(text)
    total = len(rows)
    if total == 0:
        return emit(err_json("empty file has no lines to read", EXIT_ERROR), EXIT_ERROR)
    if line is not None:
        if line > total:
            return emit(err_json("line %d out of range (file has %d lines)" % (line, total), EXIT_ERROR), EXIT_ERROR)
        start_idx = line - 1
        end_idx = line
        from_line_eff = line
        to_line_eff = line
    else:
        if from_line > total:
            return emit(err_json("from line %d out of range (file has %d lines)" % (from_line, total), EXIT_ERROR), EXIT_ERROR)
        start_idx = from_line - 1
        end_idx = to_line if to_line <= total else total
        from_line_eff = from_line
        to_line_eff = end_idx
    body = "".join(content + term for content, term in rows[start_idx:end_idx])
    if out:
        try:
            with open(out, "w", encoding="utf-8", newline="") as f:
                f.write(body)
        except OSError as e:
            return emit(err_json("cannot write out file: %s" % e, EXIT_ERROR), EXIT_ERROR)
        return emit({"ok": True, "out": os.path.abspath(out), "encoding": enc, "bom": bom_kind,
                     "bytesWritten": len(body.encode("utf-8")),
                     "fromLine": from_line_eff, "toLine": to_line_eff, "totalLines": total}, EXIT_OK)
    det = detect_file(path) if not explicit else None
    sys.stdout.write(body)
    if det:
        log("detect: encoding=%s confidence=%s bom=%s lineEnding=%s" % (
            det["encoding"], det["confidence"], det["bom"], det["lineEnding"]))
    return EXIT_OK
def cmd_replace(path, ops_arg, from_file, explicit, dry_run, keep_backup, verbose, force):
    if not is_regular_file(path):
        return emit(err_json("not a regular file: %s" % path, EXIT_ERROR), EXIT_ERROR)
    ops, oerr = load_ops(ops_arg, from_file)
    if oerr:
        return emit(err_json(oerr, EXIT_ERROR), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO error: %s" % e, EXIT_ERROR), EXIT_ERROR)
    enc, bom, de = resolve_source_encoding(path, data, explicit)
    if de:
        return emit(err_json(de, EXIT_ERROR, "use --encoding to specify the file encoding"), EXIT_ERROR)
    res = decode_with_bom(data, enc)
    if res is None:
        return emit(err_json("strict decode failed as %s (fail-closed; nothing written)" % enc, EXIT_ERROR), EXIT_ERROR)
    text, bom_kind = res
    new_text, counts, whole_mode = apply_ops(text, ops)
    if new_text is None:
        return emit(err_json(whole_mode, EXIT_ERROR), EXIT_ERROR)
    unmatched = [ops[i]["label"] for i in range(len(ops)) if counts[i] == 0]
    if unmatched and not force:
        return emit(err_json("%d op(s) unmatched; nothing written (fail-closed)" % len(unmatched), EXIT_UNMATCHED,
                             "use --force to apply matched ops anyway"), EXIT_UNMATCHED)
    if dry_run:
        preview = [{"label": ops[i]["label"], "count": counts[i]} for i in range(len(ops))]
        return emit({"ok": True, "dryRun": True, "applied": sum(1 for c in counts if c > 0),
                     "matches": preview, "unmatched": unmatched, "warnings": []}, EXIT_UNMATCHED if unmatched else EXIT_OK)
    out_enc = enc
    out_bom = bom_kind if bom_kind != "none" else "none"
    payload = encode_with_bom(new_text, out_enc, out_bom)
    if payload is None:
        return emit(err_json("strict encode failed as %s (fail-closed; nothing written)" % out_enc, EXIT_ERROR), EXIT_ERROR)
    if verbose:
        verbose_hex(data, "original")
        verbose_hex(payload, "result")
        for i, o in enumerate(ops):
            log("[verbose] op%d %r -> %r count=%d" % (i + 1, redact(o["search"]), redact(o["replace"]), counts[i]))
    if len(ops) == 0:
        return emit({"ok": True, "applied": 0, "matches": [], "backup": None, "cleanup": None,
                     "dryRun": False, "warnings": []}, EXIT_OK)
    try:
        write_with_backup(path, payload, backup=True)
    except OSError as e:
        return emit(err_json("write failed: %s" % e, EXIT_ERROR), EXIT_ERROR)
    backup_final, cleanup, damaged = post_write_cleanup(path, new_text, out_enc, keep_backup)
    if verbose:
        log("[verbose] wrote %d bytes; backup=%s; cleanup=%s" % (len(payload), backup_final, cleanup))
    warnings = [{"label": l} for l in unmatched] if unmatched else []
    return emit({"ok": True, "applied": sum(1 for c in counts if c > 0),
                 "matches": [{"label": ops[i]["label"], "count": counts[i]} for i in range(len(ops))],
                 "backup": backup_final, "cleanup": cleanup, "damaged": damaged,
                 "dryRun": False, "warnings": warnings}, EXIT_UNMATCHED if unmatched else EXIT_OK)


def cmd_convert(path, to, from_enc, bom_policy, line_ending, dry_run, keep_backup):
    if not is_regular_file(path):
        return emit(err_json("not a regular file: %s" % path, EXIT_ERROR), EXIT_ERROR)
    if not to:
        return emit(err_json("--to <encoding> is required", EXIT_ERROR), EXIT_ERROR)
    to_orig = to
    to = normalize_explicit(to)
    if to is None:
        low = to_orig.lower()
        if low in ("utf-16", "utf_16", "utf16"):
            return emit(err_json("--to %s is ambiguous; use utf-16-le or utf-16-be" % to_orig, EXIT_ERROR), EXIT_ERROR)
        return emit(err_json("--to %s is not supported (UTF-32); convert with an external tool" % to_orig, EXIT_ERROR), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO error: %s" % e, EXIT_ERROR), EXIT_ERROR)
    src_enc, src_bom, de = resolve_source_encoding(path, data, from_enc)
    if de:
        return emit(err_json(de, EXIT_ERROR, "use --from to specify the source encoding"), EXIT_ERROR)
    res = decode_with_bom(data, src_enc)
    if res is None:
        return emit(err_json("strict decode failed as %s (fail-closed; nothing written)" % src_enc, EXIT_ERROR), EXIT_ERROR)
    text, bom_kind = res
    if line_ending == "crlf":
        text = normalize_lf(text).replace("\n", "\r\n")
    elif line_ending == "lf":
        text = normalize_lf(text)
    target_bom = "none"
    if to == "utf-8":
        if bom_policy == "add":
            target_bom = "utf-8"
        elif bom_policy == "keep" and bom_kind != "none":
            target_bom = "utf-8"
    elif to in ("utf-16-le", "utf-16le", "utf_16_le"):
        if bom_policy == "add":
            target_bom = "utf-16le"
        elif bom_policy == "keep" and bom_kind != "none":
            target_bom = "utf-16le"
    elif to in ("utf-16-be", "utf-16be", "utf_16_be"):
        if bom_policy == "add":
            target_bom = "utf-16be"
        elif bom_policy == "keep" and bom_kind != "none":
            target_bom = "utf-16be"
    payload = encode_with_bom(text, to, target_bom)
    if payload is None:
        return emit(err_json("strict encode failed as %s (fail-closed; nothing written)" % to, EXIT_ERROR), EXIT_ERROR)
    if dry_run:
        return emit({"ok": True, "dryRun": True, "from": src_enc, "to": to, "bom": target_bom,
                     "lineEnding": line_ending, "backup": None, "cleanup": None}, EXIT_OK)
    try:
        write_with_backup(path, payload, backup=True)
    except OSError as e:
        return emit(err_json("write failed: %s" % e, EXIT_ERROR), EXIT_ERROR)
    backup_final, cleanup, damaged = post_write_cleanup(path, text, to, keep_backup)
    return emit({"ok": True, "from": src_enc, "to": to, "bom": target_bom,
                 "lineEnding": line_ending, "dryRun": False,
                 "backup": backup_final, "cleanup": cleanup, "damaged": damaged}, EXIT_OK)



def verify_text(text, encoding):
    """纯函数：对解码后文本做损坏判定（与 cmd_verify 口径一致，供 verify / 写后事务共用）。"""
    fffd_count = text.count("\ufffd")
    fffd_samples = []
    if fffd_count:
        for m in re.finditer("\ufffd", text):
            if len(fffd_samples) >= 5:
                break
            pos = m.start()
            snippet = text[max(0, pos - 10):pos + 11]
            fffd_samples.append({"charOffset": pos, "snippet": redact(snippet, 40)})
    q_count = text.count("?")
    total = len(text)
    q_ratio = q_count / max(1, total)
    threshold = float(os.environ.get("ENC_VERIFY_Q_RATIO", str(DEFAULT_Q_RATIO)))
    non_ascii = any(ord(c) > 0x7F for c in text)
    suspicious_q = q_ratio > threshold and non_ascii
    mojibake = {}
    for pat in MOJIBAKE_PATTERNS:
        cc = text.count(pat)
        if cc:
            mojibake[pat] = cc
    damaged = fffd_count > 0 or bool(mojibake) or suspicious_q
    return {"fffdCount": fffd_count, "fffdSamples": fffd_samples, "qCount": q_count,
            "qRatio": round(q_ratio, 6), "suspiciousQ": suspicious_q,
            "mojibakePatterns": mojibake, "damaged": damaged}


def post_write_cleanup(path, text, enc, keep_backup):
    """写后处理：决定 .orig 终态。写路径恒先备份；keep_backup 保留；否则按 verify_text 自动清。
    返回 (backup_final, cleanup, damaged)。cleanup ∈ removed / retained；damaged 表示是否因内部验证检测到损坏而保留（keep_backup 自愿保留时恒为 False）。"""
    backup = path + ".orig"
    if keep_backup:
        return backup, "retained", False
    v = verify_text(text, enc)
    if v["damaged"]:
        return backup, "retained", True
    if os.path.isfile(backup):
        try:
            os.remove(backup)
        except OSError:
            return backup, "retained", True
    return None, "removed", False

def cmd_verify(path, explicit):
    if not is_regular_file(path):
        return emit(err_json("not a regular file: %s" % path, EXIT_ERROR), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO error: %s" % e, EXIT_ERROR), EXIT_ERROR)
    det = detect_file(path)
    enc = explicit or det["encoding"]
    if enc == "unknown":
        return emit(err_json("unknown encoding; cannot verify", EXIT_ERROR, "use --encoding"), EXIT_ERROR)
    res = decode_with_bom(data, enc)
    if res is None:
        return emit(err_json("strict decode failed as %s; cannot verify" % enc, EXIT_ERROR), EXIT_ERROR)
    text, _ = res
    v = verify_text(text, enc)
    if v["damaged"]:
        action = "file appears damaged; restore from backup (e.g. <file>.orig) if available and re-edit via enc replace"
    else:
        base = "no damage detected; safe to proceed"
        if os.path.isfile(path + ".orig"):
            action = base + " (backup snapshot retained; run `enc cleanup <file>` to remove)"
        else:
            action = base
    return emit({"ok": True, "file": os.path.abspath(path), "encoding": enc, "confidence": det["confidence"],
                 "fffdCount": v["fffdCount"], "fffdSamples": v["fffdSamples"], "qCount": v["qCount"],
                 "qRatio": v["qRatio"], "suspiciousQ": v["suspiciousQ"],
                 "mojibakePatterns": v["mojibakePatterns"], "damaged": v["damaged"],
                 "suggestedAction": action}, EXIT_OK)


def cmd_cleanup(path):
    """删除 <file>.orig 单步撤销快照；幂等（无可删时 removed=null）。"""
    if not is_regular_file(path):
        return emit(err_json("not a regular file: %s" % path, EXIT_ERROR), EXIT_ERROR)
    backup = path + ".orig"
    if not os.path.lexists(backup):
        return emit({"ok": True, "file": os.path.abspath(path), "removed": None}, EXIT_OK)
    if not os.path.isfile(backup):
        return emit(err_json("backup path is not a regular file: %s" % backup, EXIT_ERROR), EXIT_ERROR)
    try:
        os.remove(backup)
    except OSError as e:
        return emit(err_json("cleanup failed: %s" % e, EXIT_ERROR), EXIT_ERROR)
    return emit({"ok": True, "file": os.path.abspath(path), "removed": os.path.abspath(backup)}, EXIT_OK)


def cmd_gc(path, all_flag):
    """gc <dir> [--all]：维护命令。默认删除孤儿 .orig（target 缺失）；--all 递归删除全部。"""
    if not os.path.isdir(path):
        return emit(err_json("not a directory: %s" % path, EXIT_ERROR), EXIT_ERROR)
    removed, kept = [], []
    for root, dirs, files in os.walk(path):
        for fn in sorted(files):
            if not fn.endswith(".orig"):
                continue
            fp = os.path.join(root, fn)
            target = fp[:-len(".orig")]
            if all_flag or not os.path.exists(target):
                try:
                    os.remove(fp)
                    removed.append(os.path.abspath(fp))
                except OSError:
                    kept.append(os.path.abspath(fp))
            else:
                kept.append(os.path.abspath(fp))
    return emit({"ok": True, "dir": os.path.abspath(path), "removed": removed, "kept": kept}, EXIT_OK)


USAGE = """usage: enc <subcommand> [options]

subcommands:
  detect <file>
  find <file> <pattern> | --pattern-file <utf8-file> [--encoding <enc>] [--ignore-case] [--max-count N] [--verbose]
  read <file> [--out <utf8-path>] [--encoding <enc>]
          [--line N] [--from-line N --to-line M]
  replace <file> <ops-json> | --from-file <ops-file>
          [--encoding <enc>] [--dry-run] [--keep-backup] [--verbose] [--force]
  convert <file> --to <enc> [--from <enc>] [--bom add|remove|keep]
          [--line-ending keep|crlf|lf] [--dry-run] [--keep-backup]
  verify <file> [--encoding <enc>]
  cleanup <file>
  gc <dir> [--all]

Global: -h, --help                     show this help; exit 0
        help <subcommand>              show subcommand help
        <subcommand> --help            show subcommand help
Note: --no-backup was removed (bottom line: writes always make a backup).
"""



def take_option(args, flag, need_value=False):
    """扫描 args 取选项；返回 (剩余 args, 值 or None)。支持 --flag value 与 --flag=value。
    布尔旗标命中时值为 True。"""
    rest = []
    value = None
    found = False
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith(flag + "="):
            found = True
            value = a[len(flag) + 1:]
            i += 1
            continue
        if a == flag:
            found = True
            if need_value:
                if i + 1 < len(args):
                    value = args[i + 1]
                    i += 2
                    continue
                else:
                    value = None
                    i += 1
                    continue
            value = True
            i += 1
            continue
        rest.append(a)
        i += 1
    return rest, (value if found else None)


SUB_HELP = {
 "detect": "enc detect <file>\n  Detect encoding/confidence/BOM/lineEnding/suggestedAction.\n",
 "find": "enc find <file> <pattern> | --pattern-file <utf8-file> [--encoding <enc>] [--ignore-case] [--max-count N] [--verbose]\n  Locate literal substring (non-regex) in decoded text; output JSON matchCount/matches.\n",
 "read": "enc read <file> [--out <utf8-path>] [--encoding <enc>] [--line N] [--from-line N --to-line M]\n  Decode to UTF-8 (stdout or --out); does not modify the file. With line args, output only selected lines.\n",
 "replace": "enc replace <file> <ops-json> | --from-file <ops-file> [--encoding <enc>] [--dry-run] [--keep-backup] [--verbose] [--force]\n  Byte-safe replace; writes always make a backup; default verifies & auto-removes .orig; --keep-backup retains it.\n",
 "convert": "enc convert <file> --to <enc> [--from <enc>] [--bom add|remove|keep] [--line-ending keep|crlf|lf] [--dry-run] [--keep-backup]\n  Transcode preserving encoding/BOM/line ending; default verifies & auto-removes .orig.\n",
 "verify": "enc verify <file> [--encoding <enc>]\n  Scan for U+FFFD / ? density / mojibake patterns; suggests restore or cleanup (conditional on .orig).\n",
 "cleanup": "enc cleanup <file>\n  Remove <file>.orig single-step snapshot (maintenance).\n",
 "gc": "enc gc <dir> [--all]\n  Maintenance: remove orphan .orig (target missing); --all removes all *.orig under dir.\n",
}

def sub_help(name):
    txt = SUB_HELP.get(name)
    if not txt:
        return emit(err_json("unknown subcommand: %s" % name, EXIT_ERROR), EXIT_ERROR)
    sys.stdout.write(txt)
    return EXIT_OK


COMMANDS = {"detect", "find", "read", "replace", "convert", "verify", "cleanup", "gc"}

def main(argv):
    if not argv:
        sys.stderr.write(USAGE)
        return EXIT_ERROR
    sub = argv[0]
    args = argv[1:]
    if sub in ("-h", "--help"):
        sys.stdout.write(USAGE)
        return EXIT_OK
    if sub == "help":
        if len(args) != 1:
            return emit(err_json("help requires exactly one <subcommand>", EXIT_ERROR), EXIT_ERROR)
        return sub_help(args[0])
    if sub in COMMANDS and any(a in ("--help", "-h") for a in args):
        return sub_help(sub)
    if "--no-backup" in args:
        return emit(err_json("--no-backup was removed; writes always make a backup (bottom line)", EXIT_ERROR), EXIT_ERROR)
    if sub == "detect":
        if len(args) != 1:
            return emit(err_json("detect requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_detect(args[0])
    if sub == "read":
        args, out = take_option(args, "--out", True)
        args, enc = take_option(args, "--encoding", True)
        args, line_opt = take_option(args, "--line", True)
        args, from_opt = take_option(args, "--from-line", True)
        args, to_opt = take_option(args, "--to-line", True)
        if len(args) != 1:
            return emit(err_json("read requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        line = from_line = to_line = None
        if line_opt is not None or from_opt is not None or to_opt is not None:
            def _pos(v):
                try:
                    n = int(v)
                    return n if n > 0 else None
                except (ValueError, TypeError):
                    return None
            if line_opt is not None:
                line = _pos(line_opt)
                if line is None:
                    return emit(err_json("--line must be a positive integer", EXIT_ERROR), EXIT_ERROR)
            if from_opt is not None:
                from_line = _pos(from_opt)
                if from_line is None:
                    return emit(err_json("--from-line must be a positive integer", EXIT_ERROR), EXIT_ERROR)
            if to_opt is not None:
                to_line = _pos(to_opt)
                if to_line is None:
                    return emit(err_json("--to-line must be a positive integer", EXIT_ERROR), EXIT_ERROR)
            if line is not None and (from_line is not None or to_line is not None):
                return emit(err_json("--line cannot be combined with --from-line/--to-line", EXIT_ERROR), EXIT_ERROR)
            if (from_line is None) != (to_line is None):
                return emit(err_json("--from-line and --to-line must be used together", EXIT_ERROR), EXIT_ERROR)
            if from_line is not None and from_line > to_line:
                return emit(err_json("--from-line must be <= --to-line", EXIT_ERROR), EXIT_ERROR)
        return cmd_read(args[0], out, enc, line, from_line, to_line)
    if sub == "find":
        args, pfile = take_option(args, "--pattern-file", True)
        args, enc = take_option(args, "--encoding", True)
        args, ic = take_option(args, "--ignore-case")
        args, verb = take_option(args, "--verbose")
        args, mc = take_option(args, "--max-count", True)
        max_count = 100
        if mc is not None:
            try:
                max_count = int(mc)
            except ValueError:
                return emit(err_json("--max-count must be a positive integer", EXIT_ERROR), EXIT_ERROR)
            if max_count <= 0:
                return emit(err_json("--max-count must be a positive integer", EXIT_ERROR), EXIT_ERROR)
        if pfile is not None:
            if not os.path.isfile(pfile):
                return emit(err_json("pattern file not found: %s" % pfile, EXIT_ERROR), EXIT_ERROR)
            if len(args) != 1:
                return emit(err_json("find --pattern-file requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
            return cmd_find(args[0], None, pfile, enc, ic is not None, max_count, verb is not None)
        if len(args) != 2:
            return emit(err_json("find requires <file> <pattern> or --pattern-file <file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_find(args[0], args[1], None, enc, ic is not None, max_count, verb is not None)
    if sub == "replace":
        args, ff = take_option(args, "--from-file", True)
        args, enc = take_option(args, "--encoding", True)
        args, dry = take_option(args, "--dry-run")
        args, kb = take_option(args, "--keep-backup")
        args, verb = take_option(args, "--verbose")
        args, force = take_option(args, "--force")
        if ff is not None:
            if len(args) != 1:
                return emit(err_json("replace --from-file requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
            return cmd_replace(args[0], None, ff, enc, dry is not None, kb is not None, verb is not None, force is not None)
        if len(args) != 2:
            return emit(err_json("replace requires <file> <ops-json> or --from-file <ops-file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_replace(args[0], args[1], None, enc, dry is not None, kb is not None, verb is not None, force is not None)
    if sub == "convert":
        args, to = take_option(args, "--to", True)
        args, frm = take_option(args, "--from", True)
        args, bom = take_option(args, "--bom", True)
        args, le = take_option(args, "--line-ending", True)
        args, dry = take_option(args, "--dry-run")
        args, kb = take_option(args, "--keep-backup")
        if len(args) != 1:
            return emit(err_json("convert requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        if bom is not None and bom not in ("add", "remove", "keep"):
            return emit(err_json("--bom must be add|remove|keep", EXIT_ERROR), EXIT_ERROR)
        if le is not None and le not in ("keep", "crlf", "lf"):
            return emit(err_json("--line-ending must be keep|crlf|lf", EXIT_ERROR), EXIT_ERROR)
        return cmd_convert(args[0], to, frm, bom or "keep", le or "keep", dry is not None, kb is not None)
    if sub == "verify":
        args, enc = take_option(args, "--encoding", True)
        if len(args) != 1:
            return emit(err_json("verify requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_verify(args[0], enc)
    if sub == "cleanup":
        if len(args) != 1:
            return emit(err_json("cleanup requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_cleanup(args[0])
    if sub == "gc":
        args, allf = take_option(args, "--all")
        if len(args) != 1:
            return emit(err_json("gc requires exactly one <dir>", EXIT_ERROR), EXIT_ERROR)
        return cmd_gc(args[0], allf is not None)
    return emit(err_json("unknown subcommand: %s" % sub, EXIT_ERROR), EXIT_ERROR)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))