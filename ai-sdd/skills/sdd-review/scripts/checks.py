#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sdd-review checks：机械事实核查（只读、fail-closed）。

用途：sdd-review 引擎在派发 reviewer 之前运行一次，把「可机械判定」的事实
（编号与引用 / 文件与链接存在性 / 模板必需字段 / 占位符残留 / 勾选与状态一致性 /
diff 范围 vs plan / 台账格式）以紧凑清单输出，避免占用 reviewer 的语义评审轮次。

契约：
- 只读、不写盘；不接 shell 执行（仅自动读取 git diff 列表时调用 git）。
- 输出一行一项：`[PASS|FAIL|WARN] <check> <detail> (<evidence>)`，默认 ≤80 行。
- 有 FAIL → 退出码 1；无 FAIL → 0；参数 / IO 错误 → 2（fail-closed）。
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

# 「涉及文件」缺失 / 无法核对时先 WARN（采用稳定后再改 FAIL）——见修订方案 D-11。
SCOPE_CHECK_LEVEL = WARN

PLACEHOLDER_TOKENS = ("TBD", "TODO", "XXX", "待定", "待补", "???")

BAD_SEVERITY_RE = re.compile(r"\bR\d+-([A-Za-z_]+)-\d+\b")
SECTION_REF_RE = re.compile(r"§\s*(\d+(?:\.\d+)*)")
NUMBERED_HEADING_RE = re.compile(r"^#{1,6}\s*(\d+(?:\.\d+)*)\b", re.MULTILINE)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
BACKTICK_RE = re.compile(r"`([^`]+)`")
LEDGER_ENTRY_RE = re.compile(r"^\s*[-*]?\s*(R\d+-(?:CRIT|IMP|MIN)-\d+)\s+(.*)$")
LEDGER_STATUS_RE = re.compile(r"\b(open|closed|reopened)\b", re.IGNORECASE)
TASK_LINE_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s+")
HEADING_RE = re.compile(r"^(#{1,6})\s*(.+?)\s*$")


@dataclass
class Result:
    check: str
    level: str
    detail: str
    evidence: str = ""

    def line(self):
        if self.evidence:
            return "[{0}] {1} {2} ({3})".format(self.level, self.check, self.detail, self.evidence)
        return "[{0}] {1} {2}".format(self.level, self.check, self.detail)


def split_front_matter(text):
    """返回 (front_matter dict, body)；无 front matter 时返回 ({}, text)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    fm = {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return fm, "\n".join(lines[i + 1:])
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*?)\s*$", lines[i])
        if m:
            fm[m.group(1)] = m.group(2)
    return {}, text


def find_section(text, *keywords):
    """返回第一个标题包含全部关键字的章节（到下一个同级/更高级标题前）；找不到返回 None。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if not m:
            continue
        level, title = len(m.group(1)), m.group(2)
        if all(k in title for k in keywords):
            out = [line]
            for nxt in lines[i + 1:]:
                m2 = HEADING_RE.match(nxt)
                if m2 and len(m2.group(1)) <= level:
                    break
                out.append(nxt)
            return "\n".join(out)
    return None


def parse_scope_files(plan_text):
    """从「涉及文件」章节提取路径列表（兼容表格行与列表行）；章节缺失返回 None。"""
    section = find_section(plan_text, "涉及文件")
    if section is None:
        return None
    files = []
    for line in section.splitlines()[1:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            cand = cells[1] if len(cells) >= 2 else ""
        elif re.match(r"^[-*]\s+", s):
            cand = re.sub(r"^[-*]\s+", "", s)
        else:
            continue
        cand = cand.strip()
        if not cand or cand == "文件路径":
            continue
        if set(cand) <= set("-: "):
            continue
        if any(ch in cand for ch in "<>*?"):
            continue
        if not re.match(r"^[A-Za-z]:[\\/]", cand):
            m = re.match(r"^(.*?):\d+(?:-\d+)?$", cand)
            if m:
                cand = m.group(1)
        cand = cand.strip().strip("`").strip()
        files.append(cand)
    seen = []
    for f in files:
        if f and f not in seen:
            seen.append(f)
    return seen


def parse_task_lines(plan_text):
    """返回 (已勾选数, 未勾选数)；仅统计「任务清单」章节（缺失则统计全文）。"""
    section = find_section(plan_text, "任务清单")
    target = section if section is not None else plan_text
    checked = unchecked = 0
    for line in target.splitlines():
        m = TASK_LINE_RE.match(line)
        if not m:
            continue
        if m.group(1) in "xX":
            checked += 1
        else:
            unchecked += 1
    return checked, unchecked


def strip_code_fences(text):
    """把 fenced code block 内容替换为空行（保留行号），用于占位符扫描。"""
    out = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)
