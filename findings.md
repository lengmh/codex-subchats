# 研究发现

2026-10-20：当前环境无可调用 Codex CLI；不可据此判断用户 Windows 环境能力。

参考仓库已固定快照：wake-codex 68ebbecb8b2e40394d5beb4b067d82f812245c42；codex-exec-subagents 6c8460f402d9e887230ec7a2edf4c63b272240ef。
wake-codex README 明确 queued 仅表示队列确认，不证明模型执行；自动消费依赖拥有会话的宿主仍可用。
codex-exec-subagents README 当前支持 native Linux，不能直接当作 Windows 支持的证据。
官方模型文档存在 gpt-6.1-sol，但这不证明用户自定义 provider 能调用。

官方源码快照：openai/codex e18a20d6eb6f5ede32a69fb56e3fe276d5e9d914。
queue_cmd.rs：queue 支持 --thread/--message，当前源码亦支持显式 remote endpoint。
ext/queue/src/service.rs：watch_external_messages 观察外部队列变化；wake_if_loaded 仅对已加载线程唤醒；dispatch_if_idle 调用 start_turn_if_idle；Interrupted 不自动启动。
因此，原宿主保留线程且安装/启用相同队列服务时存在自动执行路径，但这不是当前用户 IDE 二进制和生命周期的实测证据。
公开源码树未包含 VS Code 扩展前端实现；不能从通用 app-server 推断 IDE 每种状态都保留线程。

发布参考：lengmh/v2rayN-Monitor，2026-10-20 main 快照 2ca6427bb8156d4084a12b9031549681e677283b。public，main，MIT，Issues/Projects/Wiki 开启，Discussions 关闭；允许 merge/squash/rebase，auto merge 关闭，合并后不自动删分支。main-basic-protection 规则只禁止删除和非快进更新，无 bypass，无强制审批数量。CI 为 Windows/Linux，contents: read，fail-fast: false；有 bug/PR 模板和 SECURITY.md。以上是参考数据，不将其他仓库 AGENTS 的项目阶段和历史授权复制到本项目。
