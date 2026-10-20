# codex-subchats 任务计划

## 目标
轻量本地工具：独立 Codex CLI 子会话、准确恢复、后台完成通知，并证明原 VS Code 主会话自动继续执行。

## 阶段状态
- P0 partial / awaiting_local_validation：官方接口和两个参考项目源码已核对；源代码存在自动执行路径；当前用户 IDE 生命周期未实测。
- P1 prototype_ready / gated：实验原型包含 CLI、后台 worker、MCP、持久化状态、恢复、通知、取消；正式最小版本仍受 P0 门禁约束。
- P2 transport_verified / awaiting_live_acceptance：15 项有限传输测试通过；真实 Windows 和连续三轮主子模型闭环待执行。
- 交付 complete：源码、安装说明、架构说明、P0 报告、本机验收说明和测试结果打包。

## 已作决定
- Python 标准库，免安装源码入口；不依赖参考项目运行时。
- 每任务一个后台 worker 兼完成监听与首次投递，不引入常驻 HTTP 服务。
- 原生 queue 负责向主线程通知，绝不以 exec resume 隐式接管原主线程。
- 队列接受、助手回复被观察、自动执行验收分别记录。
- 主模型在 IDE 选择；子模型在工具配置，不自动覆盖主会话模型。
- 未确认的发送不重试，未知执行不重放。

## 验收门禁
1. 用户本机 doctor 和单次子模型调用。
2. 原 VS Code 会话自然结束后，探针无需人工操作产生原线程新回复。
3. 连续三轮真实派发—完成—唤醒—复核。
4. 有限 Windows / MCP 断连 / 重载 / 并发取消检查。

## 环境限制
当前云端 Linux 没有 Codex CLI，没有用户 Windows 或 IDE 的访问权限；未改变用户全局配置。公开仓库已创建，实验源码发布不代表真机验收通过或正式 Release。

## 错误与修复
- 测试文件首次使用重复目录前缀，未写入；纠正后实际运行14项测试。
- detached Popen ResourceWarning：增加后台回收线程，重跑通过。
- 中文文档技能附属云资源读取失败：使用对应本地技能文件完成读取。

## 公开仓库发布（用户已授权）
- complete：参考 v2rayN-Monitor 的 main、MIT、模板、CI 与基础保护规则，准备公开源码。
- complete：创建 lengmh/codex-subchats（public），默认分支 main。
- in_progress：上传实验源码并核对对应提交的 CI。
- pending：核验自动代码审查是否可用及是否完成；仓库设置按实际应用结果核对。