def check_required_fields(plan_text):
    results = []
    fm, _ = split_front_matter(plan_text)
    missing = [k for k in ("title", "status") if not fm.get(k)]
    if missing:
        results.append(Result("required-fields", FAIL, "front matter 缺少字段", ", ".join(missing)))
    else:
        results.append(Result("required-fields", PASS, "front matter 完整（title / status）", ""))
    for label, kws in (("目标", ("目标",)), ("涉及文件", ("涉及文件",)), ("风险", ("风险",)), ("任务清单", ("任务清单",))):
        if find_section(plan_text, *kws) is not None:
            continue
        if label == "涉及文件":
            results.append(Result("required-fields", SCOPE_CHECK_LEVEL, "缺少「涉及文件」章节（先按 WARN，采用稳定后升 FAIL）", ""))
        else:
            results.append(Result("required-fields", FAIL, "缺少必需章节", label))
    checked, unchecked = parse_task_lines(plan_text)
    if checked + unchecked == 0:
        results.append(Result("required-fields", FAIL, "任务清单无任务条目（- [ ] / - [x]）", ""))
    return results


def check_ids_and_refs(plan_text):
    results = []
    bad = []
    for idx, line in enumerate(plan_text.splitlines(), 1):
        for m in BAD_SEVERITY_RE.finditer(line):
            if m.group(1).upper() not in ("CRIT", "IMP", "MIN"):
                bad.append("L{0}:{1}".format(idx, m.group(0)))
    if bad:
        results.append(Result("ids", FAIL, "存在非法严重度缩写", "; ".join(bad[:5])))
    else:
        results.append(Result("ids", PASS, "问题编号格式合法", ""))
    heading_numbers = {m.group(1) for m in NUMBERED_HEADING_RE.finditer(plan_text)}
    refs = []
    for idx, line in enumerate(plan_text.splitlines(), 1):
        for m in SECTION_REF_RE.finditer(line):
            refs.append((idx, m.group(1)))
    if not refs:
        results.append(Result("refs", PASS, "无 § 引用", ""))
    elif not heading_numbers:
        results.append(Result("refs", WARN, "存在 § 引用但文档无编号标题，无法核对", "L{0}".format(refs[0][0])))
    else:
        missing = [(i, r) for i, r in refs if r not in heading_numbers]
        if missing:
            ev = "; ".join("L{0}:§{1}".format(i, r) for i, r in missing[:5])
            results.append(Result("refs", FAIL, "§ 引用指向不存在的章节", ev))
        else:
            results.append(Result("refs", PASS, "§ 引用均可解析（{0} 处）".format(len(refs)), ""))
    return results


def _skip_link_target(target):
    t = target.strip().strip("<>")
    if not t or t.startswith("#"):
        return True
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", t):
        return True
    return False


def _looks_like_path(tok):
    if not tok or len(tok) > 200 or tok.startswith("-") or tok.startswith("~"):
        return False
    if any(ch in tok for ch in "<>{}*?|"):
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", tok):
        return False
    return ("/" in tok) or ("\\" in tok)


