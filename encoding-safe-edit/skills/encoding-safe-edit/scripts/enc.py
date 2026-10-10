#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""encoding-safe-edit skill 主实现（Python，首选运行时）。

子命令：detect / find / read / replace / insert / convert / verify / cleanup / gc
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
        # newline="" disables \n -> \r\n translation on Windows (byte-exact stdout/stderr)
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

# create（新建文件）与载体（sidecar）契约常量（决策文档 D-02..D-05 / D-09..D-11）
SENTINEL = "__ENC_PLACEHOLDER__"
CREATE_HINT_EXISTS = "create 仅用于新建文件；修改既有文件请用 enc replace / enc insert"
CREATE_HINT_PARENT = "create 不会创建目录；请先创建父目录"
CREATE_HINT_OPTS = "create 仅接受 --line-ending / --bom / --dry-run"
SIDE_HINT_UTF16 = "载体以 UTF-16 BOM 开头；请另存为 UTF-8（BOM 可选）后重试"
SIDE_HINT_UTF8 = "载体必须是 UTF-8；若以 GBK/ANSI 写入，请另存为 UTF-8（BOM 可选）后重试"

HINT_DUAL = "utf-8/gbk 双合法（写回须显式指定编码）"
HINT_NUL = "包含大量 NUL 字节；可能是无 BOM 的 UTF-16/UTF-32"
HINT_BOM_CORRUPT = "带 BOM 但正文无法严格解码，可能已损坏"
HINT_UTF32 = "检测到 UTF-32 BOM，但不受支持；请先用外部工具转码"


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
                mode = os.stat(path).st_mode & 0o7777
            except OSError:
                # 新文件（create 场景）：mkstemp 默认 0600 过窄，按进程 umask 推定常规权限
                um = os.umask(0)
                try:
                    mode = 0o666 & ~um
                finally:
                    os.umask(um)
            try:
                os.chmod(tmp, mode)
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
        "suggestedAction": "unknown：请询问",
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
            d["suggestedAction"] = "可用 replace" if bom_kind == "utf-8" else "可用 replace/convert"
        else:
            d["encoding"] = {"utf-8": "utf-8", "utf-16le": "utf-16le", "utf-16be": "utf-16be"}[bom_kind]
            d["confidence"] = "medium"
            d["decodeHints"] = [HINT_BOM_CORRUPT]
            d["suggestedAction"] = "可用 replace；请遵循项目约定"
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
            d["suggestedAction"] = "请用 replace/convert 并显式指定 --encoding"
        else:
            d["suggestedAction"] = "replace 可用；引入非 ASCII 时须显式指定编码"
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
            d["suggestedAction"] = "写回须显式指定编码（utf-8/gbk 双合法）；读取不受影响"
        else:
            d["confidence"] = "high"
            d["suggestedAction"] = "可用 replace"
        d["lineEnding"] = detect_line_ending(data.decode("utf-8", errors="strict"))
        d["fffdCount"] = data.decode("utf-8", errors="strict").count("\ufffd")
        if nul_heavy:
            d["confidence"] = "medium"
            d["suggestedAction"] = "请用 replace/convert 并显式指定 --encoding"
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
            d["suggestedAction"] = "请用 replace/convert 并显式指定 --encoding"
        else:
            d["suggestedAction"] = "可用 replace"
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
            d["suggestedAction"] = "请用 replace/convert 并显式指定 --encoding"
        else:
            d["suggestedAction"] = "可用 replace"
        return d
    # ⑦ unknown
    d["encoding"] = "unknown"
    d["confidence"] = "low"
    d["asciiOnly"] = False
    d["suggestedAction"] = "unknown：请询问"
    hints = []
    for c in HINT_CODECS:
        if strict_decode(data, c) is not None:
            hints.append("可能是 %s" % c)
    if nul_heavy:
        hints.append(HINT_NUL)
    d["decodeHints"] = hints
    return d


# ---------------------------------------------------------------- 写路径公共
def resolve_source_encoding(path, data, explicit, for_write=False):
    """返回 (encoding, bom_kind, decode_error) 或 (None, None, errmsg)。
    fail-closed 规则：unknown / NUL-heavy 未显式指定编码时，read/replace/convert 一律拒绝；
    for_write=True 时，双合法（medium）未显式指定编码也拒绝（写回编码决策缺失，禁止静默选择）。"""
    if explicit:
        enc = normalize_explicit(explicit)
        if enc is None:
            low = explicit.lower()
            if low in ("utf-16", "utf_16", "utf16"):
                return None, None, "编码 '%s' 有歧义；请使用 utf-16-le 或 utf-16-be" % explicit
            return None, None, "不支持编码 '%s'（UTF-32）；请先用外部工具转码" % explicit
        bom_kind, _ = bom_of(data)
        return enc, bom_kind, None
    det = detect_file(path)
    enc = det["encoding"]
    if enc == "unknown":
        return None, None, "编码未知；请显式指定 --encoding"
    if det["confidence"] == "medium" and HINT_NUL in det["decodeHints"]:
        return None, None, "疑似无 BOM 的 UTF-16/UTF-32（NUL 密集）；请显式指定 --encoding utf-16-le/be"
    if for_write and HINT_DUAL in det["decodeHints"]:
        return None, None, "双合法文件（utf-8/gbk）；写入时必须显式指定 --encoding"
    bom_kind, _ = bom_of(data)
    return enc, bom_kind, None


