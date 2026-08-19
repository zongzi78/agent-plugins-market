---
name: window-screenshot
description: 当 Agent 需要在 Windows 上截取特定应用程序窗口的截图时使用。触发词：screenshot, capture window, take screenshot, GUI verification, visual check, 截图, 截屏, 界面截图, 窗口截图。
---

# 窗口截图工具

通过 PrintWindow API 截取指定进程的 GUI 窗口，即使窗口被遮挡或在后台也能完整截取。纯 PowerShell 实现，零外部依赖。

## 系统要求

- **操作系统**：Windows 10 (1803+) / Windows 11
- **PowerShell**：5.1+（Windows 内置）
- **会话**：需要交互式桌面会话（本地或 RDP）；服务/无桌面会话（Session 0）下 BitBlt 屏幕截取不可用
- **依赖**：无（纯 PowerShell + Win32 API）

## 定位脚本

脚本位于本 skill 安装目录下的 `scripts/Capture-Window.ps1`，其中 `<SKILL_DIR>` 是本 SKILL.md 文件所在的目录。

执行任何命令前，先解析脚本的完整路径：

```powershell
$skillDir = "<SKILL_DIR>"  # 替换为本 SKILL.md 实际所在的目录
$script = Join-Path $skillDir "scripts\Capture-Window.ps1"
```

## 快速使用

```powershell
$skillDir = "<SKILL_DIR>"
$script = Join-Path $skillDir "scripts\Capture-Window.ps1"
powershell -ExecutionPolicy Bypass -File $script -ProcessName "notepad" -OutputPath "screenshot.png"
```

截取成功后，用 Read 工具读取生成的 PNG 文件查看截图。

## 智能发现工作流

当用户说"截一下 XXX"时，按以下步骤操作：

### 第 1 步：枚举窗口

```powershell
$skillDir = "<SKILL_DIR>"
$script = Join-Path $skillDir "scripts\Capture-Window.ps1"
powershell -ExecutionPolicy Bypass -File $script -ListWindows
```

从返回的 JSON 中搜索匹配用户描述的窗口标题，找到对应的进程名和 PID。若 JSON 含 processNameLookupBlocked: true（进程名未能解析，受限环境常见），改用 -WindowTitle 或 -Hwnd 定位窗口。

### 第 2 步：截图

```powershell
$skillDir = "<SKILL_DIR>"
$script = Join-Path $skillDir "scripts\Capture-Window.ps1"
powershell -ExecutionPolicy Bypass -File $script -ProcessId <PID> -OutputPath "screenshot.png"
```

### 多窗口处理

如果脚本返回 `exit code 2`（来自不同进程的多个窗口），从输出的 `windows` 数组中选择正确的窗口，用 `-ProcessId` 或 `-Hwnd` 重新执行。

同一进程的多个窗口会自动选择最大的一个。

## 参数速查

| 参数 | 说明 | 示例 |
|------|------|------|
| `-ProcessName` | 进程名 | `-ProcessName "notepad"` |
| `-ProcessId` | 进程 ID（最精确） | `-ProcessId 1234` |
| `-WindowTitle` | 窗口标题（模糊匹配） | `-WindowTitle "微信"` |
| `-WindowClass` | 窗口类名 | `-WindowClass "Notepad"` |
| `-Hwnd` | 窗口句柄（十六进制） | `-Hwnd 0x1A2B3C` |
| `-OutputPath` | 输出 PNG 路径 | `-OutputPath "C:\temp\shot.png"` |
| `-ListWindows` | 列出所有可见窗口 | `-ListWindows` |

## 错误处理

| 退出码 | 含义 | 操作 |
|-------|------|------|
| 0 | 成功 | 用 Read 工具读取 PNG |
| 1 | 错误 | 检查 stderr 的 JSON，尝试 `-ListWindows` |
| 2 | 多窗口（不同进程） | 从 stdout 读取窗口列表，用 `-ProcessId` 重试 |

> 补充：若 JSON 含 `processNameLookupBlocked: true`，表示进程名未能解析（受限环境常见），请用 `-Hwnd` / `-WindowTitle` 定位窗口；错误 JSON 可能含 `hint` 字段，按提示处理。

## 受限环境（沙箱）说明

- 进程名通过 Get-Process 获取；在受限环境（沙箱/最小权限）可能被拦截。此时窗口列表**仍返回 PID / HWND / 标题**，JSON 中 processNameLookupBlocked: true 提示；直接用 -Hwnd 或 -WindowTitle 截图即可，无需进程枚举。
- 若运行环境拦截整条命令本身（如 -ListWindows 调用），需要为该命令申请提权或在非沙箱环境运行。
- 输出路径：默认写入 %TEMP%；受限环境可能不可写/不可读，建议显式指定 -OutputPath 到 Agent 与用户都可读写的目录。
- 窗口枚举与截图走 Win32 API，通常不受文件系统沙箱影响。
- interactiveSession 字段反映当前会话是否具备交互式桌面（Session 0/服务会话为 false），不代表沙箱权限；interactiveSession: true 不保证 BitBlt 一定可用。

## 注意事项

- 每次通过新的 PowerShell 进程执行都有几秒编译开销（Add-Type 编译 C#）；同一进程内重复调用无此开销
- 最小化窗口会临时恢复再截图，截完后自动恢复最小化状态
- UWP 应用（如设置、Store）会自动查找实际内容窗口
- 截图为真实物理像素，不受 DPI 缩放影响
- 截图方法自动选择：优先 PrintWindow（不干扰用户），失败后自动切换到 BitBlt 屏幕截取
- Qt 应用（如 faultscan、psasp）等不支持 PrintWindow 的应用，会自动触发 BitBlt 截图。此时窗口会短暂置顶并激活，截图完成后自动恢复原前台窗口
- BitBlt 截取屏幕像素，如果目标窗口被其他窗口遮挡，可能会截到遮挡物
