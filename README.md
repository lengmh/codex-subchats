# codex-subchats

轻量、Local-first 的独立 Codex CLI 子会话工具。核心 CLI、后台 worker 和 MCP Server 使用 Python 标准库，无运行时第三方依赖。源码采用 MIT 许可证。

**当前版本：0.1.0a1，实验验证原型。P0 尚缺用户 Windows VS Code 实测；不是已验收发布版。**

已实现独立会话、指定子模型、准确 Thread ID 恢复、持久化状态、完成事件入队、取消、冲突保护和 MCP。`queued` 仅表示 Codex 队列接受消息，不代表原 Astra 已执行。现有自动化测试使用 Codex 替身进程，尚无真实 Windows VS Code 自动唤醒验收结论。

## 从这里开始

1. 阅读 [P0 可行性报告](docs/feasibility.md)。
2. 按下述步骤运行 `doctor`，再按 [本机验收](docs/local-acceptance.md) 测试原 IDE 自动唤醒。
3. 基础探针通过后，再接入 MCP，完成三轮真实任务闭环。

## Windows 安装与只读检查

需要 Python 3.11+ 和已经登录、配置完成的原生 `codex.exe`。不要求安装 Node 包、不要求管理员权限。解压到固定路径；后台任务期间不要移动或更新源码。

在源码目录运行：

```powershell
python .\subchats.py --help
# 可选：仅列出标准 VS Code 扩展目录中的版本和 codex.exe 候选。
# 如果执行策略阻止脚本，不修改执行策略；直接手动确认路径。
.\scripts\Inspect-Host.ps1
```

候选路径不证明当前 IDE 正在使用它。用扩展的安装目录、版本和日志核对；自定义 VS Code 安装目录需手动检查。不要把 `codex.cmd` 当作原生可执行文件。

以下两个模型名称是用户期望值，**不是本机可调用性的保证**。`--parent-model` 只记录预期；主模型在原 VS Code 会话中选择，工具不会修改它。`--child-model` 会实际传给独立 CLI。

```powershell
$subchatsState = Join-Path $env:LOCALAPPDATA 'codex-subchats'
$subchatsCodex = 'C:\实际路径\codex.exe'
python .\subchats.py --state $subchatsState init `
  --codex $subchatsCodex `
  --child-model gpt-6.1-sol --parent-model gpt-6-astra `
  --sandbox read-only
python .\subchats.py --state $subchatsState doctor
```

`init` 仅创建工具自己的 `config.json`。已有文件不会被覆盖。`doctor` 只运行版本和帮助命令，不调用模型，不读取认证文件。检查 `exec_shape_supported`、`resume_help_available` 和 `queue_shape_supported`；检查通过仍不代表模型可用或 IDE 会自动执行。

如果子任务 CLI 和原 IDE 使用不同安装，初始化时可加 `--queue-codex 'C:\与IDE匹配\codex.exe'`。两者默认继承当前进程的 `CODEX_HOME` 和环境；工具不修改这些全局值。跨机器、不同 home 的队列不能假定互通。

已有自定义 provider 可通过 `--provider custom` 为子会话显式选择；不提供时沿用 CLI 的配置。`--effort high` 也是可选请求值。需要编码时，在完成探针后将工具 `config.json` 的 `sandbox` 设置为 `workspace-write`，再创建新子会话。已有子会话固定初始配置，避免恢复时悄然换模型或权限。子任务以 `approval_policy="never"` 非交互执行，受 sandbox 和既有规则约束；需要人工授权的操作会失败，不自动提升权限。

## 不接 MCP 也能运行

先准备一个测试 Git 仓库。非 Git 目录需要在初始化时明确加 `--skip-git-repo-check`。`--cwd` 指向子任务目录；写入任务建议使用独立 worktree。

```powershell
'只回复 CHILD_PROBE_OK。不要执行工具或修改文件。' | Set-Content -Encoding utf8 child-task.txt
python .\subchats.py --state $subchatsState start `
  --cwd 'C:\实际路径\测试仓库' --prompt-file .\child-task.txt `
  --request-key child-probe-1
```

命令立即返回 `id`（本轮 Run ID）和 `session_id`（工具会话句柄）。完成后用 `show` 查看 `thread_id`、输出和验证结果：

```powershell
python .\subchats.py --state $subchatsState show 'RUN_UUID'
'只回复 CHILD_RESUME_OK。' | Set-Content -Encoding utf8 next-task.txt
python .\subchats.py --state $subchatsState send `
  --session 'SESSION_UUID' --prompt-file .\next-task.txt --request-key child-probe-2
```

同一请求重试时保留 `request_key`；下一轮新任务必须使用新值。相同 key 但内容不同会拒绝。创建时指定 `--parent-thread '原IDE线程UUID'` 后，任务完成或失败会自动把通知送到原线程。必须使用已核实的原线程 UUID，不按标题猜测，不用 `--last`。

