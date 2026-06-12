---
name: window-screenshot
description: 当 Agent 需要在 Windows 上截取特定应用程序窗口的截图时使用。触发词：screenshot, capture window, take screenshot, GUI verification, visual check, 截图, 截屏, 界面截图, 窗口截图。
---

# 窗口截图工具

通过 PrintWindow API 截取指定进程的 GUI 窗口，即使窗口被遮挡或在后台也能完整截取。纯 PowerShell 实现，零外部依赖。

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

从返回的 JSON 中搜索匹配用户描述的窗口标题，找到对应的进程名和 PID。

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

## 注意事项

- 首次执行有几秒编译开销（Add-Type 编译 C#），后续调用无此开销
- 最小化窗口会临时恢复再截图，截完后自动恢复最小化状态
- UWP 应用（如设置、Store）会自动查找实际内容窗口
- 截图为真实物理像素，不受 DPI 缩放影响
- 截图方法自动选择：优先 PrintWindow（不干扰用户），失败后自动切换到 BitBlt 屏幕截取
- Qt 应用（如 faultscan、psasp）等不支持 PrintWindow 的应用，会自动触发 BitBlt 截图。此时窗口会短暂置顶并激活，截图完成后自动恢复原前台窗口
- BitBlt 截取屏幕像素，如果目标窗口被其他窗口遮挡，可能会截到遮挡物
