# SuperWorkbench 协作交接

## 当前接手

| 状态 | 执行者 | 任务与分支 |
| --- | --- | --- |
| 待合并 | 项目作者 / AGY | `feat/dynamic-roster` 已完成 v1.2 动态 N 角色后端审查、自适应 N 节点微轨 SVG、动态角色胶囊与增删排序 UI，推 PR #12。 |

首轮只读审查针对公开版 `v1.0.1`（`2a1bdf0`）。本轮基线为合入 PR #11 后的 `main`（`6a2d025`）。

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
| 2026-11-24 | AGY | 安全审查 `workbench/skills.py` 与 `workbench/server.py`（SSRF、重定向白名单、路径穿越、符号链接、128 KB 流式限额均通过）；在 `workbench/static/{index.html,app.css,app.js}` 接入分类筛选、标签搜索、GitHub 链接先预览审查再导入、一键导出及双语适配。 | `scripts/check_stdlib_only.py`、28 项单测、`node --check workbench/static/app.js` 与 `git diff --check` 全部通过。 |
| 2026-11-24 | Codex | 在 `feat/workspace-rosters` 实现空间独立阵容、五套场景排班、引擎画像、模型简写和便携预设。新增 3D 美术技能与 Blender MCP 模板。 | 标准库检查、33 项单测和 `git diff --check` 均通过。单测覆盖跨空间审批恢复、无引擎与自定义引擎、预设校验和技能状态隔离。Blender 验证覆盖技能和模板加载。 |
| 2026-11-24 | AGY | 审查 `feat/workspace-rosters` 后端并完成前端接入：主画布「本空间阵容」1 键场景浮层、按需自选推荐技能条、预设 JSON 导出/导入、全局/空间保存切换，全界面清除未安装 `AGY`/`CDX`/`DSH` 假占位并改用真实模型简写头像。 | `scripts/check_stdlib_only.py`、`node --check workbench/static/app.js`、33 项单测与 `git diff --check` 全部通过。 |
| 2026-11-25 | Codex | 在 `feat/mcp-proxy-and-history-scale` 实现远程 Skill 代理开关、三个 MCP 模板、Gemini 同步、连通性自检和聊天历史索引缓存。 | 标准库检查、42 项单测和 `git diff --check` 通过。覆盖双进程及重启读写、同大小文件替换、无归属旧消息、代理切换和 HTTP 模拟自检。 |
| 2026-11-25 | AGY | 审查后端安全边界（不跟随重定向、不泄露凭据、Windows 批处理元字符拦截、多维文件指纹缓存均通过）；接入前端通用设置代理开关、MCP 测连通按钮、Gemini 同步提示与零引擎 3 步首启引导卡片。 | `scripts/check_stdlib_only.py`、`node --check workbench/static/app.js`、42 项单测与 `git diff --check` 全部通过。 |
| 2026-11-25 | Codex | 在 `feat/dynamic-roster` 完成动态角色存储、增删排序、两版预设兼容、自定义角色单发和按序接力。 | 47 项单测通过（原 42 项与新增 5 项），标准库检查和 `git diff --check` 通过。新接力用例使用模拟引擎。 |
| 2026-11-25 | AGY | 审查 v1.2 动态阵容后端并完成前端接入：自适应 N 节点纵向交接微轨 SVG、动态底部角色胶囊、空间阵容浮层与设置页的「+ 添加专家角色 / ↑↓ 调整接力顺序 / 启停 / 删除」交互。 | `scripts/check_stdlib_only.py`、`node --check workbench/static/app.js`、47 项单测与 `git diff --check` 全部通过。 |

## v1.2 动态阵容交接

- `snapshot.roles` 保留所有角色定义。每项带 `builtin`、`enabled` 与从 0 开始的 `order`，停用时 `order` 为 `null`。微轨和发送目标使用 `snapshot.roster`，其顺序等于 `snapshot.roster_order`。
- 内置三角色保留在定义表，可通过保存单个或多个槽位的 `enabled` 布尔值切换参与状态。至少启用一个角色，总定义数最多八个。重新启用的角色排到末尾，之后可排序。默认配置沿用旧版三角色顺序。
- `roles.json` 保留顶层内置字段，新增 `custom_roles` 与 `roster_order`。工作空间自定义结构后保存独立结构，恢复继承时删除空间覆盖。应用场景更新三个内置角色的配置，保留自定义角色与启用顺序。

| `POST /api/roles` 新操作 | 请求字段 | 成功响应 |
| --- | --- | --- |
| `add_role` | `label`，可选 `engine`、`model`、`effort`、`system_prompt`、`insert_before`。默认插在已启用的 `reviewer` 前，`null` 表示追加。 | `ok`、`role`、`roles`、`roster`、`roster_order`、`snapshot`。 |
| `delete_role` | `role_id` | `ok`、`roles`、`roster`、`roster_order`、`snapshot`。 |
| `reorder_roles` | `order`，为当前已启用角色 ID 的完整排列。 | `ok`、`roles`、`roster`、`roster_order`、`snapshot`。 |

以上三项和既有 `save` 支持 `scope`，默认 `workspace`，也可选 `global`。响应顶层的阵容对应写入范围，`snapshot` 对应当前空间。选择新角色时，发送入口为 `POST /api/dispatch` 或 `POST /api/send`，用 `target`（也接受 `role_id`）与 `instruction`。内置消息仍使用 `agy`、`codex`、`dsh` 别名，自定义消息的 `from`、`to` 及运行中的 `live_job.agent` 使用角色 ID。

