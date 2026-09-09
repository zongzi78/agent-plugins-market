# Flag Wait Plugin

跨会话哨兵协调插件。通过共享文件系统上的 JSON 哨兵文件协调两个 AI 会话：完成方发布哨兵（`flag publish`），等待方等候文件出现（`flag wait`）并校验契约后继续（`flag check`）。跨平台、低成本、零/少依赖。

## 系统要求

- **运行时**：Python 3.7+（`flag` 启动器自动探测 `uv → python3 → python`，任一可用即可）
- **平台**：Windows（PowerShell 5.1+）/ Linux / macOS（bash）
- **文件系统**：两个会话共享同一本地磁盘或已挂载共享盘
- **依赖**：无第三方包（Python 标准库）

## 定位命令

`flag` 位于本插件安装目录：

```powershell
# Windows
$flag = Join-Path "<SKILL_DIR>" "scripts\flag.ps1"
```

```bash
# Linux / macOS / Git Bash
FLAG="<SKILL_DIR>/scripts/flag"
```

## 快速使用

### 生产者：完成工作后发布哨兵

```powershell
& $flag publish "D:\work\succ.flag" --status success --proceed true --reason "contract ready"
```

```bash
$FLAG publish /tmp/work/succ.flag --status success --proceed true --reason "contract ready"
```

### 消费者：开工前等待并校验

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

等待期间脚本内部轮询，**几乎不消耗模型 token**；`FOUND=true` 只代表文件存在，**必须先 `check` 再开工**。

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

- `status`：`success` 或 `failed`
- `proceed`：消费者是否可继续，`check` 以它为接续判据
- `check` 只接受合法 JSON、`status` 为 `success|failed`、且 `proceed` 为 `true` 的文件；缺失/损坏/空文件一律不接续

## Gotchas

- `wait` **不解读哨兵内容**；若生产者在真正就绪前写出文件，该文件不代表「可继续」
- 哨兵不是锁，不阻止并发写；目录/文件归属需在会话间约定
- 共享网络盘上 `os.replace` 通常原子，但平台行为可能不同；优先同一台机器或同一工作区
- 中文路径：Windows 下可先 `cd` 进目录、用相对 ASCII 文件名
- 启动器 stderr 会输出 uv 的 `WARN --no-project`（良性提示）；**结果只认 stdout**

## 许可证

MIT License