# Window Screenshot Plugin

在 Windows 上截取任意应用程序窗口的插件。通过 Win32 PrintWindow / BitBlt API 实现，即使窗口被最小化或遮挡也能完整截取。纯 PowerShell 实现，零外部依赖。

支持 **Claude Code** 和 **OpenAI Codex** 两个平台。

## 系统要求

- **操作系统：** Windows 10 (1803+) / Windows 11
- **PowerShell：** 5.1+（Windows 内置）
- **依赖：** 无（纯 PowerShell + Win32 API）

## 快速使用

安装插件后，当你说"截一下 XXX"时，Agent 会自动执行截图工作流。也可以手动触发：

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

- **三级截取自动选择**：优先 PrintWindow → BitBlt 屏幕截取
- **黑屏检测**：采样 9 个像素点检测图像均匀性
- **最小化窗口恢复**：3 步渐进式恢复，截完后自动恢复
- **UWP 应用**：穿透 ApplicationFrameWindow
- **DPI 感知**：真实物理像素，不受缩放影响

## 许可证

MIT License