预设在存在自定义角色、停用项或不同排序时导出 v2，包含 `roster_order` 和各定义的 `enabled`。旧 v1 仍可导入，导入替换当前空间阵容。两个版本均只推荐技能，由用户自行勾选。

流水线保存启动顺序，首角色完成后如需审批，`live_job.pending_approval.remaining_role_ids` 给出待执行顺序。批准后按该顺序继续，使用原线程的历史快照。剩余角色被删除或停用时在该角色处报错。阶段产出链最多 2,400 字符，状态事件沿用 `LOCK`、`WAITING_APPROVAL`、`ERROR` 和 `PIPELINE_DONE`。Godot 只在内置 `reviewer` 是最后一位时运行门禁核验。

## 代理、MCP 与历史读取交接

- `POST /api/settings` 接受布尔字段 `use_system_proxy_for_remote_skills`，可读 `snapshot.settings` 回填开关。默认直连，只有 JSON 布尔值 `true` 开启系统代理。两种模式均沿用 HTTPS 域名白名单、逐跳校验、最多 3 次跳转、8 秒总时限与 128 KB 上限。
- `POST /api/mcp` 传 `{action: "test", name}`，直接返回 `{ok, reachable, transport, detail_zh, detail_en}`。已登记服务的 `ok` 表示自检请求已处理，使用 `reachable` 显示结果。名称不存在时返回 404。响应本身不附带快照。
- stdio 自检只检索可执行文件。HTTP 自检直连端点，总时限 4 秒，先发 HEAD，遇到 405 才用 GET 读取最多 1 KB。收到 HTTP 状态即可判为端点可达，并在说明里展示状态码。自检覆盖网络可达性，跳转目标和服务凭据都不出现在返回结果里。
- `snapshot.mcp.templates` 新增 `fetch`、`context7`、`memory`。Gemini 同步使用用户级配置，Windows 批处理启动器遇到无法安全传递的参数时会返回该 CLI 的失败结果。Gemini 与 HTTP 验证均使用模拟调用。[Gemini CLI MCP 命令参考](https://geminicli.com/docs/tools/mcp-server/#managing-mcp-servers-with-gemini-mcp)
- 历史仍保存为 `messages.json` 数组。读取按文件指纹更新进程内索引，并用工作区和线程定位消息。写入沿用跨进程锁、原子替换和 `messages.sequence.json`；每次写入仍重写 JSON 文件。12,000 条样本中读取目标线程 120 条，100 次平均耗时从全量解析的 11.24 ms 降至缓存命中的 0.25 ms，该数据仅衡量历史读取。

## 工作空间阵容交接

- `snapshot.roles` 是当前工作空间的有效阵容。每个槽位新增 `badge`。空引擎的 `engine`、`model`、`badge` 均为空字符串。`snapshot.engines` 增加 `strength_zh`、`strength_en` 和 `capabilities`。
- `snapshot.scenes` 每项包含 `id`、`label_zh`、`label_en`、`role_labels` 和 `recommended_skills`。用 `active_scene` 显示当前场景，用 `roles_scope` 区分独立阵容与全局继承。
- `roles.json` 顶层的三个槽位继续存放全局配置。工作空间覆盖在 `workspaces[workspace_id]`，恢复继承时删除该条目。单发、流水线和审批恢复都使用任务所属空间的 ID。

| `POST /api/roles` 操作 | 请求字段 | 成功响应 |
| --- | --- | --- |
| 保存（缺省 `action`，也可传 `save`） | 直接传三个槽位对象，或放在 `roles` 下。可传 `scope: "global"`，默认 `workspace`。 | `ok`、`roles`、`snapshot`。 |
| `apply_scene` | `scene` | `ok`、`scene`、`roles`、`reason_zh`、`reason_en`、`recommended_skills`、`snapshot`。 |
| `reset_workspace` | 无额外字段 | `ok`、`roles`、`snapshot`。 |
| `export_preset` | 无额外字段 | `ok` 与 `preset`。预设为 `{version: 1, scene, roles, recommended_skills}`。 |
| `import_preset` | `preset` 对象 | `ok`、`roles`、`active_scene`、`roles_scope`、`recommended_skills`、`snapshot`。字段非法时返回 400。 |

应用场景和导入预设都写入当前空间。`recommended_skills` 取自场景定义，可在界面提示用户自行勾选。导入的引擎不可用时回退到本机可用选项，同时换用对应模型。Blender 模板提供 `uvx blender-mcp`，实际联机需要启用 Blender 端插件。[MCP 项目安装说明](https://github.com/ahujasid/mcp-for-blender#quickstart)

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

此前登记的两项公开版问题（CLI 角色指令、聊天历史截断与 ID 重复）均已在 PR #5（`3b90eb1`）和 PR #8（`773272d`）中完成并合入 `main`。下一轮任务将由 AGY 拆解并登记于此。

## 每轮如何交接

1. 开工时先读最近记录并查看 Git 状态，在“当前接手”登记执行者、任务范围和分支。同一时间由一方编辑，保留上一位的未提交改动。
2. 收工时在“协作记录”末尾追加一行，写清谁实际改了什么。已提交的改动附短提交号或公开 PR，未提交的改动列仓库相对路径。
3. 记录谁验证了什么、结果如何。仅做静态检查、尚未运行的测试和仍需人工验收的项目分别标明。提出建议、完成实现和完成验收可分别署名。
4. 更新“当前接手”，注明下一位执行者或标为“待认领”，留下可直接开始的下一步。公开记录仅使用仓库相对路径、测试名、提交号或公开 PR，省略个人路径和凭证。
