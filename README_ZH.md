<p align="center">
  <img src="workbench/static/icon.svg" width="68" height="68" alt="Super Workbench 图标" />
</p>

<h1 align="center">Super Workbench</h1>

<p align="center">
  <strong>零依赖、零额外 API 账单的本地多智能体协同工作台</strong><br/>
  <a href="README.md">English</a> · <a href="README_ZH.md">简体中文</a> · <a href="AGENT_INSTALL.md">AI 一键代装指南</a> · <a href="COMPATIBILITY.md">CLI 兼容性矩阵</a> · <a href="ROADMAP.md">演进路线图</a>
</p>

| Obsidian 暗夜深色 | Muse 纸白浅色 |
| :---: | :---: |
| ![Obsidian Dark](docs/assets/preview-dark.png) | ![Muse Paper Light](docs/assets/preview-light.png) |

> **让你的 AI 帮你一键安装（推荐）**：直接把下面这句话发给你的 Claude Code / Codex / Cursor / Antigravity：
> ```text
> 请阅读 https://github.com/ricardoashfordan-dot/SuperWorkbench/blob/main/AGENT_INSTALL.md ，先体检我电脑的环境并告诉我需要准备什么，然后帮我安装并启动 Super Workbench。
> ```

在一个极简、冷静的 Muse / Codex / Linear 风格界面中，把你本机已经装好的 AI 命令行工具（**Antigravity `agy`**、**OpenAI `codex`**、**Claude Code `claude`**、**Gemini CLI `gemini`**、**DSH**）以及 **本地 Ollama / 任意 OpenAI 兼容 API** 串成一条顺手的协作流水线——同时服务于 **软件工程开发** 与 **AIGC 漫剧 / 短片制片**。

> **核心理念**：直接复用你已有的本地 CLI 订阅额度。只有 **核心执行（Builder）** 岗位需要绑定一个可改文件的本地 CLI，**策划（Planner）** 与 **质检（Reviewer）** 可以自由绑定 CLI、免费本地 Ollama 或任意云端 API。

---

## 核心特性

- **零重型依赖**：后端仅使用 Python 3 标准库，前端为零构建的模块化 `index.html + app.css + app.js`；无需 Docker、Redis、数据库或前端编译环境，下载即用。
- **三角色自由协作（策划 → 执行 → 质检）**：
  - 实时流式输出与可折叠的执行步骤 Trace，拒绝满屏日志噪音。
  - 46px 极简纵向纸飞机交接微轨，一眼看清当前接力位置。
  - **极简执行前审批门禁（可选）**：在 `Settings → 角色与引擎` 中一键开关；开启后「全自动流转」会在策划出方案后暂停，并在输入框上方浮出一条安静的单行确认栏，点击「批准执行」才开始动手改文件。
- **多工作空间 & 同空间多对话 & 一键压缩上下文**：
  - 支持 `通用研发`、`Web 前端`、`Python`、`AIGC 制片空间`、`Godot 游戏开发` 等多种空间预设，互不干扰。
  - 每个工作空间支持建立多个独立对话线程，长对话可一键浓缩为长期记忆摘要，自动注入后续每轮上下文。
- **Codex / AGY 风格 `+` 多模态输入框**：
  - 点击 `+` 即可上传图片、本地文件或挂载 `/技能`，支持 `Ctrl+V` 直接粘贴截图与拖拽上传。
- **零门槛可视化 Settings 设置中心**：
  - **技能（Skills）**：4 层自动发现（内置、工作台技能库、项目 `.agents/skills/` 以及只读读取本机 `~/.codex/skills`、`~/.gemini/antigravity/skills`、`~/.claude/skills`），零 YAML 表单新建，自动注入所有引擎。
  - **外部工具（MCP）**：内置 Playwright 浏览器、GitHub、Figma、ComfyUI、本地目录等 1 键零 JSON 模板，并支持一键同步到本机已装的 `agy` / `codex` / `claude` CLI。
  - **角色与引擎**：自动探测本机 CLI 与 Codex 模型列表，并提供左下角 1 秒快切模型弹窗；一键接入 Ollama、DeepSeek、OpenRouter 或自定义 CLI。
