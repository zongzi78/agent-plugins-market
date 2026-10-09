#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""change-backup：改前留痕底层能力（布局 A / 锚绑定 / 原子写入 / 自动裁剪）。

子命令：snapshot / list / restore / prune / selfcheck
退出码：0 成功；1 fail-closed；2 幂等命中（同刻同内容已存在）
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

VERSION = "1.0.0"
LAYOUT = "A"
KEEP = 10
ANCHOR_FILE = ".change-backup.anchor"
TS_FMT = "%Y%m%d-%H%M%S"
TS_RE = re.compile(r"^\d{8}-\d{6}(-\d{2})?$")
TMP_PREFIX = ".cb-tmp-"


class Fail(Exception):
    """fail-closed：任何不可继续的情况都在此抛出。"""

    def __init__(self, message, code=1, hint=None):
        Exception.__init__(self, message)
        self.message = message
        self.code = code
        self.hint = hint


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def emit_fail(exc):
    emit({"ok": False, "error": exc.message, "exitCode": exc.code, "hint": exc.hint})


def abspath(p):
    return os.path.abspath(os.path.expanduser(p))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def posix_rel(path, anchor):
    """path 相对 anchor 的 POSIX 路径；不在 anchor 之下时 fail-closed。"""
    try:
        rel = os.path.relpath(path, anchor)
    except ValueError:
        raise Fail("anchor 与 file 不在同一根下：%s" % path,
                   hint="请给出能覆盖该文件的 anchor（通常为该文件所在项目的根）")
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        raise Fail("file 不在 anchor 之下：%s" % path,
                   hint="一个工作空间只有一个 anchor；如需覆盖更大范围请由项目层一次性上移 anchor")
    return rel.replace(os.sep, "/")


def now_stamp(when=None):
    return time.strftime(TS_FMT, time.localtime(when))


def snapshot_entries(dirpath):
    """目录内布局 A 的快照文件，按文件名时间戳降序。"""
    d = Path(dirpath)
    if not d.is_dir():
        return []
    items = [p for p in d.iterdir() if p.is_file() and TS_RE.match(p.name)]
    return sorted(items, key=lambda p: p.name, reverse=True)
def write_atomic_text(path, text):
    """原子写入文本（UTF-8 无 BOM）。"""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=TMP_PREFIX, dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(path))
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def copy_verify(src, target):
    """把 src 内容原子写入 target：临时文件 → 校验字节数与 sha256 → rename。"""
    target = Path(target)
    fd, tmp = tempfile.mkstemp(prefix=TMP_PREFIX, dir=str(target.parent))
    try:
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            for block in iter(lambda: inp.read(65536), b""):
                out.write(block)
                digest.update(block)
                size += len(block)
            out.flush()
            os.fsync(out.fileno())
        if os.path.getsize(tmp) != size or digest.hexdigest() != sha256_file(tmp):
            raise Fail("快照校验失败（字节数或 sha256 不一致）：%s" % src)
        os.replace(tmp, str(target))
        tmp = None
        return size, digest.hexdigest()
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def read_anchor(store):
    p = Path(store) / ANCHOR_FILE
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8").strip()


def bind_anchor(store, anchor, create=True):
    """store ↔ anchor 一对一：首次创建锚记录，此后不一致即 fail-closed。"""
    store_p = Path(store)
    existing = read_anchor(store_p)
    if existing is None:
        if not create:
            raise Fail("store 尚未绑定 anchor：%s" % store,
                       hint="先对该 store 执行一次 snapshot（会写入锚记录）")
        store_p.mkdir(parents=True, exist_ok=True)
        write_atomic_text(store_p / ANCHOR_FILE, anchor + "\n")
        return anchor
    if os.path.normcase(existing) != os.path.normcase(anchor):
        raise Fail("store 已绑定到其它 anchor：%s（本次：%s）" % (existing, anchor),
                   hint="一个 store 只能服务一个 anchor；如需覆盖更大范围请由项目层上移 anchor")
    return existing


def alloc_snapshot(dirpath, base):
    """原子占用一个快照名：base，冲突时 base-01/base-02…（字典序单调）。"""
    dirpath = Path(dirpath)
    for i in range(0, 100):
        name = base if i == 0 else "%s-%02d" % (base, i)
        target = dirpath / name
        try:
            fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            continue
        os.close(fd)
        return target
    raise Fail("同一秒内快照数量过多：%s" % base)