def check_write_encoding_decision(out_enc, text):
    """写路径编码决策检查：ascii 文件将引入非 ASCII 时 fail-closed（禁止静默选编码）。"""
    if out_enc == "ascii" and any(ord(c) > 127 for c in text):
        return "ascii 文件将引入非 ASCII 内容（写回编码未决）；请按项目约定显式指定 --encoding（如 gbk / utf-8）"
    return None


def read_utf8_sidecar(path, label):
    """读取 UTF-8 侧面文件（ops / pattern 载体）→ (text, err, hint)。

    契约（决策文档 D-09 / D-10 / D-11）：
      - 允许并剥离**开头一个** UTF-8 BOM（EF BB BF）；中段 U+FEFF 保留。
      - 严格 UTF-8 解码：非法字节 fail-closed（不猜测 GBK/ANSI），返回可执行 hint。
      - 目标必须是常规文件（缺失 / 目录 / 特殊文件 → err）。
    """
    if not is_regular_file(path):
        return None, "无法读取 %s：不是常规文件：%s" % (label, path), None
    try:
        raw = read_bytes(path)
    except OSError as e:
        return None, "无法读取 %s：%s" % (label, e), None
    if raw.startswith(codecs.BOM_UTF8):
        raw = raw[3:]
    try:
        return raw.decode("utf-8"), None, None
    except UnicodeDecodeError as e:
        hint = SIDE_HINT_UTF16 if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else SIDE_HINT_UTF8
        return None, "%s 不是合法 UTF-8：%s" % (label, e), hint


def load_ops(ops_arg, from_file):
    if from_file:
        if not os.path.isfile(from_file):
            return None, "ops 载体文件不存在：%s" % from_file, None
        raw, rerr, rhint = read_utf8_sidecar(from_file, "ops 载体")
        if rerr:
            return None, rerr, rhint
    else:
        raw = ops_arg
    try:
        ops = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, "ops JSON 解析错误：%s" % e, None
    if not isinstance(ops, list):
        return None, "ops 必须是 JSON 数组", None
    cleaned = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or "search" not in op or not isinstance(op["search"], str) or op["search"] == "":
            return None, "ops[%d] 必须含非空字符串 'search'" % i, None
        if "replace" in op and not isinstance(op["replace"], str):
            return None, "ops[%d].replace 必须是字符串" % i, None
        if "label" in op and not isinstance(op["label"], str):
            return None, "ops[%d].label 必须是字符串" % i, None
        cleaned.append({
            "search": op["search"],
            "replace": op.get("replace", ""),
            "label": op.get("label", "op%d" % (i + 1)),
        })
    return cleaned, None, None


def load_insert_ops(ops_arg, from_file):
    """解析 insert ops（JSON 数组）。校验 anchor/text/where/occurrence/trim/label。
    返回 (ops, err, hint)；fail-closed：任一字段非法 → err（hint 仅在载体解码失败时非空）。"""
    if from_file:
        if not os.path.isfile(from_file):
            return None, "ops 载体文件不存在：%s" % from_file, None
        raw, rerr, rhint = read_utf8_sidecar(from_file, "ops 载体")
        if rerr:
            return None, rerr, rhint
    else:
        raw = ops_arg
    try:
        ops = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, "ops JSON 解析错误：%s" % e, None
    if not isinstance(ops, list):
        return None, "ops 必须是 JSON 数组", None
    cleaned = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            return None, "ops[%d] 必须是 JSON 对象" % i, None
        if "anchor" not in op or not isinstance(op["anchor"], str) or op["anchor"] == "":
            return None, "ops[%d] 必须含非空字符串 'anchor'" % i, None
        if "\r" in op["anchor"] or "\n" in op["anchor"]:
            return None, "ops[%d].anchor 不得包含换行" % i, None
        if "text" not in op or not isinstance(op["text"], str):
            return None, "ops[%d] 必须含字符串 'text'" % i, None
        where = op.get("where", "before")
        if where not in ("before", "after"):
            return None, "ops[%d].where 必须是 'before'|'after'" % i, None
        occurrence = op.get("occurrence")
        if occurrence is not None:
            if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence <= 0:
                return None, "ops[%d].occurrence 必须是正整数" % i, None
        trim = op.get("trim", False)
        if not isinstance(trim, bool):
            return None, "ops[%d].trim 必须是布尔值" % i, None
        if "label" in op and not isinstance(op["label"], str):
            return None, "ops[%d].label 必须是字符串" % i, None
        cleaned.append({
            "anchor": op["anchor"],
            "text": op["text"],
            "where": where,
            "occurrence": occurrence,
            "trim": trim,
            "label": op.get("label", "op%d" % (i + 1)),
        })
    return cleaned, None, None


