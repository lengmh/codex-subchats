# 测试结果与未验证范围

日期：2026-10-20。以下本地测试记录来自首次交付，测试环境为 Linux 云端、Python 3.12.14；后续远程 CI 结果见文末。

## 已执行

命令：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。

**15 项通过，0 项失败。** 完整输出见 [test-output.txt](test-output.txt)。另通过 Python 编译检查、源码入口 `--help` 和本地 wheel 构建。

这些测试使用真实 Python 后台进程和 SQLite，但 Codex 由 `fake_codex.py` 替代。没有调用真实模型，也没有模拟「IDE 自动执行成功」状态。

| 验证项 | 结果 |
| --- | --- |
| 三轮创建/恢复/完成/队列确认，准确子 Thread ID 与模型参数 | 通过；传输替身链路 |
| 并发提交相同 request_key，只有一次实际执行 | 通过 |
| 重叠目录与同会话执行预留 | 通过对应路径 |
| CLI 失败、缺失 turn.completed 不记成功 | 通过 |
| 恢复返回其他 Thread ID，拒绝并保留原身份 | 通过 |
| 运行中取消进程，不再通知 | Linux 通过 |
| 主进程退出后仍忽略 SIGTERM 的后代进程继续写文件 | 已复现并修复；Linux 回归通过 |
| outbox 重开后投递，多个投递者只有一个发送 | 通过 |
| ambiguous/sending 不自动重试 | 通过 |
| 孤儿任务保留占用，不自动重放 | 通过 |
| doctor 不声称模型或宿主已验证 | 通过 |
| 探针只接受准确原线程的助手回复，仍不伪造自动执行 | 通过 |
| MCP 关闭后后台任务继续完成并通知 | Linux 通过 |
| 中断后从事件恢复 Thread ID，null 身份拒绝 | 通过 |
| 延迟探针在发送前取消 | 通过 |

首轮 12 项测试发现 detached Popen 对象回收警告，已增加后台回收线程并重跑通过；后续增加两项针对身份恢复和探针取消的验证。首次创建测试文件时路径写错，发现 0 项测试，已纠正且不计为通过。

## 首次交付时未执行，不计入验收

- 用户原生 Windows 启动、取消、Unicode 和 PowerShell 检查脚本。
- 真正 Codex CLI 参数兼容、认证、GPT-6.1 Sol / Astra 可用性及自定义 provider 路由。
- VS Code IDE 原线程自然结束后的自动唤醒。
- 三轮真实主子模型闭环及原 IDE 复核。
- IDE 切换聊天、窗口重载、Remote-SSH 断连后的宿主生命周期。
- 当时未执行 GitHub Actions；后续已发布公开仓库并运行远程 CI，见文末。

结论：传输与状态原型已通过本环境有限测试。P0 宿主门禁、P1 正式可用性和 P2 真实验收仍未通过。下一步按 local-acceptance.md 执行本机探针；不需要先做更多替身测试。

## 公开仓库准备复核

本地复核发现 Linux 取消时仅等待主进程，可能遗漏忽略 SIGTERM 的后代。新增最短回归先复现失败，再修复为对私有进程组补发 SIGKILL。最终 15 项测试通过。此轮是本地源码复核，不是外部自动审查；当时远程 CI 和自动审查尚未执行。

## 公开发布后的远程 CI

2026-10-20：[公开仓库](https://github.com/lengmh/codex-subchats)已发布。首次 CI 在 Windows / Python 3.11 的测试目录清理阶段遇到 WinError 32：MCP 派生 worker 已写入终态，但日志文件尚未关闭。测试清理现仅对该 Windows 共享文件占用错误限时等待，持续占用或其他错误仍会失败；未修改运行时功能。

修复提交 [`025cd31b11c878e992cda43a0b8b18e5b889a93c`](https://github.com/lengmh/codex-subchats/commit/025cd31b11c878e992cda43a0b8b18e5b889a93c) 的 [CI 运行 39434388406](https://github.com/lengmh/codex-subchats/actions/runs/39434388406) 已完成，结论为 success：

- Ubuntu / Python 3.11、3.13：测试、wheel 构建及安装入口检查通过。
- Windows / Python 3.11、3.13：测试、wheel 构建及安装入口检查通过；POSIX 进程组回归按平台跳过。

这些测试仍使用合成 Codex 替身，不调用真实模型。用户本机、真实 VS Code 自动唤醒、三轮主子模型闭环及 Remote-SSH 生命周期尚未验收。外部自动代码审查尚未确认完成，不以本地复核或 CI 成功代替。
