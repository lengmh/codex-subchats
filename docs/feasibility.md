# P0 可行性报告

核对日期：2026-10-20。

## 当前判定

**源码层面存在原线程自动开始新回合的路径；用户 Windows VS Code 自动唤醒仍未验证。P0 保持待本机验证，P1/P2 不宣称完成。**

本轮交付可运行的实验验证原型，使下一步无需重新搭建派发和取证逻辑。没有把 Desktop、通用 App Server 或替身进程结果当成 VS Code 的测试结论。

## 三种能力分别判断

| 能力 | 证据与结论 |
| --- | --- |
| 消息入队 | 官方 CLI 文档提供 `codex queue --thread ... --message ...`。源码返回消息 ID 和线程 ID。只能证明接受。 |
| 会话恢复 | `exec resume` 继续准确 UUID 的独立 CLI 会话。App Server 的 `thread/resume` 加载会话，`turn/start` 才开始新的模型回合。不能把恢复等同于原 IDE 自动执行。 |
| 自动模型执行 | 当前官方 queue extension 在已加载线程空闲时调用 `start_turn_if_idle`。依赖宿主拥有该线程、队列服务已安装及线程状态允许；用户 IDE 实测仍缺失。 |

## 官方源码核对

固定版本：`openai/codex@e18a20d6eb6f5ede32a69fb56e3fe276d5e9d914`。

- [queue_cmd.rs](https://github.com/openai/codex/blob/e18a20d6eb6f5ede32a69fb56e3fe276d5e9d914/codex-rs/cli/src/queue_cmd.rs)：命令参数和显式远端选项。
- [session_queue_commands.rs](https://github.com/openai/codex/blob/e18a20d6eb6f5ede32a69fb56e3fe276d5e9d914/codex-rs/tui/src/session_queue_commands.rs)：发现共享 server，发送 `thread/queue/add`；拒绝会造成独立 server 写入的 `--no-daemon` 组合；生成本次 client message ID。
- [queue service](https://github.com/openai/codex/blob/e18a20d6eb6f5ede32a69fb56e3fe276d5e9d914/codex-rs/ext/queue/src/service.rs)：`watch_external_messages` 观察外部队列；`wake_if_loaded` 只处理已加载线程；`on_thread_idle` 对中断原因不自动启动；`dispatch_if_idle` 开始下一回合。
- [App Server extensions](https://github.com/openai/codex/blob/e18a20d6eb6f5ede32a69fb56e3fe276d5e9d914/codex-rs/app-server/src/extensions.rs)：在提供 queue_service 时安装队列扩展。
- [exec CLI](https://github.com/openai/codex/blob/e18a20d6eb6f5ede32a69fb56e3fe276d5e9d914/codex-rs/exec/src/cli.rs)：JSONL、stdin prompt、输出文件、恢复入口。

上述事实支持「条件成立时可行」，不足以支持「当前 Windows IDE 已可用」。公开源码树没有包含本次核对所需的 VS Code 扩展前端生命周期实现，也没有对应的真实 IDE 验收证据。结束回合、切换聊天、关闭面板、窗口重载是否卸载线程，必须分别实测。

## 参考项目审查

| 项目 | 固定版本及所读源码 | 可复用思路 | 不能推导的结论 |
| --- | --- | --- | --- |
| wake-codex | `68ebbecb8b2e40394d5beb4b067d82f812245c42`；README、scripts/wakecodex.py、docs/verification.md | 后台完成事件、准确队列确认、发送不确定时停止重试 | 验证文档仅确认特定 Windows Desktop + CLI 0.159.2；没有确认 VS Code |
| codex-exec-subagents | `6c8460f402d9e887230ec7a2edf4c63b272240ef`；README、worker.py、runner.py | 独立 exec、准确恢复 ID、保存事件和结果、验证请求配置 | README 当前将 native Linux 列为支持平台；不能当作 Windows 已验证实现 |

参考项目：[Wake Codex 验证文档](https://github.com/rotcev/wake-codex/blob/68ebbecb8b2e40394d5beb4b067d82f812245c42/docs/verification.md)、[独立执行 runner](https://github.com/antoinezambelli/codex-exec-subagents/blob/6c8460f402d9e887230ec7a2edf4c63b272240ef/src/codex_exec_subagents/runner.py)。本项目未引入它们的运行时依赖，也未复制其源码。

## 为什么暂不切换 App Server 或 SDK

CLI 已提供独立执行、恢复和队列入口。单独新起 App Server 并 `thread/resume` 不能保证控制到原 IDE 的在内存会话；它可能成为另一个 writer，不能作为失败时的隐式替代。

若本机 queue 存在但原线程不消费，先核对原宿主使用的二进制、版本、home、共享 server 和线程状态。只有这些证据指向接口缺口时，再评估通过受支持的同一 server 端点调用。SDK 能管理自己启动的线程，不会自动解决原 IDE 所有权问题。

## 最小替代方案

若 queue 缺失或 IDE 始终只显示待发送消息：保留独立子会话执行和结果持久化；主代理结束回合。任务完成后由用户在原 Astra 会话发送一次「读取 RUN_UUID 的结果并继续」。这减少一次自动唤醒能力，其余会话、恢复和结果流程不变。

如果必须完全自动，下一候选是显式由工具管理的 Astra CLI/App Server 主会话；它会改变主会话宿主，不是本轮用户要求的原 VS Code 自动唤醒。未经本机验证，不将其列为已实现。

## 官方文档

- [CLI 命令](https://developers.openai.com/codex/cli/reference)
- [非交互模式](https://developers.openai.com/codex/non-interactive-mode)
- [App Server](https://developers.openai.com/codex/app-server)
- [IDE 扩展](https://developers.openai.com/codex/ide/features)
- [GPT-6.1 Sol 模型](https://developers.openai.com/api/docs/models/gpt-6.1-sol)：模型 ID 文档存在，不代表用户自定义 provider 已支持。
- [MCP stdio](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) 与 [初始化](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)。