def prune_dir(dirpath, keep, apply=False):
    """单个文件目录的保留策略：保留最新 keep 份；永不删最新一份。"""
    if keep < 1:
        raise Fail("--keep 必须 >= 1")
    entries = snapshot_entries(dirpath)
    old = sorted(entries[keep:], key=lambda p: p.name)
    deleted = []
    if apply:
        for p in old:
            os.remove(str(p))
            deleted.append(p.name)
    return [p.name for p in old], deleted


def scan_file_dirs(store):
    """遍历 store，返回所有「直接包含布局 A 快照」的目录。"""
    found = []
    for root, dirs, _files in os.walk(str(store)):
        dirs[:] = [d for d in dirs if not d.startswith(TMP_PREFIX)]
        if snapshot_entries(root):
            found.append(Path(root))
    return sorted(found, key=lambda p: str(p))


def snapshot_one(store, anchor, file_abs):
    src = Path(file_abs)
    if not src.is_file():
        raise Fail("源文件不存在或不是常规文件：%s" % file_abs,
                   hint="改前留痕只针对既有文件；新文件无需备份")
    rel = posix_rel(file_abs, anchor)
    bind_anchor(store, anchor)
    d = Path(store) / rel
    base = now_stamp()
    digest = sha256_file(src)
    size = src.stat().st_size
    if d.is_dir():
        for p in snapshot_entries(d):
            if p.name.startswith(base) and sha256_file(p) == digest:
                return {"ok": True, "idempotent": True, "src": file_abs, "snapshot": str(p),
                        "sha256": digest, "bytes": size, "timestamp": p.name,
                        "store": store, "anchor": anchor, "layout": LAYOUT}
    d.mkdir(parents=True, exist_ok=True)
    target = alloc_snapshot(d, base)
    try:
        n, h = copy_verify(src, target)
    except Exception:
        try:
            os.remove(str(target))
        except OSError:
            pass
        raise
    candidates, deleted = prune_dir(d, KEEP, apply=True)
    return {"ok": True, "idempotent": False, "src": file_abs, "snapshot": str(target),
            "sha256": h, "bytes": n, "timestamp": target.name,
            "store": store, "anchor": anchor, "layout": LAYOUT,
            "pruned": deleted, "pruneCandidates": candidates}


def do_snapshot(args):
    store = abspath(args.store)
    anchor = abspath(args.anchor)
    results = [snapshot_one(store, anchor, abspath(f)) for f in args.file]
    emit({"ok": True, "count": len(results), "results": results})
    if results and all(r.get("idempotent") for r in results):
        return 2
    return 0
def resolve_dir(store, anchor, file_abs):
    bind_anchor(store, anchor, create=False)
    return Path(store) / posix_rel(file_abs, anchor)


def do_list(args):
    store = abspath(args.store)
    anchor = abspath(args.anchor)
    file_abs = abspath(args.file)
    d = resolve_dir(store, anchor, file_abs)
    entries = snapshot_entries(d)
    cur = sha256_file(file_abs) if os.path.isfile(file_abs) else None
    items = []
    for p in entries:
        h = sha256_file(p)
        items.append({"timestamp": p.name, "path": str(p), "bytes": p.stat().st_size,
                      "sha256": h, "matchesCurrent": (cur is not None and cur == h)})
    legacy = []
    if d.is_dir():
        for p in sorted(d.iterdir(), key=lambda x: x.name):
            if not (p.is_file() and TS_RE.match(p.name)):
                legacy.append(p.name)
    emit({"ok": True, "src": file_abs, "store": store, "anchor": anchor, "layout": LAYOUT,
          "count": len(items), "snapshots": items,
          "legacyCount": len(legacy), "legacy": legacy})
    return 0


def do_restore(args):
    store = abspath(args.store)
    anchor = abspath(args.anchor)
    file_abs = abspath(args.file)
    d = resolve_dir(store, anchor, file_abs)
    entries = snapshot_entries(d)
    if not entries:
        raise Fail("没有任何布局 A 快照可恢复：%s" % file_abs)
    if args.snapshot:
        pick = [p for p in entries if p.name == args.snapshot]
        if not pick:
            raise Fail("指定的快照不存在：%s" % args.snapshot)
        chosen = pick[0]
    else:
        chosen = entries[0]
    exists = os.path.isfile(file_abs)
    plan = {"src": file_abs, "snapshot": str(chosen), "timestamp": chosen.name,
            "sha256": sha256_file(chosen), "bytes": chosen.stat().st_size,
            "preSnapshot": bool(exists), "store": store, "anchor": anchor, "layout": LAYOUT}
    if not args.apply:
        emit({"ok": True, "applied": False, "plan": plan,
              "hint": "默认不动手；确认后加 --apply 执行（执行前会先备份当前文件）"})
        return 0
    pre = snapshot_one(store, anchor, file_abs) if exists else None
    n, h = copy_verify(chosen, file_abs)
    emit({"ok": True, "applied": True, "src": file_abs, "restoredFrom": str(chosen),
          "sha256": h, "bytes": n, "preSnapshot": pre})
    return 0


