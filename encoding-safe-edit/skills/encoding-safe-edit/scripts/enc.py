#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""encoding-safe-edit skill 主实现（Python，首选运行时）。

子命令：detect / read / replace / convert / verify / selfcheck
安全语义：fail-closed、默认自动备份、dry-run、原子写、BOM/行尾保留、日志脱敏、不接 shell。
stdout 强制 UTF-8；错误对象 schema：{"ok":false,"error":str,"exitCode":int,"hint":str|null}。
"""
import sys
import os
import re
import json
import shutil
import tempfile
import subprocess
import codecs

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
    with open(path, "rb") as f:
        return f.read()


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
        shutil.copy2(path, path + ".orig")
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
        "safeToEditDirectly": False,
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
            d["safeToEditDirectly"] = False  # 带 BOM 一律不可直写
            d["suggestedAction"] = "use replace tool" if bom_kind == "utf-8" else "use replace/convert tool"
        else:
            d["encoding"] = {"utf-8": "utf-8", "utf-16le": "utf-16le", "utf-16be": "utf-16be"}[bom_kind]
            d["confidence"] = "medium"
            d["decodeHints"] = [HINT_BOM_CORRUPT]
            d["safeToEditDirectly"] = False
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
            d["safeToEditDirectly"] = False
            d["suggestedAction"] = "use replace/convert tool with explicit --encoding"
        else:
            d["safeToEditDirectly"] = True
            d["suggestedAction"] = "native edit allowed if project permits"
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
            d["safeToEditDirectly"] = False
            d["suggestedAction"] = "use replace tool / follow project policy"
        else:
            d["confidence"] = "high"
            d["safeToEditDirectly"] = True
            d["suggestedAction"] = "native edit allowed if project permits"
        d["lineEnding"] = detect_line_ending(data.decode("utf-8", errors="strict"))
        d["fffdCount"] = data.decode("utf-8", errors="strict").count("\ufffd")
        if nul_heavy:
            d["confidence"] = "medium"
            d["safeToEditDirectly"] = False
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
            d["safeToEditDirectly"] = False
            d["suggestedAction"] = "use replace/convert tool with explicit --encoding"
        else:
            d["safeToEditDirectly"] = False
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
            d["safeToEditDirectly"] = False
            d["suggestedAction"] = "use replace/convert tool with explicit --encoding"
        else:
            d["safeToEditDirectly"] = False
            d["suggestedAction"] = "use replace tool"
        return d
    # ⑦ unknown
    d["encoding"] = "unknown"
    d["confidence"] = "low"
    d["asciiOnly"] = False
    d["safeToEditDirectly"] = False
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
def cmd_detect(path):
    if not is_regular_file(path):
        return emit(err_json("not a regular file: %s" % path, EXIT_ERROR), EXIT_ERROR)
    try:
        d = detect_file(path)
    except OSError as e:
        return emit(err_json("IO error: %s" % e, EXIT_ERROR), EXIT_ERROR)
    return emit(d, EXIT_OK)


def cmd_read(path, out, explicit):
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
    if out:
        try:
            with open(out, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except OSError as e:
            return emit(err_json("cannot write out file: %s" % e, EXIT_ERROR), EXIT_ERROR)
        return emit({"ok": True, "out": os.path.abspath(out), "encoding": enc, "bom": bom_kind,
                     "bytesWritten": len(text.encode("utf-8"))}, EXIT_OK)
    # stdout 原始文本（字节精确，不追加换行）；摘要走 stderr
    det = detect_file(path) if not explicit else None
    sys.stdout.write(text)
    if det:
        log("detect: encoding=%s confidence=%s bom=%s lineEnding=%s" % (
            det["encoding"], det["confidence"], det["bom"], det["lineEnding"]))
    return EXIT_OK


def cmd_replace(path, ops_arg, from_file, explicit, dry_run, no_backup, verbose, force):
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
        return emit({"ok": True, "applied": 0, "matches": [], "backup": None, "dryRun": False, "warnings": []}, EXIT_OK)
    try:
        write_with_backup(path, payload, backup=not no_backup)
    except OSError as e:
        return emit(err_json("write failed: %s" % e, EXIT_ERROR), EXIT_ERROR)
    if verbose:
        log("[verbose] wrote %d bytes; backup=%s" % (len(payload), (path + ".orig") if not no_backup else None))
    warnings = [{"label": l} for l in unmatched] if unmatched else []
    return emit({"ok": True, "applied": sum(1 for c in counts if c > 0),
                 "matches": [{"label": ops[i]["label"], "count": counts[i]} for i in range(len(ops))],
                 "backup": (path + ".orig") if not no_backup else None,
                 "dryRun": False, "warnings": warnings}, EXIT_UNMATCHED if unmatched else EXIT_OK)


def cmd_convert(path, to, from_enc, bom_policy, line_ending, dry_run, no_backup):
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
                     "lineEnding": line_ending, "backup": None}, EXIT_OK)
    try:
        write_with_backup(path, payload, backup=not no_backup)
    except OSError as e:
        return emit(err_json("write failed: %s" % e, EXIT_ERROR), EXIT_ERROR)
    return emit({"ok": True, "from": src_enc, "to": to, "bom": target_bom,
                 "lineEnding": line_ending, "dryRun": False,
                 "backup": (path + ".orig") if not no_backup else None}, EXIT_OK)


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
    if damaged:
        action = "file appears damaged; restore from backup (e.g. <file>.orig) if available and re-edit via enc replace"
    else:
        action = "no damage detected; safe to proceed (run `enc cleanup <file>` to remove the backup snapshot)"
    return emit({"ok": True, "file": os.path.abspath(path), "encoding": enc, "confidence": det["confidence"],
                 "fffdCount": fffd_count, "fffdSamples": fffd_samples, "qCount": q_count, "qRatio": round(q_ratio, 6),
                 "mojibakePatterns": mojibake, "damaged": damaged, "suggestedAction": action}, EXIT_OK)


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


def _probe_runtime(cmd):
    """found = 命令存在于 PATH（shutil.which）；usable = 实际执行 --version 成功。"""
    found = shutil.which(cmd[0]) is not None
    try:
        p = subprocess.run(cmd + ["--version"], capture_output=True, timeout=15)
        out = (p.stdout or b"").decode("utf-8", errors="replace") + (p.stderr or b"").decode("utf-8", errors="replace")
        ok = p.returncode == 0 and bool(out.strip())
        return {"found": found, "usable": ok, "version": (out.strip().splitlines()[0] if ok and out.strip() else None)}
    except (OSError, subprocess.TimeoutExpired):
        return {"found": found, "usable": False, "version": None}


def cmd_selfcheck():
    runtimes = {}
    for name, cmd in [("python3", ["python3"]), ("python", ["python"]), ("py -3", ["py", "-3"]),
                      ("uv", ["uv", "run", "--no-project", "python"]), ("node", ["node"])]:
        runtimes[name] = _probe_runtime(cmd)
    selected = None
    for name in ("python3", "python", "py -3", "uv", "node"):
        if runtimes[name]["usable"]:
            selected = name
            break
    return emit({"ok": selected is not None, "runtimes": runtimes, "selectedRuntime": selected,
                 "message": "no usable runtime; install Python or Node, or use --runtime to force" if selected is None else None},
                EXIT_OK)


USAGE = """usage: enc <subcommand> [options]

