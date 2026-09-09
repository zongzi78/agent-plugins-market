#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flag-wait skill core (Python, cross-platform).

Subcommands: publish / wait / check.
Sentinel JSON contract: {status, proceed, reason, producer, published_at, meta}.
Safety: atomic publish (temp file + os.replace), idempotent, fail-closed, pure poll.
stdout is UTF-8; error JSON schema: {"ok":false,"error":str,"exitCode":int,"hint":str|null}.
"""
import sys
import os
import json
import math
import time
import argparse
import tempfile

if sys.version_info >= (3, 7):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

EXIT_OK = 0
EXIT_ERROR = 1

STATUS_VALUES = ("success", "failed")

USAGE = (
    "usage: flag <subcommand> [options]\n"
    "  subcommands: publish / wait / check\n"
    "  flag --help | flag help <sub> | flag <sub> --help\n"
)


def err_json(error, exit_code=EXIT_ERROR, hint=None):
    return {"ok": False, "error": error, "exitCode": exit_code, "hint": hint}


def emit(obj, exit_code=EXIT_OK):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return exit_code


class FancyParser(argparse.ArgumentParser):
    """ArgumentParser that emits JSON errors instead of argparse's plain stderr."""

    def error(self, message):
        emit(err_json(message, EXIT_ERROR))
        sys.exit(EXIT_ERROR)


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes", "y", "on"):
            return True
        if low in ("false", "0", "no", "n", "off"):
            return False
    raise argparse.ArgumentTypeError("proceed must be true|false")


