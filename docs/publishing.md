# 公开仓库发布配置

目标：`lengmh/codex-subchats`，公开源码，当前保持 `0.1.0a1` 实验阶段，不创建正式 Release。

配置参考：2026-10-20 读取的 `lengmh/v2rayN-Monitor` 实际设置。

| 设置 | 拟应用值 |
| --- | --- |
| 默认分支 | main |
| 可见性 | public |
| 许可证 | MIT |
| 描述 | Local-first independent Codex CLI sessions, durable task state and queue notifications for VS Code orchestration. Experimental. |
| Issues / Projects / Wiki | 开启，与参考仓库一致 |
| Discussions | 关闭 |
| Merge commit / Squash / Rebase | 允许 |
| Auto merge / 自动删除分支 | 关闭 |
| main-basic-protection | main 禁止删除、禁止非快进更新，无 bypass |

源码包含适配本项目的 AGENTS.md、SECURITY.md、Bug/PR 模板及 Windows/Linux CI。CI 使用只读 contents 权限，Python 3.11/3.13，包含传输测试、wheel 构建和安装入口检查，不调用模型。

## 执行顺序

1. 创建公开仓库并准备 main 基础提交。
2. 提交实验原型源码，执行对应提交的 CI。
3. 核对精确提交的检查结果，修复确认存在的问题；可用的自动代码审查单独核验。
4. 核对仓库最终状态及上述基础 main 规则。

自动代码审查依赖账户已有 Codex/GitHub 审查集成；不能把发布一条审查请求当作审查已完成。不新增付费密钥或第三方服务。若集成没有覆盖新仓库，明确报告实际阻碍。

## 当前执行状态

2026-10-20：已创建公开仓库 [lengmh/codex-subchats](https://github.com/lengmh/codex-subchats)，默认分支为 main。源码上传前在 Linux / Python 3.12.14 重跑 15 项测试，全部通过；源码语法及命令入口检查通过。远程 CI 结果以对应提交的 GitHub Actions 为准，自动代码审查尚未确认完成。上表是目标配置，不代表所有设置均已应用。仍未验证原 Windows VS Code 自动唤醒，不创建正式 Release，也不发布 PyPI 包。