可以随时使用 `show` 读取日志。任务结束后，如需交互进入子会话，运行原生 `codex resume CHILD_THREAD_UUID`；它会占用这个线程，返回后台派发前先退出交互会话。不要同时使用两个执行者写同一线程。

## MCP 接入

先手动完成 `init`、`doctor` 和本机探针，再将以下示例配置合并到所需 Codex 配置范围。工具不会自动写配置。按实际绝对路径替换：

```toml
[mcp_servers.codex_subchats]
command = 'C:\实际路径\python.exe'
args = ['C:\实际路径\codex-subchats\subchats.py', '--state', 'C:\Users\实际用户\AppData\Local\codex-subchats', 'mcp']
```

MCP 提供五个工具：

| 工具 | 用途 |
| --- | --- |
| `subchat_start` | 创建独立会话，接收 cwd、完整任务、request_key，可选原线程 UUID |
| `subchat_send` | 向原子会话派发下一轮任务 |
| `subchat_status` | 读取状态、结果和通知状态 |
| `subchat_cancel` | 请求停止正在执行的子任务 |
| `subchat_list` | 查看最近 100 轮任务 |

MCP 不提供任意 shell 执行接口；子任务通过已配置 Codex CLI 执行。不会默认安装或注入 Skill。主代理派发后应结束当前回合，等待宿主消费通知；MCP 通知本身不是唤醒机制。

## 状态与恢复

| 状态 | 实际含义 |
| --- | --- |
| `pending` / `running` | 已登记／worker 正在执行；不能据此证明进程现在仍存活 |
| `completed` | CLI 退出码为 0，准确线程及单个 `turn.completed` 已核对；仍需复核任务质量 |
| `failed` | 启动、CLI、事件协议或恢复身份核对失败 |
| `cancelled` | 子进程已终止或未启动；不回滚文件改动 |
| `needs_attention` | 进程终止未确认，保留目录占用 |
| `interrupted` | 操作者确认孤儿任务已停止后释放占用 |
| 通知 `ready` | 已持久化，尚未尝试发送 |
| 通知 `sending` | 正在发送，或发送进程异常中断、结果未知 |
| 通知 `queued` | 已收到匹配原线程的队列确认；不是模型执行证明 |
| 通知 `ambiguous` | 未收到可靠确认，不自动重试 |

```powershell
python .\subchats.py --state $subchatsState cancel 'RUN_UUID'
python .\subchats.py --state $subchatsState reconcile
```

正常完成由对应 worker 立即投递，不需要常驻轮询主模型。MCP 关闭不会主动取消 worker；系统重启或宿主管理的进程清理仍可能结束任务。`reconcile` 仅补发 `ready` 通知，不重放任务，不重试 `sending/ambiguous`。需要先检查原会话再处理不确定通知；原型没有「盲目重试」命令。

如果 worker 确实已消失，先检查它及 Codex 子进程树均已停止，再运行：

```powershell
python .\subchats.py --state $subchatsState resolve-stopped 'RUN_UUID' --confirm-stopped
```

这会保留结果、尝试恢复已记录的 Thread ID，并释放工具占用。不会自动重新执行未完成的任务。随后可以向原子会话 `send` 明确的恢复指令。

## 范围和限制

- 并发保护仅覆盖同一 state 目录下本工具登记的任务，拒绝同一会话和相互包含的 cwd。不会锁住用户编辑器或原主代理；需约定写入归属。
- 使用本地文件系统存放 state；默认位于用户个人目录。日志含任务内容和模型输出，不要提交到仓库或放在共享目录。原型不配置 Windows ACL。
- 用户原生 Windows 环境和 IDE MCP 尚待本机验证。公开源码已发布；提交 [`025cd31b`](https://github.com/lengmh/codex-subchats/commit/025cd31b11c878e992cda43a0b8b18e5b889a93c) 的 [Windows/Linux CI](https://github.com/lengmh/codex-subchats/actions/runs/39434388406) 已通过 Python 3.11/3.13 四项矩阵，覆盖替身传输测试、wheel 构建和安装入口。CI 不证明真实模型或 VS Code 自动唤醒可用，外部自动代码审查尚未确认完成。
- Linux/Remote-SSH 原则上在拥有原 IDE 会话的同一远端运行 worker/MCP/queue。跨本机—远端转发不在本轮范围内。
- 不修改 Codex 数据库、不抢占原主会话 writer、不在 queue 失败后偷偷改用 `exec resume` 唤醒主线程。
- 模型字段是请求配置，不能证明自定义网关实际路由到哪个模型。按用户 provider 的响应和后台记录复核。

## 测试

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

Linux：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。

结果与覆盖边界见 [测试报告](docs/test-results.md)，实现关系与后续验收门禁见 [架构说明](docs/architecture.md)。
