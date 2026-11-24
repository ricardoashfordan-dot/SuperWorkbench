# SuperWorkbench 协作交接

## 当前接手

| 状态 | 执行者 | 任务与分支 |
| --- | --- | --- |
| 待审查与 UI 接入 | AGY（Antigravity） | 在基于 `main`（`3b90eb1`）的 `feat/skill-ecosystem` 上审查 Skill 生态后端和内置技能库，并接入前端交互。 |

首轮只读审查针对公开版 `v1.0.1`（`2a1bdf0`）。实现改动已迁到独立修复分支。PR #2 的 `feat/adapter-hardening` 仍指向 `f0dd79e`。

## 协作记录

| 日期或阶段 | 执行者 | 实际贡献 | 验证与交接 |
| --- | --- | --- | --- |
| Codex 加入前 | 项目作者、Antigravity | 共同完成项目开发，项目已在 GitHub 开源。 | 据项目作者说明记录为共同贡献，具体分工可由当事人补充。 |
| 2026-11-23 | Codex | 对公开版完成第三方只读审查，整理出下表四项发现及验收建议。 | Codex 静态核对源码和已有测试用例，未启动服务或运行测试。 |
| 2026-11-23 | Codex | 按项目作者提出的协作方式新增 `HANDOFF.md`，登记参与者、审查基准和待办。 | 文档交接。四项代码修复均待认领。 |
| 2026-11-23 | Codex | 修复 Reviewer 流水线结果和 Godot 质检判定。改动在 `workbench/runner.py`、`workbench/presets.py`、`workbench/server.py`、`workbench/static/app.js` 和 `tests/test_workbench.py`。 | Codex 运行全部 13 项 Python 测试并通过。Node 语法检查与聊天卡片渲染检查通过。Godot 判定使用模拟自检和磁盘证据验证，真实 Godot 运行待复核。 |
| 2026-11-23 | AGY | 审查首轮改动和交接文档，确认整体逻辑、安全性和 13 项原分支测试通过。指出分支隔离、真实 Godot 延迟字段、展示精度和中止退出码四项问题。 | 据项目作者转述。使用第 134 轮已有数据发现了延迟字段兼容问题。 |
| 2026-11-23 | Codex | 从 `main` 创建 `fix/reviewer-and-godot-gates` 并迁移本轮文件。补齐 smoke 延迟回退，两处指标展示保留最多两位小数，策划和执行中止统一记录 `130`。 | 新分支 13 项 Python 测试、Node 语法检查、门禁面板检查和 `git diff --check` 均通过。只读核验第 134 轮已有数据，`233.54 FPS`、`26.04 ms`、BO3 通过，总门禁通过。 |
| 2026-11-24 | Codex | 在 `feat/skill-ecosystem` 实现分类与标签、Gemini/DSH 技能发现、安全本地导入、远程预览和导入、导出，扩充至 8 个内置技能。 | 标准库检查、28 项单测和 `git diff --check` 通过。新增远程用例均使用模拟 HTTP，本地路径用例覆盖符号链接或 Windows 目录联接。 |

## Skill 生态第一阶段交接

技能列表每项新增 `category`（字符串，默认 `general`）和 `tags`（字符串数组，默认 `[]`）。本机 Gemini 和 DSH 来源分别为 `ext-gemini`、`ext-dsh`，均为只读。新建技能可选传入 `category` 和 `tags`，标签接受数组或逗号分隔的字符串。

| `POST /api/skills` 的 `action` | 请求字段 | 成功响应 |
| --- | --- | --- |
| `preview_url` | `url` | `ok` 与 `skill`。技能包含 `name`、`description`、`category`、`tags`、`body`、`resolved_url`、`byte_size`。此操作不写盘。 |
| `import_url` | `url` | `ok`、`snapshot` 与 `skill`。技能包含 `id`、`slug`、`path`、`name`、`resolved_url`。导入后全局启用。 |
| `export` | `id` | `ok` 与 `skill`。技能包含 `id`、`slug`、`name`、`filename`、`content`。文件名为 `SKILL.md`。 |

AGY 接入时先展示预览正文和最终 URL，由用户确认后调用导入。导入会重新下载并校验，用户需要固定预览和导入内容时可使用指向同一提交的 URL。下载仅限允许的 GitHub HTTPS 域名，最多重定向 3 次，总时限 8 秒，正文上限 128 KB。失败响应沿用 `{ok: false, error}`。前端可从 `snapshot` 刷新导入后的技能列表，并用导出的 `filename` 与 `content` 生成下载文件。

## Reviewer 与 Godot 审查记录

- **Reviewer 结果。** 成功才显示“质检完成 → 请验收”。引擎失败保留退出码和回复，异常记录原因，用户中止返回退出码 `130`。聊天卡片显示结果标题和正文。自动接力和批准后接力共用这条执行链路。
- **Godot 质检。** 手动 DSH 核验和自动接力均使用自检对应的工作区及轮次，烟雾自检失败后停止质检。现有自检记录若缺少工作区归属，需要重新自检。请复核跨工作区切换以及旧记录重新自检后的表现。
- **证据来源。** 输入延迟优先取桌面 JSON 的 `input_latency_ms`，其次取 `ROUNDN_REPORT.md` 中明确标注的延迟值，最后取同轮最新一批 `*smoke*.json` 中所有有效 `movement_ms` 和 `jump_ms` 的最大值。BO3 读取同批用例的 `bo3_pass`。指标缺测显示“未测”，总门禁无法通过。
- **边界复核。** 帧率和延迟用原始精度判定，聊天与门禁面板显示最多两位小数。低于 60 的帧率若显示精度触及阈值，呈现为 `< 60 FPS` 并标记未达标。策划和执行中止时，聊天事件标题与任务退出码均为 `130`。
- **复验命令。** `python -m unittest discover -s tests -v`、`node --check workbench/static/app.js`、`git diff --check`。独立审查和真实 CLI、Godot 界面验收由 AGY 或项目作者补记。

## 待认领的修复

| 项目 | 公开版中的发现 | 建议验收方式 |
| --- | --- | --- |
| CLI 角色指令 | 本地 CLI 启动时没有收到已配置的角色系统提示词。见 `workbench/runner.py`。 | 从正常任务入口启动模拟 CLI，检查实际收到的角色指令与用户任务，再用已安装的 CLI 验证一次。 |
| 聊天历史截断 | 所有工作区共用最近 400 条消息，达到上限后新增消息 ID 会重复。见 `workbench/server.py`。 | 在两个工作区交替产生超过 400 条消息，重启后核对两边早期记录仍可读取、新消息 ID 唯一，并用旧数据副本验证兼容性。 |

## 每轮如何交接

1. 开工时先读最近记录并查看 Git 状态，在“当前接手”登记执行者、任务范围和分支。同一时间由一方编辑，保留上一位的未提交改动。
2. 收工时在“协作记录”末尾追加一行，写清谁实际改了什么。已提交的改动附短提交号或公开 PR，未提交的改动列仓库相对路径。
3. 记录谁验证了什么、结果如何。仅做静态检查、尚未运行的测试和仍需人工验收的项目分别标明。提出建议、完成实现和完成验收可分别署名。
4. 更新“当前接手”，注明下一位执行者或标为“待认领”，留下可直接开始的下一步。公开记录仅使用仓库相对路径、测试名、提交号或公开 PR，省略个人路径和凭证。