subcommands:
  detect <file>
  read <file> [--out <utf8-path>] [--encoding <enc>]
  replace <file> <ops-json> | --from-file <ops-file>
          [--encoding <enc>] [--dry-run] [--no-backup] [--verbose] [--force]
  convert <file> --to <enc> [--from <enc>] [--bom add|remove|keep]
          [--line-ending keep|crlf|lf] [--dry-run] [--no-backup]
  verify <file> [--encoding <enc>]
  cleanup <file>
  selfcheck
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


def main(argv):
    if not argv:
        sys.stderr.write(USAGE)
        return EXIT_ERROR
    sub = argv[0]
    args = argv[1:]
    if sub == "detect":
        if len(args) != 1:
            return emit(err_json("detect requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_detect(args[0])
    if sub == "read":
        args, out = take_option(args, "--out", True)
        args, enc = take_option(args, "--encoding", True)
        if len(args) != 1:
            return emit(err_json("read requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_read(args[0], out, enc)
    if sub == "replace":
        args, ff = take_option(args, "--from-file", True)
        args, enc = take_option(args, "--encoding", True)
        args, dry = take_option(args, "--dry-run")
        args, nb = take_option(args, "--no-backup")
        args, verb = take_option(args, "--verbose")
        args, force = take_option(args, "--force")
        if ff is not None:
            if len(args) != 1:
                return emit(err_json("replace --from-file requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
            return cmd_replace(args[0], None, ff, enc, dry is not None, nb is not None, verb is not None, force is not None)
        if len(args) != 2:
            return emit(err_json("replace requires <file> <ops-json> or --from-file <ops-file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_replace(args[0], args[1], None, enc, dry is not None, nb is not None, verb is not None, force is not None)
    if sub == "convert":
        args, to = take_option(args, "--to", True)
        args, frm = take_option(args, "--from", True)
        args, bom = take_option(args, "--bom", True)
        args, le = take_option(args, "--line-ending", True)
        args, dry = take_option(args, "--dry-run")
        args, nb = take_option(args, "--no-backup")
        if len(args) != 1:
            return emit(err_json("convert requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        if bom is not None and bom not in ("add", "remove", "keep"):
            return emit(err_json("--bom must be add|remove|keep", EXIT_ERROR), EXIT_ERROR)
        if le is not None and le not in ("keep", "crlf", "lf"):
            return emit(err_json("--line-ending must be keep|crlf|lf", EXIT_ERROR), EXIT_ERROR)
        return cmd_convert(args[0], to, frm, bom or "keep", le or "keep", dry is not None, nb is not None)
    if sub == "verify":
        args, enc = take_option(args, "--encoding", True)
        if len(args) != 1:
            return emit(err_json("verify requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_verify(args[0], enc)
    if sub == "cleanup":
        if len(args) != 1:
            return emit(err_json("cleanup requires exactly one <file>", EXIT_ERROR), EXIT_ERROR)
        return cmd_cleanup(args[0])
    if sub == "selfcheck":
        return cmd_selfcheck()
    return emit(err_json("unknown subcommand: %s" % sub, EXIT_ERROR), EXIT_ERROR)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))