def check_links_and_paths(plan_text, base_dir, artifacts=()):
    results = []
    base = Path(base_dir)
    missing = []
    for idx, line in enumerate(plan_text.splitlines(), 1):
        for m in LINK_RE.finditer(line):
            target = m.group(1)
            if _skip_link_target(target):
                continue
            path_part = target.strip().strip("<>").split("#", 1)[0].strip()
            if not path_part:
                continue
            cand = Path(path_part)
            if not cand.is_absolute():
                cand = base / cand
            if not cand.exists():
                missing.append("L{0}:{1}".format(idx, path_part))
    if missing:
        results.append(Result("links", FAIL, "Markdown 链接指向不存在的路径", "; ".join(missing[:5])))
    else:
        results.append(Result("links", PASS, "Markdown 链接均存在（已跳过外部/锚点）", ""))
    not_yet = []
    for idx, line in enumerate(plan_text.splitlines(), 1):
        for m in BACKTICK_RE.finditer(line):
            tok = m.group(1).strip()
            if not _looks_like_path(tok):
                continue
            path_part = tok.split("#", 1)[0]
            cand = Path(path_part)
            if not cand.is_absolute():
                cand = base / cand
            if not cand.exists():
                not_yet.append("L{0}:{1}".format(idx, path_part))
    if not_yet:
        results.append(Result("paths", WARN, "引用的文件路径暂不存在（可能是计划新建）", "; ".join(not_yet[:5])))
    else:
        results.append(Result("paths", PASS, "反引号路径均存在（或已跳过非路径 token）", ""))
    missing_art = []
    for a in artifacts:
        cand = Path(a)
        if not cand.is_absolute():
            cand = base / cand
        if not cand.exists():
            missing_art.append(a)
    if missing_art:
        results.append(Result("artifacts", FAIL, "产物路径不存在", "; ".join(missing_art[:5])))
    return results


def check_placeholders(plan_text):
    stripped = strip_code_fences(plan_text)
    hits = []
    for idx, line in enumerate(stripped.splitlines(), 1):
        for tok in PLACEHOLDER_TOKENS:
            if tok in line:
                hits.append("L{0}:{1}".format(idx, tok))
    if hits:
        return [Result("placeholders", FAIL, "存在占位符残留", "; ".join(hits[:5]))]
    return [Result("placeholders", PASS, "无占位符残留（已忽略代码块）", "")]


def check_checkbox_status(plan_text):
    fm, _ = split_front_matter(plan_text)
    status = (fm.get("status") or "").strip().lower()
    checked, unchecked = parse_task_lines(plan_text)
    total = checked + unchecked
    if total == 0:
        return [Result("checkbox", WARN, "未找到任务条目，无法核对勾选状态", "")]
    results = []
    if status == "completed" and unchecked > 0:
        results.append(Result("checkbox", FAIL, "status=completed 但存在未勾选任务", "{0}/{1} 已勾选".format(checked, total)))
    else:
        results.append(Result("checkbox", PASS, "勾选与状态一致（{0}/{1} 已勾选，status={2}）".format(checked, total, status or "?"), ""))
    if status != "completed" and unchecked == 0:
        results.append(Result("checkbox", WARN, "全部任务已勾选但 status 未标 completed", "status=" + (status or "?")))
    return results


def _normalize_path(p):
    p = p.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def check_diff_scope(plan_text, diff_files, diff_available):
    declared = parse_scope_files(plan_text)
    if declared is None:
        return [Result("diff-scope", SCOPE_CHECK_LEVEL, "plan 无「涉及文件」章节，无法核对 diff 范围", "")]
    if not diff_available or diff_files is None:
        return [Result("diff-scope", WARN, "无 diff 来源，无法核对范围", "")]
    declared_set = {_normalize_path(x) for x in declared if x.strip()}
    actual_set = {_normalize_path(x) for x in diff_files if x.strip()}
    results = []
    extra = sorted(actual_set - declared_set)
    missing = sorted(declared_set - actual_set)
    if extra:
        results.append(Result("diff-scope", FAIL, "存在未声明的文件变更", "; ".join(extra[:5])))
    else:
        results.append(Result("diff-scope", PASS, "无未声明变更（声明 {0} 项 / 实际 {1} 项）".format(len(declared_set), len(actual_set)), ""))
    if missing:
        results.append(Result("diff-scope", WARN, "声明了但未见改动的文件", "; ".join(missing[:5])))
    return results