def do_prune(args):
    store = abspath(args.store)
    if not os.path.isdir(store):
        raise Fail("store 不存在或不是目录：%s" % store)
    if args.keep < 1:
        raise Fail("--keep 必须 >= 1")
    dirs = scan_file_dirs(store)
    candidates, deleted, legacy = [], [], []
    for d in dirs:
        cand, dele = prune_dir(d, args.keep, apply=bool(args.apply))
        candidates += [str(d / n) for n in cand]
        deleted += [str(d / n) for n in dele]
        for p in sorted(d.iterdir(), key=lambda x: x.name):
            if not (p.is_file() and TS_RE.match(p.name)):
                legacy.append(str(p))
    emit({"ok": True, "store": store, "keep": args.keep, "apply": bool(args.apply),
          "fileDirs": len(dirs), "count": len(candidates),
          "candidates": candidates, "deleted": deleted,
          "legacyCount": len(legacy), "legacy": legacy,
          "hint": None if args.apply else "默认只报告；确认后加 --apply 执行删除"})
    return 0
def do_selfcheck(args):
    emit({"ok": True, "version": VERSION, "layout": LAYOUT, "keep": KEEP,
          "python": "%d.%d.%d" % sys.version_info[:3], "executable": sys.executable,
          "note": "启动器的 selfcheck 为原生实现，不依赖 Python 即可报告运行时探测结果"})
    return 0


def add_path_args(parser, repeat_file=False):
    parser.add_argument("--store", required=True, help="备份根目录（绝对路径）")
    parser.add_argument("--anchor", required=True, help="相对路径基准目录（绝对路径）")
    if repeat_file:
        parser.add_argument("--file", required=True, action="append", dest="file",
                            help="被备份文件（绝对路径；可重复，一次备份多个文件）")
    else:
        parser.add_argument("--file", required=True, dest="file", help="目标文件（绝对路径）")
    return parser


def build_parser():
    p = argparse.ArgumentParser(
        prog="change-backup",
        description="改前留痕底层能力：为既有文件建立可恢复的改前副本（布局 A）。",
        epilog="退出码：0 成功；1 fail-closed；2 幂等命中（同刻同内容已存在）。")
    p.add_argument("--version", action="version", version="change-backup " + VERSION)
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("snapshot", help="建改前备份（改/删既有文件前调用；--file 可重复）")
    add_path_args(s, repeat_file=True)
    s.set_defaults(func=do_snapshot)

    s = sub.add_parser("list", help="只读列出某文件全部快照（按文件名时间戳降序）")
    add_path_args(s)
    s.set_defaults(func=do_list)

    s = sub.add_parser("restore", help="把快照拷回原位置（默认只打印；--apply 才写）")
    add_path_args(s)
    s.add_argument("--snapshot", help="指定快照名（默认取最近一份）")
    s.add_argument("--apply", action="store_true", help="真正执行；执行前会先备份当前文件")
    s.set_defaults(func=do_restore)

    s = sub.add_parser("prune", help="按保留策略裁剪（默认只报告；永不删最新一份）")
    s.add_argument("--store", required=True, help="备份根目录（绝对路径）")
    s.add_argument("--keep", type=int, default=KEEP, help="每个文件保留份数（默认 %d）" % KEEP)
    s.add_argument("--apply", action="store_true", help="真正执行删除")
    s.set_defaults(func=do_prune)

    s = sub.add_parser("selfcheck", help="报告本机制与运行时信息")
    s.set_defaults(func=do_selfcheck)
    return p


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        if exc.code in (0, None):
            return 0
        emit_fail(Fail("参数错误（用法见 change-backup --help）",
                       hint="snapshot/list/restore 需要 --store/--anchor/--file；prune 需要 --store"))
        return 1
    if not getattr(args, "command", None):
        emit_fail(Fail("缺少子命令", hint="用法见 change-backup --help"))
        return 1
    try:
        return args.func(args)
    except Fail as exc:
        emit_fail(exc)
        return exc.code
    except Exception as exc:
        emit_fail(Fail("未预期错误：%s" % exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