- **可折叠右侧 Inspector 抽屉**（默认收起，保持画布纯净）：
  - **终端日志**：完整 CLI 实时输出，带智能滚动锁（上翻查看历史时绝不强制拽回底部）。
  - **Live Git Diff 与源码审查**：有 Git 时展示分支、变更文件与红绿 Diff；无 Git 时自动降级为带行号的源码预览。
  - **AIGC 漫剧 / 短片审片室**：自动初始化并追踪 5 级制片目录（`01_script` → `05_output`），内置分镜网格画廊与支持任意拖动进度条（HTTP `206 Range`）的 HTML5 音视频审片播放器。
- **Obsidian 暗夜 ⇄ Muse 纸白双主题**：精细打磨的排版、留白与极简图标体系。

---

## 整体架构

```mermaid
flowchart LR
    U["制作人 / 开发者"] --> UI["双主题极简画布\n(workbench/static/index.html)"]
    UI <--> API["本地 REST 与流式媒体服务\n(workbench/server.py · 127.0.0.1:8765)"]
    API --> JM["跨平台任务调度器\n(workbench/runner.py)"]
    JM --> P["策划槽位 Planner\n(AGY / Claude / Ollama / API)"]
    P -. "可选 · 极简审批门禁" .-> B["执行槽位 Builder\n(Codex / Claude / AGY CLI)"]
    B --> R["质检槽位 Reviewer\n(DSH / CLI / API)"]
    API --> SK["4 层技能引擎\n(workbench/skills.py)"]
    API --> MCP["可视化 MCP 注册与 CLI 同步\n(workbench/mcp_manager.py)"]
    API --> PR["行业插件与审片扫描\nGit Diff · AIGC 审片室 · Godot\n(workbench/presets.py)"]
```

---

## 30 秒快速启动

### 环境要求
- **Python 3.10+**（纯标准库，无需 `pip install` 任何包）
- 至少安装并登录 1 个本地 AI CLI（如 `codex`、`agy`、`claude`、`gemini`），**或** 配置本地 Ollama / OpenAI 兼容 API。

### 启动方式

```bash
git clone https://github.com/ricardoashfordan-dot/SuperWorkbench.git
cd SuperWorkbench
python start.py
```

Windows 用户可直接双击 `Start-SuperWorkbench.cmd`，macOS / Linux 用户可执行 `./start.sh`。

启动后浏览器访问 **`http://127.0.0.1:8765`**（默认仅监听本机回环地址）。

---

## 安全与隐私边界

- **本地接口会话鉴权 + Host / Origin 防护**：
  - 所有 `/api/*` 接口均强制校验本地会话凭证（自动生成并保存在 `.workbench/session.token`，也支持通过环境变量 `SUPER_WORKBENCH_TOKEN` 指定）。通过桌面图标或 `start.py` 打开时会自动种下 `HttpOnly; SameSite=Strict` Cookie 并在地址栏隐藏 `?token=`。
  - 全路由校验 `Host`（防御 DNS Rebinding 攻击），非 GET 请求校验 `Origin`（阻止跨站恶意网页静默调用本地接口）。
  - **为什么直接手敲地址有时会看到 403？** 当你用从未授权过的新浏览器直接访问裸地址 `http://127.0.0.1:8765` 时，因尚未种下本地会话 Cookie，接口会主动拦截返回 `403`；只需双击桌面图标或从终端打印的 `/?token=...` 链接打开一次即可恢复。
  - **边界说明**：此机制用于阻止浏览器中打开的其他恶意网页操控本机工作台，**无法**防御已在你同一操作系统用户下运行的本地恶意软件。脚本或外部 Agent 可从 `.workbench/session.token` 读取凭证并在请求头携带 `X-Workbench-Token`。
- **仅限本机访问**：默认严格绑定 `127.0.0.1`，不向公网暴露任何端口。
- **个人数据完全隔离**：所有聊天记录、工作空间路径、API 密钥、MCP 环境变量、会话凭证与上传附件均存放在 `.workbench/` 目录下，已在 `.gitignore` 中排除，绝不会随代码提交泄漏。
- **安全执行策略**：调用本地 CLI 仅使用标准工作区沙箱权限（绝不注入绕过沙箱的危险参数），前端快照自动对密钥脱敏。
- **非破坏性空间移除**：从侧栏移除工作空间绝不会删除你硬盘上的项目文件。

---

## 参与贡献

欢迎提交新的内置 `SKILL.md` 模板、MCP 工具预设或行业工作流插件！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 开源协议

[MIT](LICENSE)
