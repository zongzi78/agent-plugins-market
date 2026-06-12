# Window Screenshot Plugin for Claude Code

在 Windows 上截取任意应用程序窗口的 Claude Code 插件。通过 Win32 PrintWindow / BitBlt API 实现，即使窗口被最小化或遮挡也能完整截取。纯 PowerShell 实现，零外部依赖。

## 系统要求

- **操作系统：** Windows 10 (1803+) / Windows 11
- **PowerShell：** 5.1+（Windows 内置）
- **依赖：** 无（纯 PowerShell + Win32 API）

## 安装

### 方式一：从 GitHub Marketplace 安装（推荐）

```
/plugin marketplace add zongzi78/window-screenshot-plugin
/plugin install window-screenshot@window-screenshot
```

### 方式二：从 GitHub 本地安装

```bash
git clone https://github.com/zongzi78/window-screenshot-plugin.git
claude --plugin-dir ./window-screenshot-plugin
```

### 方式三：复制到 skills 目录

```bash
cp -r window-screenshot-plugin ~/.claude/skills/window-screenshot
```

## 快速使用

安装插件后，当你说"截一下 XXX"时，Agent 会自动执行以下工作流：

### 第 1 步：枚举窗口

```powershell
$skillDir = "<SKILL_DIR>"
$script = Join-Path $skillDir "scripts\Capture-Window.ps1"
powershell -ExecutionPolicy Bypass -File $script -ListWindows
```

### 第 2 步：截图

```powershell
$skillDir = "<SKILL_DIR>"
$script = Join-Path $skillDir "scripts\Capture-Window.ps1"
powershell -ExecutionPolicy Bypass -File $script -ProcessName "notepad" -OutputPath "screenshot.png"
```

截取成功后，用 Read 工具读取生成的 PNG 文件查看截图。

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

## 退出码

| 退出码 | 含义 | 操作 |
|-------|------|------|
| 0 | 成功 | 用 Read 工具读取 PNG |
| 1 | 错误 | 检查 stderr 的 JSON，尝试 `-ListWindows` |
| 2 | 多窗口（不同进程） | 从 stdout 读取窗口列表，用 `-ProcessId` 重试 |

## 技术说明

- **三级截取自动选择**：优先 PrintWindow（不干扰用户），失败后自动切换到 BitBlt 屏幕截取
- **黑屏检测**：通过采样 9 个像素点检测图像均匀性，自动判断截取是否成功
- **最小化窗口渐进式恢复**：对最小化窗口自动执行 3 步恢复（ShowWindow → 前台权限提升 → SC_RESTORE 消息），覆盖 Qt 等特殊应用，截完后自动恢复最小化和原始窗口层叠
- **UWP 应用**：自动穿透 ApplicationFrameWindow 查找实际内容窗口
- **DPI 感知**：截图为真实物理像素，不受 DPI 缩放影响
- **Qt 应用支持**：不支持 PrintWindow 的 Qt 应用会自动触发 BitBlt 截图，窗口短暂置顶后自动恢复
- **前台窗口保护**：截图时自动保存/恢复原前台窗口和 Z-order，通过 Alt 键模拟绕过前台锁

## 许可证

MIT License
