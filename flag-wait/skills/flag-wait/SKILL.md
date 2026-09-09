---
name: flag-wait
description: >
  用 JSON 哨兵文件协调两个 AI 会话：完成方发布哨兵（flag publish），等待方等候文件出现
  （flag wait）并校验后继续（flag check）。适用于「一个会话必须等另一个会话完成才能开工」、
  「等待标志/哨兵文件后再接续」的场景。触发词：等待哨兵、等待标志、等 succ.flag、flag wait、
  sentinel、哨兵等待、等另一个会话完成、publish flag、wait for flag。
---

# flag-wait

通过共享文件系统上的一个 JSON 哨兵文件协调两个 AI 会话：一方工作完成后写入哨兵，另一方等待文件出现、校验契约后继续。命令集与哨兵格式固定，Windows 与 Linux 行为一致。

## 环境要求

- Python 3.7+（`uv`、`python3` 或 `python`，三条路径任一可用即可）
- 两个会话共享同一文件系统（本地磁盘或已挂载共享盘）
- Windows 需 PowerShell 5.1+；Linux/macOS 需 bash

## 定位命令

命令位于本 skill 安装目录：

```powershell
# Windows
$flag = "<SKILL_DIR>\scripts\flag.ps1"
```

```bash
# Linux / macOS / Git Bash
FLAG="<SKILL_DIR>/scripts/flag"
```

启动器自动探测可用运行时（`uv → python3 → python`），把参数转发给 Python 核心 `flag.py`。把 `<SKILL_DIR>` 替换为本 SKILL.md 所在目录。

## 快速使用

**生产者——完成工作后发布哨兵：**

```powershell
& $flag publish "D:\work\succ.flag" --status success --proceed true --reason "contract ready"
```

```bash
$FLAG publish /tmp/work/succ.flag --status success --proceed true --reason "contract ready"
```

**消费者——开工前等待并校验：**

```powershell
& $flag wait "D:\work\succ.flag" --timeout 1800 --interval 1
# => FOUND=true
& $flag check "D:\work\succ.flag"
# => CHECK=true
```

```bash
$FLAG wait /tmp/work/succ.flag --timeout 1800 --interval 1
$FLAG check /tmp/work/succ.flag
```

等待时把 `wait` 作为后台/阻塞任务运行，脚本内部轮询文件，**等待期间的轮询不消耗模型 token**。`FOUND=true` 只代表文件存在，**必须先 `check` 再开工**。

## 命令

| 命令 | 用途 | 输出 | 退出码 |
|------|------|------|--------|
| `publish <flag> --status success\|failed --proceed true\|false [--reason R] [--producer P] [--meta K=V ...] [--force]` | 原子写哨兵 | JSON | 0=成功，1=失败 |
| `wait <flag> [--timeout 秒] [--interval 秒] [--json]` | 阻塞直到文件存在 | `FOUND=true/false`（或 JSON） | 0=命中，1=超时/错误 |
| `check <flag> [--json]` | 校验哨兵契约 | `CHECK=true/false`（或 JSON） | 0=可继续，1=不可继续/错误 |

`flag --help`、`flag help <子命令>`、`flag <子命令> --help` 打印用法；`flag selfcheck` 打印启动器选中运行时。

## 哨兵格式

`publish` 写入固定 JSON：

```json
{
  "status": "success",
  "proceed": true,
  "reason": "contract ready",
  "producer": "session-a",
  "published_at": "2026-09-09T09:30:00+08:00",
  "meta": {}
}
```

- `status`：`success` 或 `failed`。
- `proceed`：消费者是否可继续。`check` 以它为接续判据。
- `check` 只接受合法 JSON、且 `status` 为 `success|failed`、且 `proceed` 为 `true` 的文件；缺失、损坏、空文件一律不接续。

## 关键规则

- `wait` 只判「文件是否存在」，语义判断一律由 `check` 完成。
- `publish` 是原子写：先在目标目录内写临时文件，再 `os.replace` 到目标；文件要么完整、要么不存在。
- 目标已存在且 `status=success` 时再次 `publish` 幂等返回；加 `--force` 才覆盖。
- 等待前可做只读准备；不要修改另一个会话拥有的文件。
- 超时后把结果交给调用方（重试 / 通知人类 / 放弃由调用方决定）。

## Gotchas（踩坑经验）

- `wait` **不解读哨兵内容**。若生产者在真正就绪前就写出文件，该文件并不代表「可继续」。
- 哨兵不是锁，不阻止并发写；跨会话的目录/文件归属需在会话间约定。
- 共享网络盘上 `os.replace` 通常原子，但平台行为可能不同；优先同一台机器或同一工作区。
- 中文路径：Windows 下避免把含中文的路径作为 argv 传给启动器子进程；可先 `cd` 进目录、用相对 ASCII 文件名。
- 启动器在 stderr 输出 `WARN --no-project`（uv 良性提示）；**结果只认 stdout**。