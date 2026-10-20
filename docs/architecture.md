# 架构与实现边界

## 进程关系

主代理通过 MCP 或 CLI 登记任务。工具在 SQLite 事务中登记 Run、预留会话和目录，再启动独立 Python worker，立即返回句柄。worker 启动 `codex exec` 或 `exec resume`，捕获 JSONL、标准错误和最终回复。完成后在同一事务中保存终态及 outbox 事件，然后调用原生 `codex queue`。

原主代理无需保持一个等待回合。worker 使用普通进程检查，不调用模型轮询。原 IDE 是否消费队列并启动 Astra，属于宿主能力；工具不伪造该状态。

本轮采用每任务一个短生命周期后台 worker，它同时负责完成监听和首次通知，避免引入常驻 HTTP 服务。`reconcile` 负责恢复尚未尝试的通知。系统服务、自启动和跨主机代理暂不实现。

## 模块

| 模块 | 职责 |
| --- | --- |
| `core.py` | SQLite 事务、任务预留、后台执行、事件核对、队列投递、探针 |
| `cli.py` | 本地配置、命令行、进程入口和结果读取 |
| `mcp.py` | 五个 stdio MCP 工具；无网络监听端口 |
| `subchats.py` | 免安装源码入口 |
| `Inspect-Host.ps1` | Windows 标准扩展目录的只读版本/二进制候选检查 |

## 身份模型

- Session ID：本工具分配，关联一条独立 Codex 会话和固定配置。
- Thread ID：Codex `thread.started` 返回的 UUID；恢复只用此准确值。
- Run ID：每次 start/send 一轮执行独有。
- request_key：调用者的幂等键。同请求重试不创建新执行。
- parent_thread：原 IDE 主线程的准确 UUID，与子 Thread ID 分开保存。
- message_id：原生 queue 确认返回的队列项 ID，不是模型回合 ID。

主模型在原 IDE 会话配置；子模型由工具参数指定，两者独立。`parent_model_expected` 只用于记录预期，不能通过 queue 更改主模型。这一限制在 CLI 帮助和 README 中明示。

## 完成与通知语义

只有子 CLI 正常退出、事件包含准确身份和单个 `turn.completed` 且没有错误事件，才记 `completed`。这表示一次模型执行完成，不表示代码质量验收通过。

终态和 outbox 同事务保存，避免结果已完成但通知登记丢失。worker 争用 `ready → sending` 的原子更新，只有一个成功者发送。收到匹配线程的确认后才记 `queued`。

在外部发送成功到本地保存确认之间仍有崩溃窗口。CLI queue 自己生成消息 ID，当前适配器无法让重复 CLI 调用共享同一个幂等 ID。因此 `sending/ambiguous` 永不自动重试；不承诺 exactly-once。主代理按 Run ID 识别事件，可减少重复业务处理。

## 并发和恢复

同一 state 数据库以 `BEGIN IMMEDIATE` 串行化任务预留。拒绝同会话或重叠 cwd 的并发任务，包括父子目录；路径先解析符号链接和平台大小写规范。不同本地 state 无共享锁，外部编辑器和原主代理也不受此锁控制。

worker 失联时不根据过期 PID 自动发信号，不主动释放 busy 占用，不自动重跑。`resolve-stopped --confirm-stopped` 仅在操作者确认进程树停止后释放，并从保留的 JSONL 恢复线程身份。随后由明确的 send 开始下一轮。

取消只针对当前 worker 持有的 Popen；Linux 终止进程组，Windows 使用当前存活子进程的 taskkill /T。终止失败保留占用。退出宿主、系统重启、工具进程异常被杀与自然结束是不同情况，不能保证任意子工具都支持可恢复执行。

## 接口与版本

本地 CLI 先以 doctor 读取实际帮助，不固定最低版本号作为能力证明。命令使用 stdin 传提示词、显式子模型和 sandbox，不覆盖 developer_instructions，不用 `--full-auto` 或绕过审批参数。

MCP 使用标准 JSON-RPC 行分隔 stdio，实现 initialize、ping、tools/list、tools/call；协议协商支持 2024-11-05、2025-03-26、2025-06-18，其他版本返回本实现支持的版本，由客户端决定是否继续。没有 MCP sampling 或未经请求的模型调用。

## 原型边界

- Windows 原生路径、进程组和 taskkill 的实际表现待本机测试。
- state 使用本地个人目录；本轮不实现自定义 Windows ACL 管理。
- MCP stdout 只输出协议消息，日志和事件写文件，采用 UTF-8。
- `observe-probe` 仅支持 session_meta/response_item JSONL 格式。它不是 Codex 全版本日志解析器。
- 只读查看通过 show；交互进入子会话使用原生 resume，须避免并发占用。
- 不自动安装 Skill、不改全局配置、不创建公开仓库、不发布版本。