def _iso_now():
    t = time.localtime()
    off = time.timezone if t.tm_isdst == 0 else time.altzone
    sign = "+" if off <= 0 else "-"
    absoff = abs(off)
    return time.strftime("%Y-%m-%dT%H:%M:%S", t) + "%s%02d:%02d" % (sign, absoff // 3600, (absoff % 3600) // 60)


def _load_payload(flag):
    try:
        with open(flag, "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as e:
        return None, str(e)


def _write_atomic(payload, flag):
    d = os.path.dirname(os.path.abspath(flag)) or "."
    fd = tmp = None
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".flag.tmp.", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = None  # ownership transferred to fh
            json.dump(payload, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, flag)
        tmp = None
    except Exception as e:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if tmp is not None:
            try:
                os.unlink(tmp)
            except Exception:
                pass
        return None, "write failed: %s" % e
    return flag, None


def _parse_meta(items):
    meta = {}
    for kv in items:
        if "=" not in kv:
            return None, "--meta expects KEY=VALUE, got %r" % kv
        k, v = kv.split("=", 1)
        if not k:
            return None, "--meta key must not be empty, got %r" % kv
        meta[k] = v
    return meta, None


def cmd_publish(args):
    meta, err = _parse_meta(args.meta)
    if err:
        return emit(err_json(err), EXIT_ERROR)
    if os.path.exists(args.flag) and not args.force:
        data, load_err = _load_payload(args.flag)
        if load_err is None and isinstance(data, dict) and data.get("status") == "success":
            return emit({"ok": True, "exists": True, "flag": args.flag,
                         "status": "success", "proceed": data.get("proceed")}, EXIT_OK)
    payload = {
        "status": args.status,
        "proceed": args.proceed,
        "reason": args.reason,
        "producer": args.producer,
        "published_at": _iso_now(),
        "meta": meta,
    }
    flag, err = _write_atomic(payload, args.flag)
    if err:
        return emit(err_json(err), EXIT_ERROR)
    return emit({"ok": True, "flag": flag, "status": args.status, "proceed": args.proceed}, EXIT_OK)


def wait_poll(flag, timeout, interval):
    deadline = time.monotonic() + timeout
    while True:
        if os.path.exists(flag):
            return True
        if time.monotonic() >= deadline:
            return os.path.exists(flag)
        time.sleep(interval)


def cmd_wait(args):
    if not (math.isfinite(args.timeout) and math.isfinite(args.interval)
            and args.timeout > 0 and args.interval > 0):
        return emit(err_json("timeout/interval must be finite and > 0"), EXIT_ERROR)
    found = wait_poll(args.flag, args.timeout, args.interval)
    if args.json:
        return emit({"found": found, "flag": args.flag, "exit": EXIT_OK if found else EXIT_ERROR},
                    EXIT_OK if found else EXIT_ERROR)
    sys.stdout.write("FOUND=true\n" if found else "FOUND=false\n")
    return EXIT_OK if found else EXIT_ERROR


def _check_result(ok, reason, status, flag, want_json):
    if want_json:
        return emit({"ok": ok, "reason": reason, "status": status, "flag": flag},
                    EXIT_OK if ok else EXIT_ERROR)
    if ok:
        sys.stdout.write("CHECK=true\n")
    else:
        sys.stdout.write("CHECK=false " + reason + "\n")
    return EXIT_OK if ok else EXIT_ERROR


def cmd_check(args):
    flag = args.flag
    if not os.path.exists(flag):
        return _check_result(False, "absent", None, flag, args.json)
    data, err = _load_payload(flag)
    if err is not None:
        return _check_result(False, "not-json:" + err, None, flag, args.json)
    if not isinstance(data, dict):
        return _check_result(False, "not-json:root must be object", None, flag, args.json)
    status = data.get("status")
    proceed = data.get("proceed")
    ok = (status in STATUS_VALUES) and (proceed is True)
    if not ok:
        reason = "status=%r proceed=%r" % (status, proceed)
        return _check_result(False, reason, status if isinstance(status, str) else None, flag, args.json)
    return _check_result(True, "proceed=true status=" + status, status, flag, args.json)


def build_parser():
    p = FancyParser(prog="flag", description="cross-session sentinel coordination (publish/wait/check).")
    sub = p.add_subparsers(dest="command", required=True)

    pub = sub.add_parser("publish", help="atomically write a sentinel flag",
                         description="Publish a sentinel flag atomically.")
    pub.add_argument("flag", help="path to the sentinel file")
    pub.add_argument("--status", required=True, choices=STATUS_VALUES,
                     help="producer result: success|failed")
    pub.add_argument("--proceed", required=True, type=_to_bool,
                     help="whether consumer may continue: true|false")
    pub.add_argument("--reason", default="", help="explanation text")
    pub.add_argument("--producer", default="", help="producer identifier")
    pub.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                     help="extra field (repeatable)")
    pub.add_argument("--force", action="store_true", help="overwrite existing flag even if already success")
    pub.set_defaults(func=cmd_publish)

    wait = sub.add_parser("wait", help="block until sentinel file exists",
                          description="Wait until the sentinel file exists.")
    wait.add_argument("flag", help="path to the sentinel file")
    wait.add_argument("--timeout", type=float, default=1800.0, help="max wait seconds (default 1800)")
    wait.add_argument("--interval", type=float, default=1.0, help="poll interval seconds (default 1.0)")
    wait.add_argument("--json", action="store_true", help="emit JSON result")
    wait.set_defaults(func=cmd_wait)

    chk = sub.add_parser("check", help="validate sentinel; proceed==true => can continue",
                         description="Validate the sentinel flag.")
    chk.add_argument("flag", help="path to the sentinel file")
    chk.add_argument("--json", action="store_true", help="emit JSON result")
    chk.set_defaults(func=cmd_check)

    return p


def _find_sub(parser, name):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            if name in action.choices:
                return action.choices[name]
    return None


def main(argv):
    parser = build_parser()
    if not argv:
        sys.stderr.write(USAGE)
        return EXIT_ERROR
    if argv[0] == "help":
        if len(argv) != 2:
            return emit(err_json("help requires exactly one <subcommand>", EXIT_ERROR), EXIT_ERROR)
        sub = _find_sub(parser, argv[1])
        if sub is None:
            return emit(err_json("unknown subcommand: %s" % argv[1], EXIT_ERROR), EXIT_ERROR)
        sub.print_help()
        return EXIT_OK
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))