def check_ledger_format(plan_text):
    section = find_section(plan_text, "评审记录")
    if section is None:
        return [Result("ledger", PASS, "无评审记录（首轮前，跳过）", "")]
    results = []
    entries = []
    no_status = []
    for line in section.splitlines():
        m = LEDGER_ENTRY_RE.match(line)
        if not m:
            continue
        entries.append(m.group(1))
        if not LEDGER_STATUS_RE.search(m.group(2)):
            no_status.append(m.group(1))
    if no_status:
        results.append(Result("ledger", FAIL, "台账条目缺少状态（open/closed/reopened）", "; ".join(no_status[:5])))
    dup = sorted({x for x in entries if entries.count(x) > 1})
    if dup:
        results.append(Result("ledger", FAIL, "台账存在重复 id", "; ".join(dup[:5])))
    if not no_status and not dup:
        results.append(Result("ledger", PASS, "台账格式合法（{0} 条）".format(len(entries)), ""))
    if "结果" not in section:
        results.append(Result("ledger", WARN, "评审记录缺少「结果」行（可能仍在进行中）", ""))
    return results
def run_checks(plan_path, change_dir, artifacts=(), diff_files=None, diff_available=False):
    plan_text = Path(plan_path).read_text(encoding="utf-8-sig")
    results = []
    results += check_required_fields(plan_text)
    results += check_ids_and_refs(plan_text)
    results += check_links_and_paths(plan_text, change_dir, artifacts)
    results += check_placeholders(plan_text)
    results += check_checkbox_status(plan_text)
    results += check_diff_scope(plan_text, diff_files, diff_available)
    results += check_ledger_format(plan_text)
    return results


def load_diff(repo, diff_file):
    """返回 (diff_files | None, note)。"""
    if diff_file:
        p = Path(diff_file)
        if not p.exists():
            return None, "diff 文件不存在: " + str(p)
        lines = [ln.strip() for ln in p.read_text(encoding="utf-8-sig").splitlines()]
        return [ln for ln in lines if ln], "diff-file"
    if repo:
        last = "git 不可用"
        for cmd in (["git", "-C", str(repo), "diff", "--name-only", "HEAD"],
                    ["git", "-C", str(repo), "diff", "--name-only"]):
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
            except OSError as exc:
                return None, "git 调用失败: " + str(exc)
            if proc.returncode == 0:
                files = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
                return files, "git"
            last = "git diff 失败（exit={0}）".format(proc.returncode)
        return None, last
    return None, "未提供 diff 来源"


def format_report(results, max_lines=80):
    lines = [r.line() for r in results]
    fails = sum(1 for r in results if r.level == FAIL)
    warns = sum(1 for r in results if r.level == WARN)
    passes = sum(1 for r in results if r.level == PASS)
    if max_lines and len(lines) > max_lines:
        omitted = len(lines) - (max_lines - 1)
        lines = lines[: max_lines - 1] + ["... ({0} more lines omitted)".format(omitted)]
    lines.append("SUMMARY PASS={0} FAIL={1} WARN={2}".format(passes, fails, warns))
    return "\n".join(lines)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="checks",
        description="sdd-review mechanical fact checks (read-only, fail-closed)",
    )
    ap.add_argument("--change", required=True, help="change directory (contains plan.md)")
    ap.add_argument("--plan", help="plan.md path (default: <change>/plan.md)")
    ap.add_argument("--artifacts", nargs="*", default=[], help="artifact paths (relative to <change> or absolute)")
    ap.add_argument("--diff-file", help="changed-files list (one path per line)")
    ap.add_argument("--repo", help="git repo path; used when --diff-file is absent")
    ap.add_argument("--no-diff", action="store_true", help="skip diff-scope check")
    ap.add_argument("--max-lines", type=int, default=80, help="output line budget (default 80)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    change_dir = Path(args.change)
    plan_path = Path(args.plan) if args.plan else change_dir / "plan.md"
    if not plan_path.exists():
        sys.stderr.write("plan not found: " + str(plan_path) + "\n")
        return 2
    if args.no_diff:
        diff_files, note = None, "disabled"
    else:
        diff_files, note = load_diff(args.repo, args.diff_file)
    if note not in ("diff-file", "git", "disabled"):
        print("[WARN] diff-source " + note)
    try:
        results = run_checks(plan_path, change_dir, args.artifacts, diff_files, diff_files is not None)
    except Exception as exc:  # fail-closed：任何解析/IO 异常都以退出码 2 终止
        sys.stderr.write("checks failed (fail-closed): {0}: {1}\n".format(type(exc).__name__, exc))
        return 2
    print(format_report(results, args.max_lines))
    return 1 if any(r.level == FAIL for r in results) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())