def apply_ops(text, ops):
    """在解码后文本上应用 ops；返回 (new_text, counts, whole_text_mode) 或 (None, None, "error: ...")。
    多行 op（search/replace 含换行）在 mixed 行尾文件上无法保证"逐行保留原行尾"→ fail-closed。"""
    counts = [0] * len(ops)
    whole = any(("\n" in normalize_lf(o["search"])) or ("\n" in normalize_lf(o["replace"])) for o in ops)
    if whole:
        if detect_line_ending(text) == "mixed":
            return None, None, "混合行尾文件不支持多行 op（fail-closed）；请先统一行尾"
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


def cmd_find(path, pattern, pattern_file, explicit, ignore_case, max_count, verbose=False, regex=False):
    if pattern is None:
        if pattern_file is None:
            return emit(err_json("find 需要 pattern 或 --pattern-file", EXIT_ERROR), EXIT_ERROR)
        pattern, perr, phint = read_utf8_sidecar(pattern_file, "pattern 载体")
        if perr:
            return emit(err_json(perr, EXIT_ERROR, phint), EXIT_ERROR)
        pattern = re.sub(r"(?:\r\n|\r|\n)$", "", pattern, count=1)
    if not pattern:
        return emit(err_json("模式为空", EXIT_ERROR), EXIT_ERROR)
    if not is_regular_file(path):
        return emit(err_json("不是常规文件：%s" % path, EXIT_ERROR), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO 错误：%s" % e, EXIT_ERROR), EXIT_ERROR)
    enc, bom, de = resolve_source_encoding(path, data, explicit)
    if de:
        return emit(err_json(de, EXIT_ERROR, "请用 --encoding 显式指定文件编码"), EXIT_ERROR)
    res = decode_with_bom(data, enc)
    if res is None:
        return emit(err_json("按 %s 严格解码失败" % enc, EXIT_ERROR), EXIT_ERROR)
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
    matches = []
    total = 0
    if regex:
        flags = re.MULTILINE | (re.IGNORECASE if ignore_case else 0)
        try:
            rx = re.compile(normalize_lf(pattern), flags)
        except re.error as e:
            return emit(err_json("正则表达式非法：%s" % e, EXIT_ERROR), EXIT_ERROR)
        for m in rx.finditer(work):
            total += 1
            if total <= max_count:
                line_no, col, row_text = _locate(m.start(), starts, rows)
                matches.append({
                    "line": line_no,
                    "col": col,
                    "text": _clip(row_text, 200),
                    "snippet": _clip(row_text.strip(), 200),
                })
    else:
        if ignore_case:
            search, orig_idx = _build_fold_map(work)
            pat = normalize_lf(pattern).casefold()
            if not pat:
                return emit(err_json("折叠后模式为空", EXIT_ERROR), EXIT_ERROR)
            step = len(pat)
        else:
            search = work
            orig_idx = None
            pat = normalize_lf(pattern)
            step = len(pat)
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
        return emit(err_json("不是常规文件：%s" % path, EXIT_ERROR), EXIT_ERROR)
    try:
        d = detect_file(path)
    except OSError as e:
        return emit(err_json("IO 错误：%s" % e, EXIT_ERROR), EXIT_ERROR)
    return emit(d, EXIT_OK)


def cmd_read(path, out, explicit, line=None, from_line=None, to_line=None):
    if not is_regular_file(path):
        return emit(err_json("不是常规文件：%s" % path, EXIT_ERROR), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO 错误：%s" % e, EXIT_ERROR), EXIT_ERROR)
    enc, bom, de = resolve_source_encoding(path, data, explicit)
    if de:
        return emit(err_json(de, EXIT_ERROR, "请用 --encoding 显式指定文件编码"), EXIT_ERROR)
    res = decode_with_bom(data, enc)
    if res is None:
        return emit(err_json("按 %s 严格解码失败" % enc, EXIT_ERROR), EXIT_ERROR)
    text, bom_kind = res
    if line is None and from_line is None and to_line is None:
        if out:
            try:
                with open(out, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
            except OSError as e:
                return emit(err_json("无法写出 --out 文件：%s" % e, EXIT_ERROR), EXIT_ERROR)
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
        return emit(err_json("空文件没有可读取的行", EXIT_ERROR), EXIT_ERROR)
    if line is not None:
        if line > total:
            return emit(err_json("行号 %d 超出范围（文件共 %d 行）" % (line, total), EXIT_ERROR), EXIT_ERROR)
        start_idx = line - 1
        end_idx = line
        from_line_eff = line
        to_line_eff = line
    else:
        if from_line > total:
            return emit(err_json("起始行 %d 超出范围（文件共 %d 行）" % (from_line, total), EXIT_ERROR), EXIT_ERROR)
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
            return emit(err_json("无法写出 --out 文件：%s" % e, EXIT_ERROR), EXIT_ERROR)
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
        return emit(err_json("不是常规文件：%s" % path, EXIT_ERROR), EXIT_ERROR)
    ops, oerr, ohint = load_ops(ops_arg, from_file)
    if oerr:
        return emit(err_json(oerr, EXIT_ERROR, ohint), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO 错误：%s" % e, EXIT_ERROR), EXIT_ERROR)
    enc, bom, de = resolve_source_encoding(path, data, explicit, for_write=True)
    if de:
        return emit(err_json(de, EXIT_ERROR, "请用 --encoding 显式指定文件编码"), EXIT_ERROR)
    res = decode_with_bom(data, enc)
    if res is None:
        return emit(err_json("按 %s 严格解码失败（fail-closed；未写盘）" % enc, EXIT_ERROR), EXIT_ERROR)
    text, bom_kind = res
    new_text, counts, whole_mode = apply_ops(text, ops)
    if new_text is None:
        return emit(err_json(whole_mode, EXIT_ERROR), EXIT_ERROR)
    unmatched = [ops[i]["label"] for i in range(len(ops)) if counts[i] == 0]
    if unmatched and not force:
        return emit(err_json("%d 条 op 未命中；未写盘（fail-closed）" % len(unmatched), EXIT_UNMATCHED,
                             "如需应用已命中项，可使用 --force"), EXIT_UNMATCHED)
    if dry_run:
        preview = [{"label": ops[i]["label"], "count": counts[i]} for i in range(len(ops))]
        return emit({"ok": True, "dryRun": True, "applied": sum(1 for c in counts if c > 0),
                     "matches": preview, "unmatched": unmatched, "warnings": []}, EXIT_UNMATCHED if unmatched else EXIT_OK)
    out_enc = enc
    out_bom = bom_kind if bom_kind != "none" else "none"
    _cd = check_write_encoding_decision(out_enc, new_text)
    if _cd:
        return emit(err_json(_cd, EXIT_ERROR, "本工具不做编码假设；请按项目约定显式指定 --encoding"), EXIT_ERROR)
    payload = encode_with_bom(new_text, out_enc, out_bom)
    if payload is None:
        return emit(err_json("按 %s 严格编码失败（fail-closed；未写盘）" % out_enc, EXIT_ERROR), EXIT_ERROR)
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
        return emit(err_json("写入失败：%s" % e, EXIT_ERROR), EXIT_ERROR)
    backup_final, cleanup, damaged = post_write_cleanup(path, new_text, out_enc, keep_backup)
    if verbose:
        log("[verbose] wrote %d bytes; backup=%s; cleanup=%s" % (len(payload), backup_final, cleanup))
    warnings = [{"label": l} for l in unmatched] if unmatched else []
    return emit({"ok": True, "applied": sum(1 for c in counts if c > 0),
                 "matches": [{"label": ops[i]["label"], "count": counts[i]} for i in range(len(ops))],
                 "backup": backup_final, "cleanup": cleanup, "damaged": damaged,
                 "dryRun": False, "warnings": warnings}, EXIT_UNMATCHED if unmatched else EXIT_OK)


def cmd_insert(path, ops_arg, from_file, explicit, dry_run, keep_backup, verbose, force):
    if not is_regular_file(path):
        return emit(err_json("不是常规文件：%s" % path, EXIT_ERROR), EXIT_ERROR)
    ops, oerr, ohint = load_insert_ops(ops_arg, from_file)
    if oerr:
        return emit(err_json(oerr, EXIT_ERROR, ohint), EXIT_ERROR)
    if len(ops) == 0:
        return emit({"ok": True, "applied": 0, "matches": [], "backup": None, "cleanup": None,
                     "dryRun": False, "warnings": []}, EXIT_OK)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO 错误：%s" % e, EXIT_ERROR), EXIT_ERROR)
    enc, bom, de = resolve_source_encoding(path, data, explicit, for_write=True)
    if de:
        return emit(err_json(de, EXIT_ERROR, "请用 --encoding 显式指定文件编码"), EXIT_ERROR)
    res = decode_with_bom(data, enc)
    if res is None:
        return emit(err_json("按 %s 严格解码失败（fail-closed；未写盘）" % enc, EXIT_ERROR), EXIT_ERROR)
    text, bom_kind = res
    line_end = detect_line_ending(text)
    if line_end == "mixed":
        return emit(err_json("insert 不支持混合行尾；请先统一（fail-closed；未写盘）", EXIT_ERROR), EXIT_ERROR)
    end = "\r\n" if line_end == "crlf" else "\r" if line_end == "cr" else "\n"
    rows = split_keepends(text)
    if rows == []:
        unmatched = [o["label"] for o in ops]
        if not force:
            return emit(err_json("%d 条 op 未命中；未写盘（fail-closed）" % len(unmatched), EXIT_UNMATCHED,
                                 "如需应用已命中项，可使用 --force"), EXIT_UNMATCHED)
        return emit({"ok": True, "applied": 0, "matches": [], "backup": None, "cleanup": None,
                     "dryRun": False, "warnings": [{"label": l} for l in unmatched]}, EXIT_UNMATCHED)
    applied = []
    unmatched = []
    ambiguous = None
    for o in ops:
        t = normalize_lf(o["text"])
        parts = t.split("\n")
        matches = []
        for i in range(len(rows)):
            c = rows[i][0].strip() if o["trim"] else rows[i][0]
            a = o["anchor"].strip() if o["trim"] else o["anchor"]
            if c == a:
                matches.append(i)
        if len(matches) == 0:
            unmatched.append(o["label"])
        elif len(matches) > 1 and o["occurrence"] is None:
            ambiguous = ambiguous or o["label"]
        elif o["occurrence"] is not None and o["occurrence"] > len(matches):
            unmatched.append(o["label"])
        else:
            idx = matches[o["occurrence"] - 1] if o["occurrence"] is not None else matches[0]
            applied.append((idx, o["where"], parts, o["label"]))
    if ambiguous is not None:
        return emit(err_json("锚点不唯一（多处命中且未指定 occurrence）：%s（fail-closed；未写盘）" % ambiguous, EXIT_ERROR), EXIT_ERROR)
    if unmatched and not force:
        return emit(err_json("%d 条 op 未命中；未写盘（fail-closed）" % len(unmatched), EXIT_UNMATCHED,
                             "如需应用已命中项，可使用 --force"), EXIT_UNMATCHED)
    seen = {}
    for idx, where, parts, label in applied:
        if idx in seen:
            return emit(err_json("同一原始行上存在冲突插入（第 %d 行）；请拆分为多次调用（fail-closed；未写盘）" % (idx + 1), EXIT_ERROR), EXIT_ERROR)
        seen[idx] = label
    if dry_run:
        return emit({"ok": True, "dryRun": True, "applied": len(applied),
                     "matches": [{"label": label, "line": idx + 1, "where": where} for idx, where, parts, label in applied],
                     "unmatched": unmatched, "warnings": []}, EXIT_UNMATCHED if unmatched else EXIT_OK)
    work = list(rows)
    for idx, where, parts, label in sorted([(i, w, p, l) for i, w, p, l in applied], key=lambda t: t[0], reverse=True):
        if where == "after" and work[idx][1] == "":
            work[idx] = (work[idx][0], end)
        k = 0
        for part in parts:
            if where == "before":
                work.insert(idx + k, (part, end))
            else:
                work.insert(idx + 1 + k, (part, end))
            k += 1
    new_text = "".join(content + term for content, term in work)
    out_enc = enc
    out_bom = bom_kind if bom_kind != "none" else "none"
    _cd = check_write_encoding_decision(out_enc, new_text)
    if _cd:
        return emit(err_json(_cd, EXIT_ERROR, "本工具不做编码假设；请按项目约定显式指定 --encoding"), EXIT_ERROR)
    payload = encode_with_bom(new_text, out_enc, out_bom)
    if payload is None:
        return emit(err_json("按 %s 严格编码失败（fail-closed；未写盘）" % out_enc, EXIT_ERROR), EXIT_ERROR)
    if verbose:
        verbose_hex(data, "original")
        verbose_hex(payload, "result")
    try:
        write_with_backup(path, payload, backup=True)
    except OSError as e:
        return emit(err_json("写入失败：%s" % e, EXIT_ERROR), EXIT_ERROR)
    backup_final, cleanup, damaged = post_write_cleanup(path, new_text, out_enc, keep_backup)
    warnings = [{"label": l} for l in unmatched] if unmatched else []
    return emit({"ok": True, "applied": len(applied),
                 "matches": [{"label": label, "line": idx + 1, "where": where} for idx, where, parts, label in applied],
                 "backup": backup_final, "cleanup": cleanup, "damaged": damaged,
                 "dryRun": False, "warnings": warnings}, EXIT_UNMATCHED if unmatched else EXIT_OK)


def cmd_convert(path, to, from_enc, bom_policy, line_ending, dry_run, keep_backup):
    if not is_regular_file(path):
        return emit(err_json("不是常规文件：%s" % path, EXIT_ERROR), EXIT_ERROR)
    if not to:
        return emit(err_json("必须指定 --to <encoding>", EXIT_ERROR), EXIT_ERROR)
    to_orig = to
    to = normalize_explicit(to)
    if to is None:
        low = to_orig.lower()
        if low in ("utf-16", "utf_16", "utf16"):
            return emit(err_json("--to %s 有歧义；请使用 utf-16-le 或 utf-16-be" % to_orig, EXIT_ERROR), EXIT_ERROR)
        return emit(err_json("不支持 --to %s（UTF-32）；请先用外部工具转码" % to_orig, EXIT_ERROR), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO 错误：%s" % e, EXIT_ERROR), EXIT_ERROR)
    src_enc, src_bom, de = resolve_source_encoding(path, data, from_enc, for_write=True)
    if de:
        return emit(err_json(de, EXIT_ERROR, "请用 --from 显式指定源编码"), EXIT_ERROR)
    res = decode_with_bom(data, src_enc)
    if res is None:
        return emit(err_json("按 %s 严格解码失败（fail-closed；未写盘）" % src_enc, EXIT_ERROR), EXIT_ERROR)
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
        return emit(err_json("按 %s 严格编码失败（fail-closed；未写盘）" % to, EXIT_ERROR), EXIT_ERROR)
    if dry_run:
        return emit({"ok": True, "dryRun": True, "from": src_enc, "to": to, "bom": target_bom,
                     "lineEnding": line_ending, "backup": None, "cleanup": None}, EXIT_OK)
    try:
        write_with_backup(path, payload, backup=True)
    except OSError as e:
        return emit(err_json("写入失败：%s" % e, EXIT_ERROR), EXIT_ERROR)
    backup_final, cleanup, damaged = post_write_cleanup(path, text, to, keep_backup)
    return emit({"ok": True, "from": src_enc, "to": to, "bom": target_bom,
                 "lineEnding": line_ending, "dryRun": False,
                 "backup": backup_final, "cleanup": cleanup, "damaged": damaged}, EXIT_OK)



def cmd_create(path, line_ending, bom, dry_run):
    """新建文件：只写入固定 ASCII 哨兵（锚点），不做内容初始化（决策文档 D-02..D-05）。

    护栏：目标必须不存在（与 replace/insert 的“必须存在”互为对偶）；父目录必须存在；
    无 .orig（新文件没有写前状态）；写前验证通过才落盘；任何失败都不产生文件。
    """
    if os.path.lexists(path):
        return emit(err_json("目标已存在：%s" % path, EXIT_ERROR, CREATE_HINT_EXISTS), EXIT_ERROR)
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        return emit(err_json("父目录不存在：%s" % parent, EXIT_ERROR, CREATE_HINT_PARENT), EXIT_ERROR)
    end = "\r\n" if line_ending == "crlf" else "\n"
    if bom in ("utf-16-le", "utf-16-be"):
        enc = bom
        bom_kind = "utf-16le" if bom == "utf-16-le" else "utf-16be"
    else:
        enc = "utf-8"
        bom_kind = "none" if bom == "none" else "utf-8"
    text = SENTINEL + end
    payload = encode_with_bom(text, enc, bom_kind)
    if payload is None:
        return emit(err_json("按 %s 严格编码失败（fail-closed；未写盘）" % enc, EXIT_ERROR), EXIT_ERROR)
    rt = decode_with_bom(payload, enc)
    if rt is None or rt[0] != text:
        return emit(err_json("写前校验失败（fail-closed；未写盘）", EXIT_ERROR), EXIT_ERROR)
    out = {"ok": True, "created": not dry_run, "file": os.path.abspath(path), "sentinel": SENTINEL,
           "encoding": enc, "bom": bom_kind, "lineEnding": line_ending, "bytes": len(payload),
           "dryRun": bool(dry_run), "backup": None, "cleanup": None, "damaged": verify_text(text, enc)["damaged"]}
    if dry_run:
        return emit(out, EXIT_OK)
    try:
        atomic_write(path, payload)
    except OSError as e:
        return emit(err_json("写入失败：%s" % e, EXIT_ERROR), EXIT_ERROR)
    return emit(out, EXIT_OK)


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
        return emit(err_json("不是常规文件：%s" % path, EXIT_ERROR), EXIT_ERROR)
    try:
        data = read_bytes(path)
    except OSError as e:
        return emit(err_json("IO 错误：%s" % e, EXIT_ERROR), EXIT_ERROR)
    det = detect_file(path)
    enc = explicit or det["encoding"]
    if enc == "unknown":
        return emit(err_json("编码未知；无法验证", EXIT_ERROR, "请指定 --encoding"), EXIT_ERROR)
    res = decode_with_bom(data, enc)
    if res is None:
        return emit(err_json("按 %s 严格解码失败；无法验证" % enc, EXIT_ERROR), EXIT_ERROR)
    text, _ = res
    v = verify_text(text, enc)
    if v["damaged"]:
        action = "文件疑似损坏；如有备份（如 <file>.orig）请先恢复，再用 enc replace 重新编辑"
    else:
        base = "未检测到损坏；可以继续"
        if os.path.isfile(path + ".orig"):
            action = base + "（保留了备份快照；如需删除请运行 `enc cleanup <file>`）"
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
        return emit(err_json("不是常规文件：%s" % path, EXIT_ERROR), EXIT_ERROR)
    backup = path + ".orig"
    if not os.path.lexists(backup):
        return emit({"ok": True, "file": os.path.abspath(path), "removed": None}, EXIT_OK)
    if not os.path.isfile(backup):
        return emit(err_json("备份路径不是常规文件：%s" % backup, EXIT_ERROR), EXIT_ERROR)
    try:
        os.remove(backup)
    except OSError as e:
        return emit(err_json("清理失败：%s" % e, EXIT_ERROR), EXIT_ERROR)
    return emit({"ok": True, "file": os.path.abspath(path), "removed": os.path.abspath(backup)}, EXIT_OK)


def cmd_gc(path, all_flag):
    """gc <dir> [--all]：维护命令。默认删除孤儿 .orig（target 缺失）；--all 递归删除全部。"""
    if not os.path.isdir(path):
        return emit(err_json("不是目录：%s" % path, EXIT_ERROR), EXIT_ERROR)
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


import argparse


def _emit_usage_error(message):
    """CLI 参数错误：JSON 错误包 + exit 1（保持 0/1/2 契约）。"""
    return emit(err_json("参数错误：%s（详见 enc --help）" % message, EXIT_ERROR), EXIT_ERROR)


class _Parser(argparse.ArgumentParser):
    """argparse 包装：用法错误改为 JSON 错误包，退出码统一为 1。"""

    def error(self, message):
        emit(err_json("参数错误：%s（详见 enc --help）" % message, EXIT_ERROR), EXIT_ERROR)
        raise SystemExit(EXIT_ERROR)


def _build_parser():
    p = _Parser(
        prog="enc",
        description="encoding-safe-edit：文本文件编码安全的读 / 写 / 改（fail-closed、写前备份、写后验证）。",
        epilog="退出码：0 成功；1 错误（参数错误 / IO / fail-closed）；2 业务性预期分支（未命中）。",
    )
    p.add_argument("--version", action="version", version="enc 1.1.0 (encoding-safe-edit)")
    sub = p.add_subparsers(dest="cmd", metavar="<subcommand>")

    s = sub.add_parser("detect", help="检测文件编码 / 置信度 / BOM / 行尾")
    s.add_argument("file", metavar="<file>", help="目标文件路径")

    s = sub.add_parser("find", help="定位（默认字面匹配；--regex 启用正则）")
    s.add_argument("file", metavar="<file>", help="目标文件路径")
    s.add_argument("pattern", nargs="?", metavar="<pattern>", help="搜索串（中文 / 特殊字符请用 --pattern-file）")
    s.add_argument("--pattern-file", dest="pattern_file", metavar="<utf8-file>", help="从 UTF-8 文件读取模式（与 <pattern> 二选一）")
    s.add_argument("--encoding", metavar="<enc>", help="显式指定源文件编码")
    s.add_argument("--ignore-case", dest="ignore_case", action="store_true", help="忽略大小写")
    s.add_argument("--regex", action="store_true", help="把模式按正则表达式解释（非法正则 fail-closed）")
    s.add_argument("--max-count", dest="max_count", type=int, default=100, metavar="N", help="最多返回 N 条匹配（默认 100）")
    s.add_argument("--verbose", action="store_true", help="输出诊断日志到 stderr")

    s = sub.add_parser("read", help="按原编码解码输出（stdout 或 --out）")
    s.add_argument("file", metavar="<file>", help="目标文件路径")
    s.add_argument("--out", metavar="<utf8-path>", help="写 UTF-8 到指定文件（机器消费场景）")
    s.add_argument("--encoding", metavar="<enc>", help="显式指定源文件编码（歧义时必填）")
    s.add_argument("--line", type=int, metavar="N", help="只输出第 N 行")
    s.add_argument("--from-line", dest="from_line", type=int, metavar="N", help="起始行（含；与 --line 互斥）")
    s.add_argument("--to-line", dest="to_line", type=int, metavar="M", help="结束行（含）")

    s = sub.add_parser("create", help="创建仅含哨兵行的新文件（随后用 insert / replace 写入内容）")
    s.add_argument("file", metavar="<file>", help="目标文件路径")
    s.add_argument("--line-ending", dest="line_ending", choices=["lf", "crlf"], default="lf", help="行尾风格（默认 lf）")
    s.add_argument("--bom", choices=["none", "utf-8", "utf-16-le", "utf-16-be"], default="none", help="BOM 策略：none / utf-8 / utf-16-le / utf-16-be（默认 none）")
    s.add_argument("--dry-run", dest="dry_run", action="store_true", help="只预览不写盘（未命中先 exit 2）")

    for _name, _verb in (("replace", "字面替换"), ("insert", "按锚点整行插入")):
        s = sub.add_parser(_name, help=_verb + "（写路径：内置检测 / 备份 / 写后验证）")
        s.add_argument("file", metavar="<file>", help="目标文件路径")
        s.add_argument("ops_json", nargs="?", metavar="<ops-json>", help="内联 ops JSON（与 --from-file 二选一）")
        s.add_argument("--from-file", dest="from_file", metavar="<ops-file>", help="从 UTF-8 载体文件读取 ops")
        s.add_argument("--encoding", metavar="<enc>", help="显式指定源文件编码（歧义时必填）")
        s.add_argument("--dry-run", dest="dry_run", action="store_true", help="只预览不写盘（未命中先 exit 2）")
        s.add_argument("--keep-backup", dest="keep_backup", action="store_true", help="保留 .orig 单步快照（默认写后验证通过即删）")
        s.add_argument("--verbose", action="store_true", help="输出匹配明细 / 诊断日志")
        s.add_argument("--force", action="store_true", help="未命中项不阻塞；应用已命中项")

    s = sub.add_parser("convert", help="转码（保留 BOM / 行尾策略）")
    s.add_argument("file", metavar="<file>", help="目标文件路径")
    s.add_argument("--to", required=True, metavar="<enc>", help="目标编码（必填）")
    s.add_argument("--from", dest="from_enc", metavar="<enc>", help="源编码（缺省时按检测结果）")
    s.add_argument("--bom", choices=["add", "remove", "keep"], default="keep", help="BOM 策略：add / remove / keep（默认 keep）")
    s.add_argument("--line-ending", dest="line_ending", choices=["keep", "crlf", "lf"], default="keep", help="行尾策略：keep / lf / crlf（默认 keep）")
    s.add_argument("--dry-run", dest="dry_run", action="store_true", help="只预览不写盘")
    s.add_argument("--keep-backup", dest="keep_backup", action="store_true", help="保留 .orig 单步快照（默认写后验证通过即删）")

    s = sub.add_parser("verify", help="扫描 U+FFFD / 乱码特征（只读）")
    s.add_argument("file", metavar="<file>", help="目标文件路径")
    s.add_argument("--encoding", metavar="<enc>", help="显式指定源文件编码（歧义时必填）")

    s = sub.add_parser("cleanup", help="删除 <file>.orig 单步快照（维护）")
    s.add_argument("file", metavar="<file>", help="目标文件路径")

    s = sub.add_parser("gc", help="清理孤儿 .orig（维护）")
    s.add_argument("dir", metavar="<dir>", help="扫描目录")
    s.add_argument("--all", dest="all_flag", action="store_true", help="删除目录下全部 *.orig")

    return p
def main(argv):
    if "--no-backup" in argv:
        return emit(err_json("--no-backup 已移除：写路径恒先备份（底线不可关闭）", EXIT_ERROR), EXIT_ERROR)
    args = _build_parser().parse_args(argv)
    if args.cmd is None:
        return _emit_usage_error("缺少子命令，详见 enc --help")
    if args.cmd == "detect":
        return cmd_detect(args.file)
    if args.cmd == "find":
        if (args.pattern is None) == (args.pattern_file is None):
            return _emit_usage_error("find 需要 <pattern> 或 --pattern-file（二选一）")
        if args.max_count <= 0:
            return _emit_usage_error("--max-count 必须是正整数")
        if args.pattern_file is not None and not os.path.isfile(args.pattern_file):
            return emit(err_json("pattern 载体不存在：%s" % args.pattern_file, EXIT_ERROR), EXIT_ERROR)
        return cmd_find(args.file, args.pattern, args.pattern_file, args.encoding,
                        args.ignore_case, args.max_count, args.verbose, args.regex)
    if args.cmd == "read":
        if args.line is not None and (args.from_line is not None or args.to_line is not None):
            return _emit_usage_error("--line 不能与 --from-line/--to-line 组合使用")
        if (args.from_line is None) != (args.to_line is None):
            return _emit_usage_error("--from-line 与 --to-line 必须成对使用")
        for v in (args.line, args.from_line, args.to_line):
            if v is not None and v <= 0:
                return _emit_usage_error("行号必须是正整数")
        if args.from_line is not None and args.from_line > args.to_line:
            return _emit_usage_error("--from-line 必须 <= --to-line")
        return cmd_read(args.file, args.out, args.encoding, args.line, args.from_line, args.to_line)
    if args.cmd == "create":
        return cmd_create(args.file, args.line_ending, args.bom, args.dry_run)
    if args.cmd in ("replace", "insert"):
        if (args.ops_json is None) == (args.from_file is None):
            return _emit_usage_error("%s 需要 <ops-json> 或 --from-file（二选一）" % args.cmd)
        fn = cmd_replace if args.cmd == "replace" else cmd_insert
        return fn(args.file, args.ops_json, args.from_file, args.encoding,
                  args.dry_run, args.keep_backup, args.verbose, args.force)
    if args.cmd == "convert":
        return cmd_convert(args.file, args.to, args.from_enc, args.bom, args.line_ending,
                           args.dry_run, args.keep_backup)
    if args.cmd == "verify":
        return cmd_verify(args.file, args.encoding)
    if args.cmd == "cleanup":
        return cmd_cleanup(args.file)
    if args.cmd == "gc":
        return cmd_gc(args.dir, args.all_flag)
    return _emit_usage_error("未知子命令：%s" % args.cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))