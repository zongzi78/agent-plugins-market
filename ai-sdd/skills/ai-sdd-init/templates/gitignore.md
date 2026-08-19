# `.gitignore` 播种模板（git init 本地镜像时使用）

当 `ai-sdd-init` 的 VCS 探测为"无 VCS"且用户选择「git init 本地镜像」时，
在项目根创建 `.gitignore`，内容如下（可在此基础上追加项目自身的忽略项）：

```gitignore
# AI-SDD 备份/快照目录（本地留痕，不入库）
.ai/backups/
**/.sync-backup/

# 本地缓存
.ai/ref/cache/
tmp/

# Python
__pycache__/
*.pyc
.venv/

# 工具
.vscode/
.idea/
```

> 说明：`.ai/backups/`（快照）与 change 目录下的 `.sync-backup/`（sync 只读快照）是本地留痕数据，
> 不应进入版本库；`git init` 后立即播种，防止备份目录入库。