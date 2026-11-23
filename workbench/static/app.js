const RAIL_Y = { xiu: 30, agy: 106, codex: 182, dsh: 258 };
const ROLE_INFO = {
  xiu: { name: "我", role: "发起人" },
  agy: { name: "Antigravity", role: "策划 · 审计" },
  codex: { name: "Codex", role: "核心主程" },
  dsh: { name: "DSH", role: "独立质检" }
};

let currentMode = "agy";
let currentInspTab = "console";
let lastMsgId = null;
let lastChatSig = "";
let railAnim = null;
let editingWsId = null;
let deletingWsId = null;
let latestSnap = null;

// --- Theme (Obsidian Dark <-> Muse Paper Light) ---
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("sw_theme", theme);
  const btn = document.getElementById("btnTheme");
  if (btn) {
    btn.innerHTML = theme === "dark"
      ? `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>`
      : `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>`;
  }
  document.getElementById("themeOptDark")?.classList.toggle("solid", theme === "dark");
  document.getElementById("themeOptLight")?.classList.toggle("solid", theme === "light");
  const metaTc = document.getElementById("metaThemeColor");
  if (metaTc) metaTc.setAttribute("content", theme === "dark" ? "#0c0d10" : "#f5f4f0");
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(cur === "dark" ? "light" : "dark");
}
applyTheme(localStorage.getItem("sw_theme") || "dark");

// --- Sidebar & Inspector Toggles ---
function toggleSidebar() {
  const sb = document.getElementById("sidebar");
  const collapsed = sb.classList.toggle("collapsed");
  document.getElementById("btnOpenSidebar").style.display = collapsed ? "grid" : "none";
}
function toggleInspector(force) {
  const el = document.getElementById("inspector");
  const isOpen = force !== undefined ? force : !el.classList.contains("open");
  el.classList.toggle("open", isOpen);
  document.getElementById("btnInspector").classList.toggle("active", isOpen);
}
function switchInspTab(tab) {
  currentInspTab = tab;
  document.querySelectorAll(".insp-head .insp-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  document.getElementById("inspConsoleTab").style.display = tab === "console" ? "flex" : "none";
  document.getElementById("inspWorkspaceTab").style.display = tab === "workspace" ? "flex" : "none";
  document.getElementById("inspArtifactsTab").style.display = tab === "artifacts" ? "flex" : "none";
}

// --- Role Slots & Universal Engine Studio Modal ---
function toggleModelPopover(force) {
  const pop = document.getElementById("modelPopover");
  const show = force !== undefined ? force : !pop.classList.contains("show");
  pop.classList.toggle("show", show);
}
document.addEventListener("click", e => {
  const pop = document.getElementById("modelPopover");
  if (pop && pop.classList.contains("show") && !e.target.closest(".sb-footer")) {
    pop.classList.remove("show");
  }
});

async function quickSaveModels() {
  if (!latestSnap) return;
  const roles = JSON.parse(JSON.stringify(latestSnap.roles || {}));
  const pMod = document.getElementById("quickPlannerModel")?.value;
  const bMod = document.getElementById("quickBuilderModel")?.value;
  const bEff = document.getElementById("quickBuilderEffort")?.value;
  if (roles.planner && pMod) roles.planner.model = pMod;
  if (roles.builder && bMod) roles.builder.model = bMod;
  if (roles.builder && bEff) roles.builder.effort = bEff;
  try {
    const res = await api("/api/roles", { roles });
    render(res.snapshot);
    showToast("模型切换已生效");
  } catch (e) { showToast(e.message); }
}

function openGuideModal() { document.getElementById("guideModal").classList.add("show"); }
function closeGuideModal() { document.getElementById("guideModal").classList.remove("show"); }

let currentSkillFilter = "all";
let attachedSkillIds = [];
let currentLang = localStorage.getItem("sw_lang") || "zh";

function t(zh, en) {
  return currentLang === "en" ? en : zh;
}

function fmtThreadTitle(raw) {
  const s = String(raw || "").trim();
  if (!s || s === "主对话") return t("主对话", "Main Thread");
  if (s === "新对话") return t("新对话", "New Thread");
  return s;
}

function fmtSkillSource(label) {
  if (currentLang !== "en") return label;
  const map = {
    "内置推荐": "Built-in",
    "自定义全局": "Global Custom",
    "当前空间": "Workspace",
    "本机 Codex": "Local Codex",
    "本机 AGY": "Local AGY",
    "本机 Claude": "Local Claude"
  };
  return map[label] || label;
}

function fmtSkillDesc(skill) {
  if (currentLang !== "en") return skill.description || "";
  const enMap = {
    "aigc-storyboard": "Break down rough ideas or novel chapters into a structured AIGC short-drama storyboard table (3s hook, camera framing, and character consistency prompts).",
    "code-review-strict": "Evidence-bound strict code audit & refactoring checklist (pinpoint edge-case bugs, race conditions, performance bottlenecks, and security hazards).",
    "git-commit-release": "Draft clean Conventional Commit messages, bilingual changelogs, and GitHub Release notes automatically."
  };
  return enMap[skill.slug] || skill.description || "";
}

function fmtMcpTemplate(tpl) {
  if (currentLang !== "en") return { title: tpl.title, desc: tpl.desc };
  const enMap = {
    playwright: ["Playwright Browser", "Let AI open web pages, take screenshots, click buttons, and test UI flows"],
    github: ["GitHub Collaboration", "Query issues, open PRs, search repositories, and publish releases"],
    figma: ["Figma Design Reader", "Read Figma layers, colors, and layout specs directly into production code"],
    comfyui: ["ComfyUI / AIGC Bridge", "Push storyboard prompts directly to local ComfyUI image/video queues"],
    filesystem: ["Extra Local Directory", "Grant AI read/write access to reference folders outside the current workspace"]
  };
  const pair = enMap[tpl.id];
  return pair ? { title: pair[0], desc: pair[1] } : { title: tpl.title, desc: tpl.desc };
}

const STATIC_I18N = [
  [".sb-sec-head > span", "工作空间", "Workspaces"],
  ["#modelPopover .pop-title > span", "快速切换模型", "Quick Model Switch"],
  ["#quickEffortField > label", "思考深度 (Codex)", "Reasoning Effort (Codex)"],
  ["#quickBuilderEffort option[value='low']", "轻量 (low)", "Low (low)"],
  ["#quickBuilderEffort option[value='medium']", "均衡 (medium)", "Medium (medium)"],
  ["#quickBuilderEffort option[value='high']", "深度 (high · 推荐)", "High (high · Recommended)"],
  ["#quickBuilderEffort option[value='xhigh']", "极限 (xhigh)", "Max (xhigh)"],
  ["#modelPopover .btn.sm", "高级：配置角色引擎 / 接入 API", "Advanced: Role Bindings & APIs"],
  [".engine-trigger span", "模型与引擎", "Models & Engines"],
  ["#btnCompact span", "压缩上下文", "Compact"],
  ["#approvalBar .approval-info span:last-child", "方案已就绪，确认后交棒执行（可在下方输入框补充说明）", "Plan ready — confirm to hand off to Builder (optional notes below)"],
  ["#approvalBar .btn:first-child", "取消", "Cancel"],
  ["#approvalBar .btn.solid", "批准执行", "Approve & Build"],
  ["#plusMenu .plus-item:nth-child(1) span", "添加图片 / 截图", "Add Image / Screenshot"],
  ["#plusMenu .plus-item:nth-child(2) span", "添加本地文件 / 附件", "Add Local File"],
  ["#plusMenu .plus-item:nth-child(3) span", "挂载技能 (/ Skill)", "Mount Skill (/ Skill)"],
  [".insp-tab[data-tab='console']", "终端日志", "Console"],
  [".insp-tab[data-tab='workspace']", "改动与文件", "Changes & Files"],
  [".insp-tab[data-tab='artifacts']", "审片与预览", "Preview & Media"],
  ["#gatesCard .insp-card-title", "客观门禁与实测指标", "Quality Gates & Metrics"],
  ["#gatesCard button[onclick*='runSelfCheck']", "跑自检三条", "Run Self-Check"],
  ["#gatesCard button[onclick*='runDshVerify']", "DSH 核验", "DSH Verify"],
  ["#gatesCard button[onclick*='openObjectionPrompt']", "提异议", "Objection"],
  ["#gitCard .insp-card-title > span:first-child", "Git 代码改动", "Git Changes"],
  ["#btnGitDraft > span", "AI 起草", "AI Draft"],
  ["#inspWorkspaceTab > .insp-card:nth-of-type(4) .insp-card-title > span:first-child", "最近修改文件（点击查看源码/Diff）", "Recent Files (Click for Source / Diff)"],
  ["#aigcScreeningCard .insp-card-title", "AIGC 分镜画廊与音视频审片室", "AIGC Storyboard Gallery & Screening Room"],
  ["#inspArtifactsTab > .insp-card:nth-of-type(2) .insp-card-title", "最新施工单 (NEXT_FOR_CODEX.md)", "Latest Handoff (NEXT_FOR_CODEX.md)"],
  ["#mediaCard .insp-card-title", "画面与概念图预览", "Screenshots & Concept Preview"],
  ["#newWsType option[value='general']", "通用研发项目", "General Software Project"],
  ["#newWsType option[value='aigc-studio']", "AIGC 制片空间（脚本 / 分镜 / 剪辑）", "AIGC Studio (Script / Storyboard / Edit)"],
  ["#newWsType option[value='web-app']", "Web / 前端全栈", "Web / Full-Stack App"],
  ["#newWsType option[value='python']", "Python / 脚本与数据", "Python / Scripts & Data"],
  ["#newWsType option[value='godot-game']", "Godot 游戏工程", "Godot Game Project"],
  ["#newWsType option[value='docs']", "策划与文档空间", "Docs & Planning Workspace"],
  ["#wsModal .modal-foot .btn:first-child", "取消", "Cancel"],
  ["#delModal h3", "移除工作空间", "Remove Workspace"],
  ["#delModal .modal-foot .btn:first-child", "取消", "Cancel"],
  ["#delModal .modal-foot .btn.danger", "确认移除", "Remove"],
  ["#guideModal h3", "30 秒上手指南 · Super Workbench", "30-Second Quick Guide · Super Workbench"],
  ["#guideModal .modal-foot .btn", "知道了，开始工作", "Got It, Let's Build"],
  ["#snav-general .snav-title", "通用偏好", "General"],
  ["#snav-skills .snav-title", "技能 Skills", "Skills"],
  ["#snav-roles .snav-title", "角色与引擎", "Roles & Engines"],
  ["#snav-engines .snav-title", "引擎与 API", "Engines & API"],
  ["#snav-mcp .snav-title", "外部工具 MCP", "MCP Tools"],
  ["#snav-plugins .snav-title", "工作流插件", "Plugins"],
  ["#lblPrefNameTitle", "自定义称呼", "Display Name"],
  ["#lblPrefNameDesc", "用于全新对话问候语、右侧微轨与任务交接记录。", "Shown in new-thread greetings, relay rail, and task logs."],
  ["#btnSaveUserName", "保存", "Save"],
  ["#lblPrefLangTitle", "界面语言", "Interface Language"],
  ["#lblPrefLangDesc", "在简体中文与 English 界面之间即时切换。", "Switch between Simplified Chinese and English instantly."],
  ["#lblPrefThemeTitle", "外观风格", "Appearance"],
  ["#lblPrefThemeDesc", "在暗夜（Obsidian）与纸白（Muse）双主题间自由切换。", "Switch between Obsidian Dark and Muse Light themes."],
  ["#themeOptDark", "暗夜深色", "Obsidian Dark"],
  ["#themeOptLight", "纸白浅色", "Muse Light"],
  ["#lblPrefGateTitle", "自动流水线 · 执行前暂停审批", "Auto Pipeline · Pause Before Build"],
  ["#lblPrefGateDesc", "开启后，「全自动流转」会在策划输出方案后暂停，等你点一下批准再动手改文件。", "When enabled, Auto Pipeline pauses after Planner outputs a plan and waits for your approval."],
  ["#lblPrefExitTitle", "关闭窗口时同时退出后台服务", "Stop Background Service on Window Close"],
  ["#lblPrefExitDesc", "默认关闭（点右上角 × 仅关窗口，后台保持运行以便下次秒开）；开启后关窗口将自动停掉后台。", "Off by default (clicking × only closes the window for instant reopen); when enabled, closing the window stops the background service."],
  ["#btnQuitBackend", "立即退出后台", "Quit Service Now"],
  // Pane 1: Skills
  ["#pane-skills > details.explain-fold > summary > span:first-child", "ⓘ 什么是 Skill（技能）？点此查看说明", "ⓘ What is a Skill? Click to expand"],
  ["#skillFilterBar button[data-sf='all']", "全部", "All"],
  ["#skillFilterBar button[data-sf='active']", "已启用", "Active"],
  ["#skillFilterBar button[data-sf='custom']", "自定义", "Custom"],
  ["#skillFilterBar button[data-sf='ext']", "本机发现", "Discovered"],
  ["#pane-skills button[onclick*='toggleSkillCreateBox']", "+ 新建技能", "+ New Skill"],
  ["#pane-skills button[onclick*='toggleSkillImportBox']", "导入本地 Skill", "Import Local Skill"],
  ["#skillCreateBox .insp-card-title", "创建新技能（自动生成标准 SKILL.md，无需懂 YAML）", "Create New Skill (Auto-generates standard SKILL.md)"],
  ["#newSkillScope option[value='user']", "全局可用（存放在工作台技能库）", "Global (Saved in Workbench skill library)"],
  ["#newSkillScope option[value='workspace']", "仅当前空间（存放在项目 .agents/skills/）", "Current Workspace (.agents/skills/)"],
  ["#skillCreateBox button[onclick*='toggleSkillCreateBox(false)']", "取消", "Cancel"],
  ["#skillCreateBox button[onclick*='submitCreateSkill']", "创建并启用", "Create & Enable"],
  ["#skillImportBox .insp-card-title", "导入本地已有 Skill（支持 SKILL.md 文件或技能文件夹路径）", "Import Local Skill (Path to SKILL.md or skill folder)"],
  ["#btnPickSkillFolder", "浏览…", "Browse…"],
  ["#btnPickWsFolder", "浏览…", "Browse…"],
  ["#skillImportBox button[onclick*='submitImportSkill']", "一键导入", "Import"],
  // Pane 2: Roles
  ["#pane-roles details.explain-fold > summary > span:first-child", "ⓘ 如何分配这三个角色？点此查看说明", "ⓘ How to assign the three role slots? Click to expand"],
  ["#pane-roles button[onclick*='autoRecommendRoles']", "一键推荐配置", "Auto-Recommend"],
  ["#pane-roles button[onclick*='saveRoleBindings']", "保存角色配置", "Save Role Bindings"],
  // Pane 3: Engines & API
  ["#pane-engines > .insp-card:first-child > .insp-card-title", "本机已检测 CLI 与自定义引擎", "Detected Local CLIs & Custom Engines"],
  ["#pane-engines > .insp-card:last-child .insp-card-title", "接入新的云端 API 或本地模型（点模板自动填表）", "Connect Cloud API or Local Model (1-click templates)"],
  ["#pane-engines button[onclick*=\"presetEngine('ollama')\"]", "免费本地 Ollama", "Local Ollama"],
  ["#pane-engines button[onclick*=\"presetEngine('custom-cli')\"]", "自定义命令行", "Custom CLI"],
  ["#engKind option[value='openai-compat']", "云端 API / 本地 Ollama（免安装 CLI）", "Cloud API / Local Ollama (No CLI required)"],
  ["#engKind option[value='custom-cli']", "本机命令行工具（CLI）", "Local Command-Line Tool (CLI)"],
  ["#pane-engines button[onclick*='submitAddEngine']", "添加到引擎库", "Add to Engine Library"],
  // Pane 4: MCP
  ["#pane-mcp > details.explain-fold > summary > span:first-child", "ⓘ 什么是 MCP（外部工具协议）？点此查看说明", "ⓘ What is MCP (Model Context Protocol)? Click to expand"],
  ["#pane-mcp button[onclick*='toggleMcpForm(true)']", "+ 添加 MCP 工具", "+ Add MCP Tool"],
  ["#pane-mcp button[onclick*='scanCliMcps']", "检测本机已有 MCP", "Scan Local CLI MCPs"],
  ["#mcpFormBox .insp-card-title", "一键套用模板或自定义接入", "Apply Template or Custom Setup"],
  ["#mcpTransport option[value='stdio']", "本地命令（stdio / npx / uvx）", "Local Command (stdio / npx / uvx)"],
  ["#mcpTransport option[value='http']", "远程或本地接口（HTTP URL）", "Remote or Local Endpoint (HTTP URL)"],
  ["#mcpFormBox button[onclick*='toggleMcpForm(false)']", "取消", "Cancel"],
  ["#mcpFormBox button[onclick*='submitMcpServer']", "保存配置", "Save MCP"],
  ["#mcpQuickTemplatesCard .insp-card-title", "常用 MCP 模板（点一下自动填表）", "Popular MCP Templates (Click to auto-fill)"],
  // Pane 5: Plugins
  ["#pane-plugins > details.explain-fold > summary > span:first-child", "ⓘ 什么是工作流插件（Plugins）？点此查看说明", "ⓘ What are Workflow Plugins? Click to expand"]
];

function applyLang(lang) {
  currentLang = lang === "en" ? "en" : "zh";
  localStorage.setItem("sw_lang", currentLang);
  document.documentElement.lang = currentLang === "en" ? "en" : "zh-CN";
  document.getElementById("langOptZh")?.classList.toggle("solid", currentLang === "zh");
  document.getElementById("langOptEn")?.classList.toggle("solid", currentLang === "en");

  for (const [sel, zh, en] of STATIC_I18N) {
    const el = document.querySelector(sel);
    if (el) el.textContent = currentLang === "en" ? en : zh;
  }

  const pipeBtn = document.querySelector(".mode-pill[data-mode='pipeline']");
  if (pipeBtn && pipeBtn.lastChild) {
    pipeBtn.lastChild.textContent = " " + t("全自动流转", "Auto Pipeline");
  }
  const cmdEl = document.getElementById("cmdInput");
  if (cmdEl) {
    cmdEl.placeholder = t(
      "输入想法或指令… 支持点 + 添加图片/附件/技能，直接粘贴截图，或 Ctrl+Enter 发送",
      "Ask or build anything… Click + for images/files/skills, paste screenshots, or Ctrl+Enter to send"
    );
  }
  const gitBox = document.getElementById("gitCommitMsg");
  if (gitBox) {
    gitBox.placeholder = t(
      "提交信息… 可点「AI 起草」根据改动自动生成",
      "Commit message… Click 'AI Draft' to generate from current diff"
    );
  }
  const uInput = document.getElementById("inputUserName");
  if (uInput) {
    uInput.placeholder = t("例如：修 / Ricardo", "e.g. Ricardo / Alex");
  }

  // Translate form labels & placeholders across Settings panes
  const setLabelFor = (inputId, zh, en) => {
    const inp = document.getElementById(inputId);
    const lbl = inp?.closest(".field")?.querySelector("label");
    if (lbl) lbl.textContent = currentLang === "en" ? en : zh;
  };
  const setPh = (inputId, zh, en) => {
    const inp = document.getElementById(inputId);
    if (inp) inp.placeholder = currentLang === "en" ? en : zh;
  };

  setLabelFor("newSkillName", "技能名称", "Skill Name");
  setPh("newSkillName", "例如：小红书爆款文案 / 漫剧分镜", "e.g. Storyboard Director / Strict Reviewer");
  setLabelFor("newSkillScope", "保存范围", "Save Scope");
  setLabelFor("newSkillDesc", "一句话用途说明（展示给小白和 / 菜单）", "One-Line Description (Shown in list & / menu)");
  setPh("newSkillDesc", "例如：按爆款钩子+结构化分镜表输出 60 秒漫剧脚本", "e.g. Output 60s short-drama script with 3s hook & shot table");
  setLabelFor("newSkillBody", "具体执行规范（直接用大白话写清楚要求即可）", "Execution Instructions (Plain language rules)");
  setPh("newSkillBody", "例如：\n1. 前 3 秒必须给出强悬念冲突；\n2. 输出 Markdown 表格，包含镜号、景别、台词、生图提示词；\n3. 保持主角外貌描述跨镜一致。", "e.g.\n1. Start with a strong 3s hook;\n2. Output a Markdown table with Shot, Framing, Dialogue, Image Prompt;\n3. Keep character traits consistent across shots.");
  setPh("importSkillPath", "粘贴本地技能文件夹路径或 SKILL.md 绝对路径，如 E:\\my-skills\\storyboard", "Paste absolute path to skill folder or SKILL.md, e.g. E:\\my-skills\\storyboard");

  setLabelFor("engName", "给它起个名字", "Display Name");
  setPh("engName", "例如：DeepSeek 策划 / 本地模型", "e.g. DeepSeek Planner / Local Ollama");
  setLabelFor("engKind", "连接方式", "Connection Type");
  setLabelFor("engBaseUrl", "接口地址（点上方模板自动填好）", "Endpoint Base URL (Click a preset above to auto-fill)");
  setLabelFor("engApiKey", "API 密钥（本地 Ollama 无需填写）", "API Key (Leave empty for local Ollama)");
  setPh("engApiKey", "粘贴 sk-... 或留空", "Paste sk-... or leave empty");
  setLabelFor("engModel", "使用的模型名称", "Default Model Name");
  setPh("engModel", "例如 deepseek-reasoner / qwen2.5:14b", "e.g. deepseek-reasoner / qwen2.5:14b");
  setLabelFor("engCmdTpl", "命令行模板（{prompt} 会自动替换为你的指令）", "Command Template ({prompt} is replaced with your prompt)");

  setLabelFor("mcpName", "工具标识（英文，如 playwright）", "Tool ID (lowercase, e.g. playwright)");
  setPh("mcpName", "例如：playwright / github / figma", "e.g. playwright / github / figma");
  setLabelFor("mcpTransport", "连接方式", "Transport");
  setLabelFor("mcpTitle", "中文名称（选填）", "Display Title (optional)");
  setPh("mcpTitle", "例如：Playwright 浏览器", "e.g. Playwright Browser");
  setLabelFor("mcpDesc", "用途简介（选填）", "Short Description (optional)");
  setPh("mcpDesc", "一句话说明这个工具做什么", "One sentence describing what this tool does");
  setLabelFor("mcpCmd", "启动命令", "Command");
  setLabelFor("mcpArgs", "启动参数（空格分隔）", "Arguments (space-separated)");
  setLabelFor("mcpUrl", "MCP 服务地址（URL）", "MCP Server URL");
  setLabelFor("mcpEnv", "环境变量 / 密钥（选填，每行一条 KEY=VALUE）", "Environment Variables / Secrets (optional, one KEY=VALUE per line)");
  setPh("mcpEnv", "例如：GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxx", "e.g. GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxx");
  setLabelFor("newWsName", "空间名称", "Workspace Name");
  setPh("newWsName", "例如：SuperWorkbench-OSS / 个人网站", "e.g. SuperWorkbench-OSS / MyWebApp");
  setLabelFor("newWsPath", "本地目录路径（若不存在将自动创建）", "Local Directory Path (Created automatically if missing)");
  setPh("newWsPath", "例如：E:\\Projects\\MyWorkspace", "e.g. E:\\Projects\\MyWorkspace");
  setLabelFor("newWsType", "空间类型", "Workspace Preset");
  const mcpAutoLbl = document.getElementById("mcpAutoSync")?.parentElement;
  if (mcpAutoLbl && mcpAutoLbl.lastChild) {
    mcpAutoLbl.lastChild.textContent = " " + t("保存并一键同步到本机已装 CLI", "Save & auto-sync to installed local CLIs");
  }

  // Explain folds body content
  const setExplain = (paneId, zhHtml, enHtml) => {
    const el = document.querySelector(`#${paneId} details.explain-fold .explain-content`);
    if (el) el.innerHTML = currentLang === "en" ? enHtml : zhHtml;
  };
  setExplain("pane-skills",
    '<strong>Skill 就像给 AI 员工发的《岗位 SOP 手册》（标准 <code class="inline">SKILL.md</code>）。</strong><br/>你可以在下方开关决定「全局常驻」或「仅在当前空间生效」，也可以随时在对话框输入 <code class="inline">/</code> 临时点名召唤某一项技能——无论是本地 CLI 还是 DeepSeek / Ollama 纯 API，都会自动按这份规范执行。',
    '<strong>A Skill is an SOP playbook (<code class="inline">SKILL.md</code>) for your AI agents.</strong><br/>Toggle skills globally or per-workspace below, or type <code class="inline">/</code> in the composer to mount a skill on the fly — works across both local CLIs and pure HTTP APIs.'
  );
  setExplain("pane-roles",
    '<strong>只需为「核心执行」绑定 1 个本地 CLI（如 Codex / Claude / AGY）</strong>，其余「策划」与「质检」岗位无论绑 CLI 还是接 DeepSeek / Ollama 纯 API 均可正常工作。',
    '<strong>Only the Core Builder slot requires a local file-editing CLI (e.g. Codex / Claude / AGY).</strong> Planner and Reviewer can freely bind to any CLI, local Ollama model, or cloud API.'
  );
  setExplain("pane-mcp",
    '<strong>如果说 Skill 是“教 AI 怎么想的说明书”，那么 MCP 就是给 AI 接上的“手和眼”</strong>——让它能操控浏览器、读取 Figma、查 GitHub 或连本地 ComfyUI。在这里填好后，可一键同步到你本机已安装的 AGY / Codex / Claude CLI，无需手写 JSON。',
    '<strong>If Skills teach AI how to think, MCP gives AI hands and eyes</strong> — browser automation, Figma reading, GitHub PRs, or local ComfyUI queues. Configure once here and sync to your installed AGY / Codex / Claude CLIs with one click.'
  );
  setExplain("pane-plugins",
    '<strong>工作流插件把某一类项目的「右侧专属抽屉面板 + 目录初始化 + 门禁检查 + 推荐技能」打包成开箱即用的行业套装</strong>，且按工作空间隔离，互不干扰。',
    '<strong>Workflow Plugins bundle dedicated Inspector panels, directory initializers, and quality gates for specific project types</strong>, cleanly isolated per workspace.'
  );

  // Plugins cards
  const pCards = document.querySelectorAll("#pane-plugins .skill-card");
  const pluginMeta = [
    ["Godot 游戏研发实验室", "Godot Game Dev Lab", "内置已启用", "Built-in · Active", "godot-game 空间生效", "Active in godot-game", "提供提交前自检三条、FPS/输入延迟硬指标灯、轮次里程碑、实机截图预览与一键启动试玩。", "Pre-submit 3-gate checks, FPS/input-latency indicators, round milestones, screenshots, and 1-click playtest launch."],
    ["AIGC 漫剧与短片制片空间", "AIGC Short Drama & Film Studio", "内置已启用", "Built-in · Active", "aigc-studio 空间生效", "Active in aigc-studio", "自动初始化 5 级制片目录（脚本/分镜/素材/剪辑/成片），角色槽位切换为「编剧 · 制片 · 审片」，右侧抽屉内置分镜网格画廊、5 阶段进度条与 HTML5 音视频审片室。", "Auto-initializes 5-stage studio folders (script/storyboard/assets/edit/output), switches role labels to Script · Produce · Review, and enables the Storyboard Gallery & HTML5 Screening Room."],
    ["Live Git Diff 与源码审查抽屉", "Live Git Diff & Source Review Drawer", "内置已启用", "Built-in · Active", "general / web / python / godot", "general / web / python / godot", "在右侧抽屉的「代码改动 / 文件」页签实时查看 Git 变更文件、红绿高亮代码 Diff 与无 Git 目录下的行号源码预览。", "Inspect changed Git files, red/green unified diffs, AI-drafted commit messages, and line-numbered source previews in the Right Inspector."]
  ];
  pCards.forEach((card, idx) => {
    const m = pluginMeta[idx];
    if (!m) return;
    const st = card.querySelector("strong");
    const src = card.querySelector(".skill-src");
    const scope = card.querySelector(".skill-top > span:last-child");
    const desc = card.querySelector(":scope > div:last-child");
    if (st) st.textContent = currentLang === "en" ? m[1] : m[0];
    if (src) src.textContent = currentLang === "en" ? m[3] : m[2];
    if (scope) scope.textContent = currentLang === "en" ? m[5] : m[4];
    if (desc) desc.textContent = currentLang === "en" ? m[7] : m[6];
  });

  const activeNav = document.querySelector(".settings-nav .snav-item.active");
  if (activeNav) {
    const tabId = (activeNav.id || "").replace("snav-", "") || "general";
    const titleEl = document.getElementById("settingsPaneTitle");
    if (titleEl) titleEl.textContent = getSettingsTitle(tabId);
  }

  lastChatSig = "";
  lastWsSig = "";
  if (latestSnap) {
    render(latestSnap, true);
    renderStudioModal();
    renderSkillsPane();
  }
}

async function setLanguage(lang) {
  const next = lang === "en" ? "en" : "zh";
  applyLang(next);
  try {
    const res = await api("/api/settings", { lang: next });
    latestSnap = res.snapshot;
    render(res.snapshot, true);
    showToast(next === "en" ? "Switched to English" : "已切换为简体中文");
  } catch (e) { showToast(e.message); }
}

function getSettingsTitle(tab) {
  const map = {
    general: t("通用偏好", "General Preferences"),
    skills: t("技能 Skills", "Skills"),
    roles: t("角色与引擎绑定", "Roles & Engine Bindings"),
    engines: t("引擎与 API 库", "Engines & APIs"),
    mcp: t("外部工具 MCP", "MCP External Tools"),
    plugins: t("工作流插件 Plugins", "Workflow Plugins")
  };
  return map[tab] || map.general;
}

function getTimePeriodLabel() {
  const h = new Date().getHours();
  if (currentLang === "en") {
    if (h >= 5 && h < 12) return "Good morning";
    if (h >= 12 && h < 18) return "Good afternoon";
    if (h >= 18 && h < 24) return "Good evening";
    return "Working late";
  }
  if (h >= 5 && h < 12) return "早上好";
  if (h >= 12 && h < 14) return "中午好";
  if (h >= 14 && h < 18) return "下午好";
  if (h >= 18 && h < 24) return "晚上好";
  return "夜深了";
}

function getGreetingLine(userName) {
  const period = getTimePeriodLabel();
  const clean = String(userName || "").trim();
  const hasCustom = clean && clean !== "我" && clean.toLowerCase() !== "me";
  if (currentLang === "en") {
    return hasCustom ? `${period}, ${clean}. Where shall we start today?` : `${period}. Where shall we start today?`;
  }
  return hasCustom ? `${period}，${clean}，今天想从哪里开始？` : `${period}，今天想从哪里开始？`;
}

function openSettings(tab = "general") {
  renderStudioModal();
  renderSkillsPane();
  switchStudioTab(tab);
  document.getElementById("studioModal").classList.add("show");
}
function openStudioModal(tab = "roles") { openSettings(tab); }
function closeStudioModal() {
  document.getElementById("studioModal").classList.remove("show");
}
function switchStudioTab(tab) {
  ["general", "skills", "roles", "engines", "mcp", "plugins"].forEach(k => {
    document.getElementById("snav-" + k)?.classList.toggle("active", k === tab);
    const pane = document.getElementById("pane-" + k);
    if (pane) pane.style.display = k === tab ? "flex" : "none";
  });
  document.getElementById("settingsPaneTitle").textContent = getSettingsTitle(tab);
  if (tab === "skills") renderSkillsPane();
}

function setSkillFilter(f) {
  currentSkillFilter = f;
  document.querySelectorAll("#skillFilterBar button").forEach(b => {
    b.classList.toggle("solid", b.dataset.sf === f);
  });
  renderSkillsPane();
}
function toggleSkillCreateBox(force) {
  const el = document.getElementById("skillCreateBox");
  const show = force !== undefined ? force : el.style.display === "none";
  el.style.display = show ? "flex" : "none";
  if (show) document.getElementById("skillImportBox").style.display = "none";
}
function toggleSkillImportBox(force) {
  const el = document.getElementById("skillImportBox");
  const show = force !== undefined ? force : el.style.display === "none";
  el.style.display = show ? "flex" : "none";
  if (show) document.getElementById("skillCreateBox").style.display = "none";
}

function renderSkillsPane() {
  const box = document.getElementById("skillsListContainer");
  if (!box || !latestSnap) return;
  const list = latestSnap.skills || [];
  const filtered = list.filter(s => {
    if (currentSkillFilter === "active") return s.active;
    if (currentSkillFilter === "custom") return s.source === "user" || s.source === "workspace";
    if (currentSkillFilter === "ext") return String(s.source || "").startsWith("ext-");
    return true;
  });

  if (!filtered.length) {
    box.innerHTML = `<div style="text-align:center;padding:28px 12px;color:var(--text-muted);font-size:12.5px;">${t("该分类下暂无技能。点上方「+ 新建技能」即可用大白话写一个！", "No skills in this category yet. Click '+ New Skill' above to create one in plain language.")}</div>`;
    return;
  }

  box.innerHTML = filtered.map(s => `
    <div class="skill-card ${s.active ? 'active' : ''}">
      <div class="skill-top">
        <div style="min-width:0;flex:1;">
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            <strong style="font-size:13px;">${escapeHtml(s.name)}</strong>
            <span class="skill-slug">/${escapeHtml(s.slug)}</span>
            <span class="skill-src">${escapeHtml(fmtSkillSource(s.source_label))}</span>
          </div>
          <div style="font-size:12px;color:var(--text-sec);margin-top:4px;">${escapeHtml(fmtSkillDesc(s))}</div>
        </div>
        <div style="display:flex;align-items:center;gap:5px;flex-shrink:0;">
          <button class="toggle-chip ${s.enabled_global ? 'on' : ''}" title="${t("在所有工作空间中自动生效", "Active across all workspaces")}" onclick="toggleSkill('${escapeHtml(s.id)}','global',${!s.enabled_global})">${t("全局", "Global")}</button>
          <button class="toggle-chip ${s.enabled_workspace ? 'on' : ''}" title="${t("仅在当前工作空间生效", "Active in current workspace only")}" onclick="toggleSkill('${escapeHtml(s.id)}','workspace',${!s.enabled_workspace})">${t("本空间", "Workspace")}</button>
          ${s.editable ? `<button class="ws-act-btn del" title="${t("删除自定义技能", "Delete custom skill")}" onclick="deleteSkill('${escapeHtml(s.id)}')"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg></button>` : ""}
        </div>
      </div>
      <details style="font-size:11.5px;color:var(--text-muted);">
        <summary style="cursor:pointer;user-select:none;">${t("查看规范正文", "View Skill Specification")}</summary>
        <pre style="margin:6px 0 0;padding:8px 10px;border-radius:8px;background:var(--bg-code);border:1px solid var(--border);white-space:pre-wrap;font-family:Consolas,monospace;color:var(--text-sec);max-height:150px;overflow-y:auto;">${escapeHtml(s.body)}</pre>
      </details>
    </div>`).join("");
}

async function toggleSkill(id, scope, enabled) {
  try {
    const res = await api("/api/skills", { action: "toggle", id, scope, enabled });
    render(res.snapshot, true);
    renderSkillsPane();
    showToast(enabled ? `已启用技能（${scope === 'global' ? '全局' : '当前空间'}）` : "已关闭该技能");
  } catch (e) { showToast(e.message); }
}

async function submitCreateSkill() {
  const name = document.getElementById("newSkillName").value.trim();
  const description = document.getElementById("newSkillDesc").value.trim();
  const body = document.getElementById("newSkillBody").value.trim();
  const scope = document.getElementById("newSkillScope").value;
  if (!name || !body) { showToast("请填写技能名称和具体规范内容"); return; }
  try {
    const res = await api("/api/skills", { action: "create", name, description, body, scope });
    document.getElementById("newSkillName").value = "";
    document.getElementById("newSkillDesc").value = "";
    document.getElementById("newSkillBody").value = "";
    toggleSkillCreateBox(false);
    render(res.snapshot, true);
    renderSkillsPane();
    showToast(`已创建并启用技能：${name}`);
  } catch (e) { showToast(e.message); }
}

async function submitImportSkill() {
  const source_path = document.getElementById("importSkillPath").value.trim();
  if (!source_path) { showToast("请粘贴本地 SKILL.md 或技能文件夹路径"); return; }
  try {
    const res = await api("/api/skills", { action: "import", source_path });
    document.getElementById("importSkillPath").value = "";
    toggleSkillImportBox(false);
    render(res.snapshot, true);
    renderSkillsPane();
    showToast("导入成功，已自动全局启用");
  } catch (e) { showToast(e.message); }
}

async function deleteSkill(id) {
  if (!confirm("确定删除该自定义技能？（不会影响内置技能）")) return;
  try {
    const res = await api("/api/skills", { action: "delete", id });
    render(res.snapshot, true);
    renderSkillsPane();
    showToast("已删除技能");
  } catch (e) { showToast(e.message); }
}

// --- Composer Slash (/) Skill Picker ---
function toggleSlashMenu(force, filterText = "") {
  const menu = document.getElementById("slashMenu");
  const show = force !== undefined ? force : !menu.classList.contains("show");
  if (!show) { menu.classList.remove("show"); return; }
  const list = (latestSnap?.skills || []).filter(s => {
    if (!filterText) return true;
    const q = filterText.toLowerCase();
    return s.slug.toLowerCase().includes(q) || s.name.toLowerCase().includes(q) || (s.description || "").toLowerCase().includes(q);
  });
  if (!list.length) { menu.classList.remove("show"); return; }
  menu.innerHTML =
    `<div style="font-size:11px;color:var(--text-muted);padding:4px 8px 6px;display:flex;justify-content:space-between;"><span>点选临时挂载技能（本条指令生效）</span><a href="javascript:void(0)" style="color:var(--text-sec);" onclick="toggleSlashMenu(false);openSettings('skills')">管理全部 →</a></div>` +
    list.slice(0, 12).map(s => `
      <button class="slash-item" onclick="attachSkill('${escapeHtml(s.id)}')">
        <div style="min-width:0;">
          <div style="font-size:12.5px;font-weight:600;">/${escapeHtml(s.slug)} <span style="font-weight:400;color:var(--text-sec);margin-left:4px;">${escapeHtml(s.name)}</span></div>
          <div style="font-size:11px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(s.description)}</div>
        </div>
        <span class="skill-src">${s.active ? '已常驻' : escapeHtml(s.source_label)}</span>
      </button>`).join("");
  menu.classList.add("show");
}

function attachSkill(skillId) {
  if (!attachedSkillIds.includes(skillId)) attachedSkillIds.push(skillId);
  if (/^\/\S*$/.test(cmdInput.value.trim())) cmdInput.value = "";
  else cmdInput.value = cmdInput.value.replace(/(?:^|\s)\/\S*$/, "").trimStart();
  toggleSlashMenu(false);
  renderAttachedSkills();
  cmdInput.focus();
}
let pendingAttachments = [];

function togglePlusMenu(force) {
  const menu = document.getElementById("plusMenu");
  const btn = document.getElementById("btnPlus");
  const show = force !== undefined ? force : !menu.classList.contains("show");
  menu.classList.toggle("show", show);
  if (btn) btn.classList.toggle("open", show);
  if (show) toggleSlashMenu(false);
}
document.addEventListener("click", e => {
  const pm = document.getElementById("plusMenu");
  if (pm && pm.classList.contains("show") && !e.target.closest("#plusMenu") && !e.target.closest("#btnPlus")) {
    togglePlusMenu(false);
  }
  const sm = document.getElementById("slashMenu");
  if (sm && sm.classList.contains("show") && !e.target.closest("#slashMenu") && !e.target.closest("#cmdInput") && !e.target.closest("#plusMenu")) {
    toggleSlashMenu(false);
  }
});

function triggerFileUpload(kind) {
  togglePlusMenu(false);
  const el = document.getElementById(kind === "image" ? "imgPicker" : "filePicker");
  if (el) el.click();
}

function formatFileSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function handlePickedFiles(fileList) {
  if (!fileList || !fileList.length) return;
  for (const file of Array.from(fileList)) {
    if (file.size > 15 * 1024 * 1024) {
      showToast(`文件过大（上限 15 MB）：${file.name}`);
      continue;
    }
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("读取文件失败"));
        reader.readAsDataURL(file);
      });
      const res = await api("/api/upload", {
        filename: file.name || "pasted.png",
        mime_type: file.type || "",
        data_base64: dataUrl
      });
      if (res.attachment) {
        pendingAttachments.push(res.attachment);
        renderAttachedSkills();
      }
    } catch (e) {
      showToast(e.message || `上传失败：${file.name}`);
    }
  }
}

function removeAttachment(attId) {
  pendingAttachments = pendingAttachments.filter(a => a.id !== attId);
  renderAttachedSkills();
}

function removeAttachedSkill(skillId) {
  attachedSkillIds = attachedSkillIds.filter(x => x !== skillId);
  renderAttachedSkills();
}

function renderAttachedSkills() {
  const bar = document.getElementById("attachedSkillsBar");
  const skillMap = Object.fromEntries((latestSnap?.skills || []).map(s => [s.id, s]));

  const attHtml = pendingAttachments.map(a => {
    if (a.is_image) {
      const src = `/api/image?path=${encodeURIComponent(a.path)}`;
      return `<div class="att-thumb" title="${escapeHtml(a.name)}"><img src="${src}"/><button class="att-rm" onclick="removeAttachment('${escapeHtml(a.id)}')">&times;</button></div>`;
    }
    return `<span class="skill-pill" title="${escapeHtml(a.path)}">${escapeHtml(a.name)}${a.size ? ' · ' + formatFileSize(a.size) : ''}<button onclick="removeAttachment('${escapeHtml(a.id)}')">&times;</button></span>`;
  }).join("");

  const skillHtml = attachedSkillIds.map(id => {
    const s = skillMap[id];
    if (!s) return "";
    return `<span class="skill-pill">/${escapeHtml(s.slug)}<button onclick="removeAttachedSkill('${escapeHtml(id)}')">&times;</button></span>`;
  }).join("");

  bar.innerHTML = attHtml + skillHtml;
}

async function autoRecommendRoles(saveNow = false) {
  if (!latestSnap) return;
  const engines = latestSnap.engines || [];
  const readyList = engines.filter(e => e.ready);
  const readyIds = new Set(readyList.map(e => e.id));
  const fallback = readyList[0]?.id || "agy";
  const pick = (list) => list.find(id => readyIds.has(id)) || fallback;
  const engMap = Object.fromEntries(engines.map(e => [e.id, e]));
  const p = pick(["agy", "claude", "gemini", "codex"]);
  const b = pick(["codex", "claude", "agy", "gemini"]);
  const r = pick(["dsh", "agy", "codex", "claude", "gemini"]);
  const nextRoles = {
    planner: { ...(latestSnap.roles?.planner || {}), engine: p, model: engMap[p]?.default_model || "" },
    builder: { ...(latestSnap.roles?.builder || {}), engine: b, model: engMap[b]?.default_model || "", effort: "high" },
    reviewer: { ...(latestSnap.roles?.reviewer || {}), engine: r, model: engMap[r]?.default_model || "" }
  };
  if (saveNow) {
    try {
      lastChatSig = "";
      const res = await api("/api/roles", { roles: nextRoles });
      render(res.snapshot, true);
      showToast("已按本机环境一键绑定最佳角色阵容");
    } catch (e) { showToast(e.message); }
    return;
  }
  latestSnap.roles = nextRoles;
  renderStudioModal();
  showToast("已按本机环境自动匹配推荐阵容，点击「保存角色配置」生效");
}

function renderStudioModal() {
  if (!latestSnap) return;
  const roles = latestSnap.roles || {};
  const engines = latestSnap.engines || [];
  const engMap = Object.fromEntries(engines.map(e => [e.id, e]));

  const slotMeta = [
    { id: "planner", title: t("1. 策划 / 方案（AIGC：编剧与分镜）", "1. Planner / Architecture (AIGC: Script & Storyboard)"), hint: t("负责思考讨论，CLI 或纯 API 均可", "Brainstorming & planning — works with CLI or pure API") },
    { id: "builder", title: t("2. 核心执行（AIGC：制片与剪辑）", "2. Core Builder (AIGC: Production & Editing)"), hint: t("负责改代码跑命令，推荐绑定本地 CLI", "Edits files & runs commands — local CLI recommended") },
    { id: "reviewer", title: t("3. 独立质检（AIGC：审片与检查）", "3. Independent Reviewer (AIGC: Screening & QA)"), hint: t("负责审查把关，CLI 或纯 API 均可", "Read-only verification & review — CLI or pure API") }
  ];

  const readyOpts = engines.filter(e => e.ready);
  const notReadyOpts = engines.filter(e => !e.ready);

  document.getElementById("roleSlotsContainer").innerHTML = slotMeta.map(s => {
    const r = roles[s.id] || {};
    const curEng = engMap[r.engine] || engines[0] || {};
    const curModel = r.model || curEng.default_model || "";
    const optHtml = [
      readyOpts.length ? `<optgroup label="${t("本机可用引擎", "Available Engines")}">${readyOpts.map(e => `<option value="${escapeHtml(e.id)}" ${e.id === r.engine ? 'selected' : ''}>${escapeHtml(e.name)} ${e.kind === 'openai-compat' ? '· API' : '· CLI'}</option>`).join("")}</optgroup>` : "",
      notReadyOpts.length ? `<optgroup label="${t("尚未安装", "Not Installed")}">${notReadyOpts.map(e => `<option value="${escapeHtml(e.id)}" ${e.id === r.engine ? 'selected' : ''}>${escapeHtml(e.name)} (${t("未检测到", "Not detected")})</option>`).join("")}</optgroup>` : ""
    ].join("");

    const models = curEng.models || [];
    const hasCurInList = models.some(m => m.id === curModel);
    const modelControl = (curEng.kind === "openai-compat" || models.length <= 1)
      ? `<input id="slot-model-${s.id}" value="${escapeHtml(curModel)}" placeholder="${t("输入模型名称", "Enter model name")}" />`
      : `<select id="slot-model-${s.id}">
          ${!hasCurInList && curModel ? `<option value="${escapeHtml(curModel)}" selected>${escapeHtml(curModel)}</option>` : ""}
          ${models.map(m => `<option value="${escapeHtml(m.id)}" ${m.id === curModel ? 'selected' : ''}>${escapeHtml(m.label || m.id)}</option>`).join("")}
        </select>`;

    const warnApi = (s.id === "builder" && curEng.kind === "openai-compat")
      ? `<div style="font-size:11px;color:var(--c-warn);margin-top:4px;">${t("提示：纯 API 无法直接修改硬盘里的代码文件；如需自动写代码，建议为「核心执行」选一个本地 CLI。", "Note: Pure HTTP APIs cannot edit local files directly; bind a local CLI to Core Builder for file editing.")}</div>`
      : "";

    const effortList = currentLang === "en"
      ? [["low","Low"],["medium","Medium"],["high","High"],["xhigh","Max"]]
      : [["low","轻量"],["medium","均衡"],["high","深度"],["xhigh","极限"]];

    const hasCustomPersona = Boolean((r.custom_label || "").trim() || (r.system_prompt || "").trim());

    return `
      <div class="insp-card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <strong style="font-size:13px;">${s.title}</strong>
          <span style="font-size:11px;color:var(--text-muted);">${s.hint}</span>
        </div>
        <div style="display:grid;grid-template-columns:1.1fr 1.25fr ${curEng.supports_effort ? '0.8fr' : ''};gap:8px;">
          <div class="field">
            <label>${t("底层引擎", "Engine")}</label>
            <select id="slot-eng-${s.id}" onchange="onSlotEngineChange('${s.id}')">${optHtml}</select>
          </div>
          <div class="field">
            <label>${t("选择模型", "Model")}</label>
            ${modelControl}
          </div>
          ${curEng.supports_effort ? `
          <div class="field">
            <label>${t("思考深度", "Reasoning Effort")}</label>
            <select id="slot-effort-${s.id}">
              ${effortList.map(([lv, nm]) => `<option value="${lv}" ${lv === (r.effort || 'high') ? 'selected' : ''}>${nm} (${lv})</option>`).join("")}
            </select>
          </div>` : ""}
        </div>
        ${warnApi}
        <details class="explain-fold" style="margin-top:4px;">
          <summary>
            <span>${t("DIY 自定义角色称呼与人设提示词", "Customize Role Name & System Prompt")}${hasCustomPersona ? ` · <strong style="color:var(--c-agy);">${t("已自定义", "Custom")}</strong>` : ""}</span>
            <span>▾</span>
          </summary>
          <div class="explain-content" style="display:flex;flex-direction:column;gap:8px;padding-top:8px;">
            <div style="display:flex;align-items:center;gap:8px;">
              <div class="field" style="flex:1;margin:0;">
                <label>${t("自定义角色名（留空使用默认）", "Custom Role Name (optional)")}</label>
                <input id="slot-clabel-${s.id}" maxlength="24" value="${escapeHtml(r.custom_label || "")}" placeholder="${t("例如：增长文案总监 / 安全审计官 / 分镜导演", "e.g. Growth Strategist / Security Auditor / Director")}" />
              </div>
              <button class="btn sm" type="button" style="margin-top:16px;" onclick="resetRolePersona('${s.id}')">${t("恢复默认", "Reset")}</button>
            </div>
            <div class="field" style="margin:0;">
              <label>${t("专属人设提示词（System Prompt，留空使用默认）", "Custom System Prompt (optional)")}</label>
              <textarea id="slot-sysp-${s.id}" rows="2" style="width:100%;background:var(--bg-elevated);border:1px solid var(--border);border-radius:8px;padding:7px 9px;color:var(--text);font-family:inherit;font-size:12px;resize:vertical;" placeholder="${t("直接用大白话写明该角色的职责、输出风格与红线规范…", "Describe this role's persona, tone, and constraints in plain language...")}">${escapeHtml(r.system_prompt || "")}</textarea>
            </div>
          </div>
        </details>
      </div>`;
  }).join("");

  document.getElementById("enginesListBox").innerHTML = engines.map(e => `
    <div class="gate-row" style="padding:5px 0;border-bottom:1px solid var(--border);">
      <div style="display:flex;align-items:center;gap:8px;min-width:0;">
        <i class="s-dot ${e.ready ? 'on' : 'off'}"></i>
        <div style="min-width:0;">
          <div style="font-size:12.5px;font-weight:550;">${escapeHtml(e.name)} <span style="font-size:11px;color:var(--text-muted);font-weight:400;">· ${e.kind === 'openai-compat' ? t('云端/本地 API', 'Cloud / Local API') : t('本地 CLI', 'Local CLI')}</span></div>
          <div style="font-size:11px;color:var(--text-muted);font-family:Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(e.base_url || e.path || e.command_template || t('未在本机检测到', 'Not detected on this machine'))}</div>
        </div>
      </div>
      ${!e.builtin ? `<button class="btn sm danger" onclick="deleteCustomEngine('${e.id}')">${t("移除", "Remove")}</button>` : `<span style="font-size:11px;color:var(--text-muted);">${e.ready ? t('已就绪', 'Ready') : t('未安装', 'Not Installed')}</span>`}
    </div>`).join("");

  const gateToggle = document.getElementById("toggleApproveGate");
  if (gateToggle) gateToggle.checked = Boolean(latestSnap?.settings?.approve_before_build);
  const exitToggle = document.getElementById("toggleExitOnClose");
  if (exitToggle) exitToggle.checked = Boolean(latestSnap?.settings?.exit_on_close);
  const uNameEl = document.getElementById("inputUserName");
  const curUName = latestSnap?.settings?.user_name || "我";
  if (uNameEl && document.activeElement !== uNameEl) uNameEl.value = curUName;
  const curTheme = document.documentElement.getAttribute("data-theme") || "dark";
  document.getElementById("themeOptDark")?.classList.toggle("solid", curTheme === "dark");
  document.getElementById("themeOptLight")?.classList.toggle("solid", curTheme === "light");
  document.getElementById("langOptZh")?.classList.toggle("solid", currentLang === "zh");
  document.getElementById("langOptEn")?.classList.toggle("solid", currentLang === "en");

  renderMcpPane();
}

function onSlotEngineChange(slotId) {
  const newEngId = document.getElementById("slot-eng-" + slotId).value;
  const eng = (latestSnap?.engines || []).find(e => e.id === newEngId);
  if (!latestSnap.roles) latestSnap.roles = {};
  if (!latestSnap.roles[slotId]) latestSnap.roles[slotId] = {};
  latestSnap.roles[slotId].engine = newEngId;
  latestSnap.roles[slotId].model = eng?.default_model || "";
  renderStudioModal();
}

function resetRolePersona(slotId) {
  const cLbl = document.getElementById("slot-clabel-" + slotId);
  const sysP = document.getElementById("slot-sysp-" + slotId);
  if (cLbl) cLbl.value = "";
  if (sysP) sysP.value = "";
  showToast(t("已清空自定义人设，点击「保存角色配置」生效", "Reset to default persona — click Save Role Bindings to apply"));
}

async function saveRoleBindings() {
  const payload = {};
  ["planner", "builder", "reviewer"].forEach(slotId => {
    const engEl = document.getElementById("slot-eng-" + slotId);
    const modEl = document.getElementById("slot-model-" + slotId);
    const effEl = document.getElementById("slot-effort-" + slotId);
    const cLblEl = document.getElementById("slot-clabel-" + slotId);
    const sysEl = document.getElementById("slot-sysp-" + slotId);
    payload[slotId] = {
      engine: engEl ? engEl.value : "",
      model: modEl ? modEl.value.trim() : "",
      effort: effEl ? effEl.value : "high",
      custom_label: cLblEl ? cLblEl.value.trim() : "",
      system_prompt: sysEl ? sysEl.value.trim() : ""
    };
  });
  try {
    const res = await api("/api/roles", { roles: payload });
    render(res.snapshot, true);
    closeStudioModal();
    showToast(t("角色与引擎配置已生效", "Role & engine bindings saved"));
  } catch (e) { showToast(e.message); }
}

function toggleEngKindFields() {
  const kind = document.getElementById("engKind").value;
  document.getElementById("engApiFields").style.display = kind === "openai-compat" ? "grid" : "none";
  document.getElementById("engCliFields").style.display = kind === "custom-cli" ? "block" : "none";
}

function presetEngine(type) {
  if (type === "ollama") {
    document.getElementById("engKind").value = "openai-compat";
    toggleEngKindFields();
    document.getElementById("engName").value = "Ollama Local";
    document.getElementById("engBaseUrl").value = "http://localhost:11434/v1";
    document.getElementById("engApiKey").value = "";
    document.getElementById("engModel").value = "qwen2.5:14b";
  } else if (type === "deepseek") {
    document.getElementById("engKind").value = "openai-compat";
    toggleEngKindFields();
    document.getElementById("engName").value = "DeepSeek API";
    document.getElementById("engBaseUrl").value = "https://api.deepseek.com/v1";
    document.getElementById("engModel").value = "deepseek-reasoner";
  } else if (type === "openrouter") {
    document.getElementById("engKind").value = "openai-compat";
    toggleEngKindFields();
    document.getElementById("engName").value = "OpenRouter";
    document.getElementById("engBaseUrl").value = "https://openrouter.ai/api/v1";
    document.getElementById("engModel").value = "anthropic/claude-sonnet-4";
  } else {
    document.getElementById("engKind").value = "custom-cli";
    toggleEngKindFields();
    document.getElementById("engName").value = "Aider CLI";
    document.getElementById("engCmdTpl").value = 'aider --yes --message "{prompt}"';
  }
}

async function submitAddEngine() {
  const kind = document.getElementById("engKind").value;
  const payload = {
    action: "add",
    kind,
    name: document.getElementById("engName").value.trim(),
    base_url: document.getElementById("engBaseUrl").value.trim(),
    api_key: document.getElementById("engApiKey").value.trim(),
    default_model: document.getElementById("engModel").value.trim(),
    command_template: document.getElementById("engCmdTpl").value.trim()
  };
  try {
    const res = await api("/api/engines", payload);
    latestSnap = res.snapshot;
    render(res.snapshot);
    renderStudioModal();
    document.getElementById("engName").value = "";
    document.getElementById("engApiKey").value = "";
    showToast(`已接入新引擎：${payload.name}`);
  } catch (e) { showToast(e.message); }
}

async function deleteCustomEngine(id) {
  try {
    const res = await api("/api/engines", { action: "delete", id });
    latestSnap = res.snapshot;
    render(res.snapshot);
    renderStudioModal();
    showToast("已移除自定义引擎");
  } catch (e) { showToast(e.message); }
}

// --- Visual MCP Manager ---
function renderMcpPane() {
  const mcp = latestSnap?.mcp || { servers: [], templates: [], last_scan: {} };
  const clis = latestSnap?.clis || {};
  const readyClis = ["agy", "codex", "claude"].filter(c => clis[c]?.installed).map(c => c.toUpperCase());
  const hint = document.getElementById("mcpCliHint");
  if (hint) {
    hint.textContent = readyClis.length
      ? `${t("可一键同步至：", "One-click sync to: ")}${readyClis.join(" / ")}`
      : t("未检测到支持 MCP 的本地 CLI", "No MCP-compatible local CLI detected");
  }

  const templates = mcp.templates || [];
  const tplBtns = document.getElementById("mcpTemplateBtns");
  if (tplBtns) {
    tplBtns.innerHTML = templates.map(tpl => {
      const m = fmtMcpTemplate(tpl);
      return `<button class="btn sm" onclick="applyMcpTemplate('${escapeHtml(tpl.id)}')">${escapeHtml(m.title)}</button>`;
    }).join("");
  }

  const quickGrid = document.getElementById("mcpQuickTemplatesGrid");
  if (quickGrid) {
    quickGrid.innerHTML = templates.map(tpl => {
      const m = fmtMcpTemplate(tpl);
      return `
      <div class="skill-card" style="padding:10px;cursor:pointer;" onclick="applyMcpTemplate('${escapeHtml(tpl.id)}', true)">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">
          <strong style="font-size:12.5px;">${escapeHtml(m.title)}</strong>
          <span class="skill-src">${escapeHtml(tpl.transport)}</span>
        </div>
        <span style="font-size:11.5px;color:var(--text-muted);">${escapeHtml(m.desc)}</span>
      </div>`;
    }).join("");
  }

  const servers = mcp.servers || [];
  const listBox = document.getElementById("mcpListBox");
  if (listBox) {
    if (!servers.length) {
      listBox.innerHTML = `<div style="font-size:12px;color:var(--text-muted);padding:4px 2px;">${t("尚未添加任何 MCP 工具，点下方常用模板即可 10 秒零 JSON 接入。", "No MCP tools added yet. Click any template below to set up in 10 seconds with zero JSON.")}</div>`;
    } else {
      listBox.innerHTML = servers.map(s => {
        const endpoint = s.transport === "http" ? s.url : `${s.command} ${(s.args || []).join(" ")}`.trim();
        const synced = (s.synced_clis || []).map(c => `<span class="skill-src" style="color:var(--c-dsh);">${escapeHtml(c.toUpperCase())}</span>`).join("");
        return `
          <div class="skill-card active">
            <div class="skill-top">
              <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                <strong style="font-size:13px;">${escapeHtml(s.title || s.name)}</strong>
                <span class="skill-src">${escapeHtml(s.name)} · ${escapeHtml(s.transport)}</span>
                ${synced || `<span class="skill-src">${t("未同步 CLI", "Not synced")}</span>`}
              </div>
              <div style="display:flex;gap:5px;">
                <button class="btn sm" onclick="editMcpServer('${escapeHtml(s.name)}')">${t("编辑", "Edit")}</button>
                <button class="btn sm" onclick="syncMcpServer('${escapeHtml(s.name)}')">${t("同步 CLI", "Sync CLI")}</button>
                <button class="btn sm danger" onclick="deleteMcpServer('${escapeHtml(s.name)}')">${t("删除", "Delete")}</button>
              </div>
            </div>
            ${s.desc ? `<div style="font-size:12px;color:var(--text-sec);">${escapeHtml(s.desc)}</div>` : ""}
            <div style="font-size:11px;color:var(--text-muted);font-family:Consolas,monospace;word-break:break-all;">${escapeHtml(endpoint)}</div>
          </div>`;
      }).join("");
    }
  }

  const scanBox = document.getElementById("mcpScanBox");
  const lastScan = mcp.last_scan || {};
  const scanKeys = Object.keys(lastScan);
  if (scanBox) {
    if (!scanKeys.length) {
      scanBox.style.display = "none";
    } else {
      scanBox.style.display = "flex";
      scanBox.innerHTML = `<div class="insp-card-title">${t("本机 CLI 现有 MCP 列表", "Configured MCPs in Local CLIs")}</div>` + scanKeys.map(cid => {
        const item = lastScan[cid] || {};
        const lines = (item.lines || []).length ? item.lines.map(l => escapeHtml(l)).join("\n") : t("(暂无已配置服务)", "(No configured servers)");
        return `<div style="font-size:11.5px;"><strong style="color:var(--text);">${escapeHtml(cid.toUpperCase())}</strong><pre style="margin:4px 0 0;padding:7px 9px;border-radius:7px;background:var(--bg-surface);border:1px solid var(--border);font-family:Consolas,monospace;font-size:11px;color:var(--text-sec);white-space:pre-wrap;max-height:110px;overflow:auto;">${lines}</pre></div>`;
      }).join("");
    }
  }
}

function toggleMcpForm(force) {
  const box = document.getElementById("mcpFormBox");
  if (!box) return;
  const show = typeof force === "boolean" ? force : box.style.display === "none";
  box.style.display = show ? "flex" : "none";
}

function toggleMcpTransportFields() {
  const t = document.getElementById("mcpTransport").value;
  document.getElementById("mcpStdioFields").style.display = t === "stdio" ? "grid" : "none";
  document.getElementById("mcpHttpFields").style.display = t === "http" ? "block" : "none";
}

function applyMcpTemplate(id, openForm = false) {
  const tpl = (latestSnap?.mcp?.templates || []).find(t => t.id === id);
  if (!tpl) return;
  if (openForm) toggleMcpForm(true);
  document.getElementById("mcpName").value = tpl.name || "";
  document.getElementById("mcpTitle").value = tpl.title || "";
  document.getElementById("mcpDesc").value = tpl.desc || "";
  document.getElementById("mcpTransport").value = tpl.transport || "stdio";
  toggleMcpTransportFields();
  document.getElementById("mcpCmd").value = tpl.command || "";
  document.getElementById("mcpArgs").value = (tpl.args || []).join(" ");
  document.getElementById("mcpUrl").value = tpl.url || "";
  document.getElementById("mcpEnv").value = (tpl.env_hints || []).map(k => `${k}=`).join("\n");
  document.getElementById("mcpFormBox").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function editMcpServer(name) {
  const srv = (latestSnap?.mcp?.servers || []).find(s => s.name === name);
  if (!srv) return;
  toggleMcpForm(true);
  document.getElementById("mcpName").value = srv.name || "";
  document.getElementById("mcpTitle").value = srv.title || "";
  document.getElementById("mcpDesc").value = srv.desc || "";
  document.getElementById("mcpTransport").value = srv.transport || "stdio";
  toggleMcpTransportFields();
  document.getElementById("mcpCmd").value = srv.command || "";
  document.getElementById("mcpArgs").value = (srv.args || []).join(" ");
  document.getElementById("mcpUrl").value = srv.url || "";
  document.getElementById("mcpEnv").value = Object.entries(srv.env || {}).map(([k, v]) => `${k}=${v}`).join("\n");
}

async function submitMcpServer() {
  const payload = {
    action: "save",
    name: document.getElementById("mcpName").value.trim(),
    title: document.getElementById("mcpTitle").value.trim(),
    desc: document.getElementById("mcpDesc").value.trim(),
    transport: document.getElementById("mcpTransport").value,
    command: document.getElementById("mcpCmd").value.trim(),
    args: document.getElementById("mcpArgs").value.trim(),
    url: document.getElementById("mcpUrl").value.trim(),
    env: document.getElementById("mcpEnv").value,
    auto_sync: document.getElementById("mcpAutoSync").checked
  };
  if (!payload.name) { showToast("请先填写工具英文标识"); return; }
  try {
    showToast(payload.auto_sync ? "正在保存并同步到本机 CLI…" : "正在保存 MCP 配置…");
    const res = await api("/api/mcp", payload);
    latestSnap = res.snapshot;
    render(res.snapshot);
    renderStudioModal();
    toggleMcpForm(false);
    const synced = res.sync?.synced || [];
    showToast(synced.length ? `已保存并同步至：${synced.join(", ").toUpperCase()}` : "MCP 配置已保存");
  } catch (e) { showToast(e.message); }
}

async function syncMcpServer(name) {
  try {
    showToast(`正在将 ${name} 同步到本机已装 CLI…`);
    const res = await api("/api/mcp", { action: "sync", name });
    latestSnap = res.snapshot;
    render(res.snapshot);
    renderStudioModal();
    const synced = res.sync?.synced || [];
    showToast(synced.length ? `已同步至：${synced.join(", ").toUpperCase()}` : "未检测到可同步的本地 CLI");
  } catch (e) { showToast(e.message); }
}

async function deleteMcpServer(name) {
  if (!confirm(`确定删除 MCP 工具「${name}」？（同时从本机已同步的 CLI 中移除）`)) return;
  try {
    const res = await api("/api/mcp", { action: "delete", name, unsync: true });
    latestSnap = res.snapshot;
    render(res.snapshot);
    renderStudioModal();
    showToast(`已移除 MCP：${name}`);
  } catch (e) { showToast(e.message); }
}

async function scanCliMcps() {
  try {
    showToast("正在扫描本机 CLI 已配置的 MCP…");
    const res = await api("/api/mcp", { action: "scan" });
    latestSnap = res.snapshot;
    render(res.snapshot);
    renderStudioModal();
    showToast("已刷新本机 CLI MCP 列表");
  } catch (e) { showToast(e.message); }
}

// --- Toast ---
function showToast(txt) {
  const el = document.getElementById("toast");
  el.textContent = txt;
  el.style.display = "block";
  clearTimeout(window._tt);
  window._tt = setTimeout(() => { el.style.display = "none"; }, 3000);
}

// --- Mode Selector + @mention Auto-Routing ---
function syncRailHighlight() {
  const job = latestSnap?.live_job || {};
  const activeTarget = job.pending_approval ? "xiu" : (currentMode === "pipeline" ? "agy" : currentMode);
  ["xiu", "agy", "codex", "dsh"].forEach(id => {
    const node = document.getElementById("rnode-" + id);
    if (!node) return;
    const isRun = !!job.running && job.agent === id;
    node.classList.toggle("is-running", isRun);
    node.classList.toggle("is-lock", !job.running && activeTarget === id);
  });
}

function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll(".mode-pill").forEach(p => p.classList.toggle("active", p.dataset.mode === mode));
  syncRailHighlight();
}
const cmdInput = document.getElementById("cmdInput");
cmdInput.addEventListener("input", () => {
  cmdInput.style.height = "auto";
  cmdInput.style.height = Math.min(180, cmdInput.scrollHeight) + "px";
  const v = cmdInput.value;
  if (/^@codex\s/i.test(v)) { setMode("codex"); cmdInput.value = v.replace(/^@codex\s/i, ""); }
  else if (/^@agy\s/i.test(v)) { setMode("agy"); cmdInput.value = v.replace(/^@agy\s/i, ""); }
  else if (/^@dsh\s/i.test(v)) { setMode("dsh"); cmdInput.value = v.replace(/^@dsh\s/i, ""); }
  else if (/^@auto\s/i.test(v)) { setMode("pipeline"); cmdInput.value = v.replace(/^@auto\s/i, ""); }

  const sm = cmdInput.value.match(/(?:^|\s)\/([a-zA-Z0-9_\-\u4e00-\u9fa5]*)$/);
  if (sm) toggleSlashMenu(true, sm[1] || "");
  else toggleSlashMenu(false);
});
cmdInput.addEventListener("keydown", e => {
  if (e.key === "Escape") { toggleSlashMenu(false); togglePlusMenu(false); }
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    handlePrimarySend();
  }
});
cmdInput.addEventListener("paste", e => {
  const items = e.clipboardData?.items;
  if (!items) return;
  const files = [];
  for (const it of items) {
    if (it.kind === "file") {
      const f = it.getAsFile();
      if (f) files.push(f);
    }
  }
  if (files.length) {
    e.preventDefault();
    handlePickedFiles(files);
  }
});
const composerBox = document.getElementById("composerBox");
if (composerBox) {
  composerBox.addEventListener("dragover", e => { e.preventDefault(); composerBox.classList.add("drag-over"); });
  composerBox.addEventListener("dragleave", () => composerBox.classList.remove("drag-over"));
  composerBox.addEventListener("drop", e => {
    e.preventDefault();
    composerBox.classList.remove("drag-over");
    if (e.dataTransfer?.files?.length) handlePickedFiles(e.dataTransfer.files);
  });
}

// --- Ultra-Minimal Vertical Paper-Plane Animation ---
function flyMiniPlane(fromId, toId) {
  const y1 = RAIL_Y[fromId] ?? 30;
  const y2 = RAIL_Y[toId] ?? 106;
  const plane = document.getElementById("miniPlane");
  const trail = document.getElementById("miniTrail");
  const curveX = fromId === toId ? 6 : (y2 > y1 ? 37 : 9);
  const midY = (y1 + y2) / 2;

  trail.setAttribute("d", `M 23,${y1} Q ${curveX},${midY} 23,${y2}`);
  trail.setAttribute("opacity", "0.75");
  plane.setAttribute("opacity", "1");

  if (railAnim) cancelAnimationFrame(railAnim);
  const start = performance.now();
  function step(now) {
    const t = Math.min(1, (now - start) / 680);
    const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    const x = (1 - e) * (1 - e) * 23 + 2 * (1 - e) * e * curveX + e * e * 23;
    const y = (1 - e) * (1 - e) * y1 + 2 * (1 - e) * e * midY + e * e * y2;
    const dx = 2 * (1 - e) * (curveX - 23) + 2 * e * (23 - curveX);
    const dy = 2 * (1 - e) * (midY - y1) + 2 * e * (y2 - midY);
    const ang = Math.atan2(dy, dx) * 180 / Math.PI;
    plane.setAttribute("transform", `translate(${x.toFixed(1)}, ${y.toFixed(1)}) rotate(${ang.toFixed(1)})`);
    if (t < 1) {
      railAnim = requestAnimationFrame(step);
    } else {
      setTimeout(() => { plane.setAttribute("opacity", "0"); trail.setAttribute("opacity", "0"); }, 260);
      const rip = document.getElementById("rrip-" + toId);
      if (rip) { rip.classList.remove("go"); void rip.offsetWidth; rip.classList.add("go"); }
    }
  }
  railAnim = requestAnimationFrame(step);
}

// --- Clean Markdown Renderer (GFM Tables, Links, Code Blocks & Live Stream) ---
function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}
function renderMarkdown(md, streaming = false) {
  let src = String(md || "");
  // Gracefully close an unfinished fenced code block while streaming
  if (streaming && ((src.match(/```/g) || []).length % 2 === 1)) {
    src += "\n```";
  }
  const codeBlocks = [];
  let text = src.replace(/```([\w-]*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang: lang || "text", code: code.replace(/\n$/, "") });
    return `\n@@CODEBLOCK_${idx}@@\n`;
  });

  const lines = text.split("\n");
  let out = [];
  let inUl = false;
  let inOl = false;

  function closeLists() {
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
  }
  function inlineFmt(s) {
    const tokens = [];
    let raw = String(s || "").replace(/`([^`\n]+)`/g, (_, code) => {
      const idx = tokens.length;
      tokens.push(`<code class="inline">${escapeHtml(code)}</code>`);
      return `@@INL_${idx}@@`;
    });
    let h = escapeHtml(raw);
    h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a class="md-link" href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    h = h.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/(^|[^\w*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    h = h.replace(/@@INL_(\d+)@@/g, (_, i) => tokens[Number(i)] || "");
    return h;
  }

  function splitTableRow(row) {
    let r = row.trim();
    if (r.startsWith("|")) r = r.slice(1);
    if (r.endsWith("|")) r = r.slice(0, -1);
    return r.split("|").map(c => c.trim());
  }
  function isTableSep(row) {
    const t = row.trim();
    if (!t.includes("-")) return false;
    const cells = splitTableRow(t);
    return cells.length >= 2 && cells.every(c => /^:?-{3,}:?$/.test(c));
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    const cbMatch = line.trim().match(/^@@CODEBLOCK_(\d+)@@$/);
    if (cbMatch) {
      closeLists();
      const cb = codeBlocks[Number(cbMatch[1])];
      const safeId = `cb_${Math.random().toString(36).slice(2, 8)}`;
      out.push(`<div class="code-block"><div class="code-head"><span>${escapeHtml(cb.lang)}</span><button class="copy-mini" onclick="copyCode('${safeId}')">复制</button></div><pre id="${safeId}">${escapeHtml(cb.code)}</pre></div>`);
      continue;
    }
    if (!line.trim()) { closeLists(); continue; }

    // GFM Table detection: header line + alignment separator line
    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      closeLists();
      const headers = splitTableRow(line);
      const aligns = splitTableRow(lines[i + 1]).map(c => {
        if (c.startsWith(":") && c.endsWith(":")) return "center";
        if (c.endsWith(":")) return "right";
        return "left";
      });
      i += 1;
      const bodyRows = [];
      while (i + 1 < lines.length && lines[i + 1].trim() && lines[i + 1].includes("|")) {
        i += 1;
        bodyRows.push(splitTableRow(lines[i]));
      }
      const thHtml = headers.map((c, ci) => `<th style="text-align:${aligns[ci] || 'left'}">${inlineFmt(c)}</th>`).join("");
      const tbHtml = bodyRows.map(r => `<tr>${headers.map((_, ci) => `<td style="text-align:${aligns[ci] || 'left'}">${inlineFmt(r[ci] || "")}</td>`).join("")}</tr>`).join("");
      out.push(`<div class="md-table-wrap"><table class="md-table"><thead><tr>${thHtml}</tr></thead><tbody>${tbHtml}</tbody></table></div>`);
      continue;
    }

    if (/^---+$/.test(line.trim())) { closeLists(); out.push('<hr style="border:none;border-top:1px solid var(--border);margin:12px 0;"/>'); continue; }
    if (line.startsWith("### ")) { closeLists(); out.push(`<h3>${inlineFmt(line.slice(4))}</h3>`); continue; }
    if (line.startsWith("## ")) { closeLists(); out.push(`<h2>${inlineFmt(line.slice(3))}</h2>`); continue; }
    if (line.startsWith("# ")) { closeLists(); out.push(`<h1>${inlineFmt(line.slice(2))}</h1>`); continue; }
    if (line.startsWith("> ")) { closeLists(); out.push(`<blockquote>${inlineFmt(line.slice(2))}</blockquote>`); continue; }
    if (/^[-*]\s+/.test(line.trim())) {
      if (inOl) { out.push("</ol>"); inOl = false; }
      if (!inUl) { out.push("<ul>"); inUl = true; }
      out.push(`<li>${inlineFmt(line.trim().replace(/^[-*]\s+/, ""))}</li>`);
      continue;
    }
    if (/^\d+\.\s+/.test(line.trim())) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (!inOl) { out.push("<ol>"); inOl = true; }
      out.push(`<li>${inlineFmt(line.trim().replace(/^\d+\.\s+/, ""))}</li>`);
      continue;
    }
    closeLists();
    out.push(`<p>${inlineFmt(line)}</p>`);
  }
  closeLists();
  if (streaming) out.push('<span class="stream-cursor"></span>');
  return out.join("");
}

function copyCode(id) {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard?.writeText(el.textContent || "");
  showToast("已复制代码");
}

function wsSvgIcon(type) {
  if (type === "aigc-studio") return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M17 3v18"/><path d="M3 8h4"/><path d="M3 16h4"/><path d="M17 8h4"/><path d="M17 16h4"/></svg>`;
  if (type === "godot-game") return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="6" x2="10" y1="12" y2="12"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="15" x2="15.01" y1="13" y2="13"/><line x1="18" x2="18.01" y1="11" y2="11"/><rect width="20" height="12" x="2" y="6" rx="2"/></svg>`;
  if (type === "web-app") return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>`;
  if (type === "python") return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>`;
  if (type === "docs") return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg>`;
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>`;
}

// --- Render Chat Stream (Strictly respects user scroll-up!) ---
function renderChat(msgs, job) {
  const scrollEl = document.getElementById("chatScroll");
  const container = document.getElementById("chatStream");
  const recent = (msgs || []).slice(-40);
  const activeThread = latestSnap?.active_thread || {};
  const isJobHere = !!job.running && (!job.thread_id || job.thread_id === activeThread.id);
  const curUName = latestSnap?.settings?.user_name || "我";
  const sig = JSON.stringify({
    tid: activeThread.id || "",
    lang: currentLang,
    uname: curUName,
    period: getTimePeriodLabel(),
    sumLen: (activeThread.summary || "").length,
    n: recent.length,
    last: recent.length ? recent[recent.length - 1].id : "",
    run: isJobHere,
    ag: job.agent || "",
    step: job.current_step_desc || "",
    liveLen: isJobHere ? (job.live_reply || "").length : 0,
    logsLen: isJobHere ? (job.logs || []).length : 0,
    sec: isJobHere ? Math.floor(job.elapsed_seconds || 0) : 0
  });
  if (sig === lastChatSig) return;

  const isFirst = !lastChatSig;
  const prevTop = scrollEl.scrollTop;
  const wasAtBottom = isFirst || (scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight) < 48;
  lastChatSig = sig;
  window._recentMsgs = recent;

  if (!recent.length && !isJobHere) {
    const wsName = latestSnap?.active_workspace?.name || t("当前空间", "Workspace");
    const wsType = latestSnap?.active_workspace?.type || "general";
    const isAigc = wsType === "aigc-studio";
    const isGame = wsType === "godot-game";
    const engines = latestSnap?.engines || [];
    const roles = latestSnap?.roles || {};
    const readyEngines = engines.filter(e => e.ready);
    const hasUnreadyRole = ["planner", "builder"].some(s => {
      const eng = engines.find(e => e.id === roles[s]?.engine);
      return !eng || !eng.ready;
    });

    const envHtml = readyEngines.length
      ? `<div class="onboard-env">
          ${readyEngines.slice(0, 4).map(e => `<span class="env-pill"><i class="s-dot on"></i><span>${escapeHtml(e.name)}</span></span>`).join('<span class="env-sep">·</span>')}
          ${hasUnreadyRole ? `<span class="env-sep">|</span><button class="onboard-link" style="color:var(--c-agy);font-weight:550;" onclick="autoRecommendRoles(true)">${t("一键匹配最佳角色", "Auto-Bind Best Roles")}</button>` : ""}
        </div>`
      : `<div class="onboard-env" style="border-color:rgba(245,158,11,0.35);">
          <span class="env-pill"><i class="s-dot off" style="background:var(--c-warn);"></i><span>${t("尚未检测到本地 CLI", "No local CLI detected")}</span></span>
          <span class="env-sep">·</span>
          <button class="onboard-link" style="color:var(--c-warn);font-weight:550;" onclick="openStudioModal('engines')">${t("10 秒接入 Ollama 或云端 API →", "Connect Ollama or Cloud API in 10s →")}</button>
        </div>`;

    const starters = isAigc
      ? [
          { mode: "agy", tag: t("编剧 · 策划", "Script · Plan"), title: t("生成 60 秒漫剧脚本", "Draft a 60s Short Script"), desc: t("输出强悬念钩子与 8 个连贯分镜画面描述", "Strong 3s hook with an 8-shot storyboard table"), prompt: t("帮我构思一个 60 秒赛博朋克漫剧第 1 集脚本，要求前 3 秒有强悬念钩子，并输出 Markdown 分镜表（镜号、景别、台词、生图提示词）。", "Draft Episode 1 of a 60s cyberpunk short drama with a strong 3s hook and a Markdown storyboard table (Shot, Framing, Dialogue, Image Prompt).") },
          { mode: "codex", tag: t("制片 · 执行", "Produce · Build"), title: t("搭建资产与粗剪脚本", "Build Storyboard JSON & Edit Script"), desc: t("把分镜结构化为 JSON 并生成本地自动化脚本", "Structure shots into JSON and scaffold an assembly script"), prompt: t("请帮我把当前空间的分镜规划整理成结构化 JSON 存入 02_storyboard/，并创建一个基础的 Python 音画合成脚本框架。", "Organize our storyboard plan into structured JSON under 02_storyboard/ and scaffold a Python audio/video assembly script.") },
          { mode: "pipeline", tag: t("全自动流水线", "Auto Pipeline"), title: t("编剧 → 制片 → 审片", "Script → Produce → Review"), desc: t("端到端自动出方案、落地文件并做合规审片", "End-to-end planning, file generation, and consistency review"), prompt: t("请在本制片空间内规划一套短片分镜目录规范模板，自动创建示例脚本与分镜清单，并做一次一致性审查。", "Design a storyboard specification template for this studio, create sample script & shot files, and run a consistency review.") }
        ]
      : isGame
      ? [
          { mode: "agy", tag: t("策划 · 架构", "Design · Plan"), title: t("梳理玩法与数值平衡", "Analyze Core Loop & Balance"), desc: t("快速分析核心循环、手感指标与下轮优化点", "Review combat loop, game feel metrics, and next priorities"), prompt: t("请梳理当前游戏项目的核心战斗循环与最新一轮的优化重点，给出按优先级排序的 3 个改进方案。", "Analyze the core gameplay loop of this project and propose the top 3 prioritized improvements.") },
          { mode: "codex", tag: t("主程 · 执行", "Engine · Build"), title: t("排查报错并跑通自检", "Inspect Scripts & Run Self-Check"), desc: t("直接检查脚本警告、修复问题并执行无头验证", "Fix script warnings or hazards and run headless verification"), prompt: t("检查当前游戏工程脚本中是否存在潜在报错或性能隐患，直接修复并运行一次无头快速验证。", "Inspect project scripts for errors or performance issues, fix them, and run headless verification.") },
          { mode: "pipeline", tag: t("全自动流水线", "Auto Pipeline"), title: t("策划 → 编码 → 门禁核验", "Plan → Code → Gate Verify"), desc: t("自动出方案、写代码并跑完客观硬指标自检", "Auto-plan, implement in workspace, and verify gates"), prompt: t("请设计并实现一个小幅手感反馈增强（如受击顿帧或音效层次优化），完成后自动跑通自检门禁并汇报结果。", "Design and implement a clean game-feel polish, then run the self-check gates and report results.") }
        ]
      : [
          { mode: "agy", tag: t("策划 · 架构", "Architecture · Plan"), title: t("读懂当前项目架构", "Explore Project Architecture"), desc: t("快速梳理目录结构、关键模块与 3 个高价值优化点", "Summarize directory structure, key modules, and top 3 improvements"), prompt: t("帮我梳理当前工作空间的整体架构与核心文件职责，并给出接下来最值得优先优化的 3 个建议。", "Summarize the overall architecture and core module responsibilities of this workspace, and suggest the top 3 improvements.") },
          { mode: "codex", tag: t("执行 · 主程", "Builder · Code"), title: t("代码体检与快速修复", "Code Health Check & Fix"), desc: t("排查潜在 Bug、性能隐患并直接落地修复验证", "Spot potential bugs or edge cases, fix them, and verify"), prompt: t("请检查当前空间代码中是否存在潜在 Bug 或可改进之处，先简要列出发现，再直接完成安全修复并验证。", "Inspect this workspace for potential bugs or improvements, list your findings briefly, and apply safe fixes with verification.") },
          { mode: "pipeline", tag: t("全自动流水线", "Auto Pipeline"), title: t("方案 → 落地 → 独立审查", "Plan → Build → Independent Review"), desc: t("一条指令串联三位智能体，完整闭环交付", "Chain all three agents end-to-end with one instruction"), prompt: t("请先为当前项目构思一个实用且轻量的功能改进方案，再直接落地实现，最后做一次独立代码审查与风险总结。", "Propose a practical, lightweight improvement for this project, implement it directly, and finish with an independent code review.") }
        ];

    window._starterPrompts = starters;
    const greetingTitle = getGreetingLine(curUName);
    container.innerHTML = `
      <div class="empty-state" style="max-width:660px;margin-top:7vh;">
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">${t("当前空间", "Workspace")} · ${escapeHtml(wsName)}</div>
        <h3 style="font-size:23px;font-weight:600;letter-spacing:-0.02em;margin-bottom:14px;">${escapeHtml(greetingTitle)}</h3>
        ${envHtml}
        <div class="starter-grid">
          ${starters.map((st, idx) => `
            <div class="starter-card" onclick="applyStarter(${idx})">
              <div class="starter-tag">${escapeHtml(st.tag)}</div>
              <div class="starter-title">${escapeHtml(st.title)}</div>
              <div class="starter-desc">${escapeHtml(st.desc)}</div>
            </div>`).join("")}
        </div>
        <div class="onboard-links">
          <button class="onboard-link" onclick="openStudioModal('general')">${t("通用偏好", "General")}</button>
          <span>·</span>
          <button class="onboard-link" onclick="openStudioModal('roles')">${t("角色与引擎", "Roles & Engines")}</button>
          <span>·</span>
          <button class="onboard-link" onclick="openStudioModal('skills')">${t("技能 Skills", "Skills")}</button>
          <span>·</span>
          <button class="onboard-link" onclick="openStudioModal('mcp')">${t("外部工具 MCP", "MCP Tools")}</button>
          <span>·</span>
          <button class="onboard-link" onclick="openGuideModal()">${t("30 秒上手指南", "Quick Guide")}</button>
        </div>
      </div>`;
    return;
  }

  let html = recent.map((m, idx) => {
    const sender = m.from || "xiu";
    const ts = (m.ts || "").slice(11, 16);
    if (sender === "xiu") {
      const toInfo = ROLE_INFO[m.to] || { name: m.to };
      const atts = m.attachments || [];
      const attHtml = atts.length ? `<div class="msg-att-row">${atts.map(a => {
        if (a.is_image) {
          const url = `/api/image?path=${encodeURIComponent(a.path)}`;
          return `<img class="msg-att-img" src="${url}" title="${escapeHtml(a.name)}" onclick="window.open('${url}','_blank')" />`;
        }
        return `<span class="msg-att-file">${escapeHtml(a.name)}</span>`;
      }).join("")}</div>` : "";
      return `
        <div>
          <div class="msg-user-wrap"><div class="msg-user">${escapeHtml(m.body)}</div></div>
          ${attHtml}
          <div class="msg-user-meta"><span>${t("发给", "To")} ${escapeHtml(toInfo.name)}</span><span>·</span><span>${ts}</span></div>
        </div>`;
    }
    const info = ROLE_INFO[sender] || { name: sender, role: "" };
    let actions = "";
    if (sender === "agy" && !job.running) {
      actions = `
        <div class="handoff-bar">
          <button class="btn sm solid" onclick="approveAgyPlan(${idx})">${t("采纳方案并交棒 Codex", "Approve Plan & Hand Off")}</button>
          <button class="btn sm" onclick="prefillInput('${t("针对上面的方案，我想微调：", "Regarding the plan above, please adjust: ")}')">${t("继续微调", "Refine")}</button>
        </div>`;
    } else if (sender === "codex" && !job.running) {
      const wsType = latestSnap?.active_workspace?.type || "general";
      actions = wsType === "godot-game"
        ? `<div class="handoff-bar">
            <button class="btn sm solid" onclick="launchGame()">${t("启动试玩", "Launch Game")}</button>
            <button class="btn sm" onclick="runSelfCheck()">${t("自检三条", "Self-Check")}</button>
            <button class="btn sm" onclick="submitVerdict('PASS')">${t("验收通过", "Approve")}</button>
            <button class="btn sm danger" onclick="prefillInput('${t("退回修改原因：", "Rework reason: ")}')">${t("退回修改", "Reject")}</button>
          </div>`
        : `<div class="handoff-bar">
            <button class="btn sm" onclick="toggleInspector(true); switchInspTab('workspace')">${t("查看代码改动", "View Changes")}</button>
            <button class="btn sm" onclick="prefillInput('${t("请针对刚才的改动补充修改：", "Please make a follow-up adjustment: ")}')">${t("继续微调", "Follow Up")}</button>
          </div>`;
    }
    return `
      <div class="msg-agent">
        <div class="agent-head">
          <div class="agent-id">
            <i class="agent-dot ${sender}"></i>
            <span>${escapeHtml(info.name)}</span>
            <span class="agent-role">${escapeHtml(info.role)}</span>
          </div>
          <span class="agent-time">${ts}</span>
        </div>
        <div class="agent-body">${renderMarkdown(m.body)}</div>
        ${actions}
      </div>`;
  }).join("");

  let memHtml = "";
  if (activeThread.summary) {
    memHtml = `
      <details class="memory-banner">
        <summary>
          <span>${t(`已加载本对话压缩记忆（覆盖前 ${activeThread.compacted_count || 0} 条消息）`, `Compacted Session Memory (${activeThread.compacted_count || 0} messages summarized)`)}</span>
          <span style="color:var(--text-muted);font-size:11px;">${t("查看摘要 ▾", "View Summary ▾")}</span>
        </summary>
        <div class="memory-body">${renderMarkdown(activeThread.summary)}</div>
      </details>`;
  }

  if (isJobHere) {
    const ag = job.agent || "agy";
    const info = ROLE_INFO[ag] || { name: ag.toUpperCase(), role: "" };
    const step = job.current_step_desc || t("正在思考与执行…", "Thinking & executing…");
    const recentLogs = (job.logs || []).slice(-18).join("\n");
    const traceOpen = window._traceOpen ? "open" : "";
    html += `
      <div class="msg-agent" id="liveAgentCard" data-agent="${escapeHtml(ag)}">
        <div class="agent-head">
          <div class="agent-id">
            <i class="pulse-dot"></i>
            <span>${escapeHtml(info.name)}</span>
            <span class="agent-role">${escapeHtml(info.role)} · ${t("运行中", "Running")}</span>
          </div>
          <span class="agent-time" id="liveElapsed">${job.elapsed_seconds}s</span>
        </div>
        <details class="trace-box" ${traceOpen} ontoggle="window._traceOpen = this.open">
          <summary>
            <span id="liveStepDesc" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(step)}</span>
            <span style="color:var(--text-muted);font-size:11px;flex-shrink:0;">${t("执行步骤 ▾", "Steps ▾")}</span>
          </summary>
          <div class="trace-logs" id="liveTraceLogs">${escapeHtml(recentLogs || t("正在初始化进程…", "Initializing process…"))}</div>
        </details>
        <div class="agent-body" id="liveReplyBody" style="${job.live_reply ? '' : 'display:none;'}">${job.live_reply ? renderMarkdown(job.live_reply, true) : ""}</div>
      </div>`;
  }

  container.innerHTML = memHtml + html;
  scrollEl.scrollTop = wasAtBottom ? scrollEl.scrollHeight : prevTop;
}

// --- Main Render (Protected against stale polls & DOM click-swallowing) ---
let lastWsSig = "";
let lastAppliedVersion = 0;
let mutationInFlight = 0;

function render(snap, fromMutation = false) {
  if (!snap) return;
  const ver = Number(snap.version || 0);
  if (!fromMutation) {
    if (mutationInFlight > 0) return;
    if (ver > 0 && ver < lastAppliedVersion) return;
  }
  if (ver > lastAppliedVersion) lastAppliedVersion = ver;

  latestSnap = snap;
  if (!localStorage.getItem("sw_lang") && snap.settings?.lang && snap.settings.lang !== currentLang) {
    applyLang(snap.settings.lang);
    return;
  }
  const st = snap.state || {};
  const wsData = snap.workspaces || {};
  const activeWs = snap.active_workspace || {};
  const wsThreads = snap.threads || [];
  const activeThread = snap.active_thread || {};
  const isGame = activeWs.type === "godot-game";
  const job = snap.live_job || {};
  const items = wsData.items || [];

  // Sidebar Workspaces + Nested Threads under Active Workspace (DOM diff-guarded!)
  const wsSig = JSON.stringify({
    lang: currentLang,
    a: activeWs.id,
    t: activeThread.id,
    th: wsThreads.map(t => [t.id, t.title]),
    i: items.map(w => [w.id, w.name, w.path, w.type])
  });
  if (wsSig !== lastWsSig) {
    lastWsSig = wsSig;
    document.getElementById("wsList").innerHTML = items.map(w => {
      const isCur = w.id === activeWs.id;
      const threadTreeHtml = isCur ? `
        <div class="thread-tree">
          ${wsThreads.map(tItem => `
            <div class="thread-item ${tItem.id === activeThread.id ? 'active' : ''}" data-thread-id="${escapeHtml(tItem.id)}" onclick="switchThread('${escapeHtml(tItem.id)}')">
              <span class="thread-title">${escapeHtml(fmtThreadTitle(tItem.title))}</span>
              <div class="thread-acts" onclick="event.stopPropagation()">
                <button class="ws-act-btn" style="width:20px;height:20px;" title="${t('重命名对话', 'Rename Thread')}" onclick="renameThreadPrompt('${escapeHtml(tItem.id)}')">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                </button>
                ${wsThreads.length > 1 ? `
                <button class="ws-act-btn del" style="width:20px;height:20px;" title="${t('删除对话', 'Delete Thread')}" onclick="deleteThreadConfirm('${escapeHtml(tItem.id)}')">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/></svg>
                </button>` : ""}
              </div>
            </div>`).join("")}
          <button class="thread-new-btn" onclick="createNewThread()">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
            <span>${t("新对话", "New Thread")}</span>
          </button>
        </div>` : "";

      return `
        <div>
          <div class="ws-item ${isCur ? 'active' : ''}" data-ws-id="${escapeHtml(w.id)}" onclick="switchWorkspace('${escapeHtml(w.id)}')">
            <span class="ws-icon">${wsSvgIcon(w.type)}</span>
            <div class="ws-meta">
              <div class="ws-name">${escapeHtml(w.name)}</div>
              <div class="ws-path">${escapeHtml(w.path)}</div>
            </div>
            <div class="ws-actions" onclick="event.stopPropagation()">
              <button class="ws-act-btn" title="${t('重命名 / 编辑路径', 'Rename / Edit Path')}" onclick="openRenameModal('${escapeHtml(w.id)}')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
              </button>
              ${items.length > 1 ? `
              <button class="ws-act-btn del" title="${t('从工作台移除空间', 'Remove Workspace')}" onclick="openDelModal('${escapeHtml(w.id)}')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
              </button>` : ""}
            </div>
          </div>
          ${threadTreeHtml}
        </div>`;
    }).join("");
  }
  const tCrumb = document.getElementById("threadCrumb");
  if (tCrumb) tCrumb.textContent = fmtThreadTitle(activeThread.title);

  // Dynamic User Display Name (De-personalized, customizable in Settings)
  const rawUName = (snap.settings?.user_name || "我").trim() || "我";
  const userName = (rawUName === "我" && currentLang === "en") ? "Me" : rawUName;
  const userShort = /^[\x00-\x7F]+$/.test(userName) ? userName.slice(0, 3) : userName.slice(0, 2);
  ROLE_INFO.xiu = { name: userName, role: t("发起人", "Producer") };
  const rTxtXiu = document.getElementById("rtxt-xiu");
  if (rTxtXiu) rTxtXiu.textContent = userShort;
  const rTitleXiu = document.getElementById("rtitle-xiu");
  if (rTitleXiu) rTitleXiu.textContent = `${userName} · ${t("发起人 / 终审", "Producer / Review")}`;

  // Dynamic Role Slots & Engine Badges
  const roles = snap.roles || {};
  const engines = snap.engines || [];
  const engMap = Object.fromEntries(engines.map(e => [e.id, e]));
  const isAigc = activeWs.type === "aigc-studio";

  const slotToNode = { planner: "agy", builder: "codex", reviewer: "dsh" };
  const summaryParts = [];
  ["planner", "builder", "reviewer"].forEach(slotId => {
    const r = roles[slotId] || {};
    const eng = engMap[r.engine] || { short: (r.engine || "?").slice(0, 3).toUpperCase(), name: r.engine || "未绑定", ready: false };
    const dot = document.getElementById("dot-" + slotId);
    if (dot) dot.className = "s-dot " + (eng.ready ? "on" : "off");

    const nodeId = slotToNode[slotId];
    const defaultShort = isAigc
      ? (slotId === "planner" ? t("编剧", "Script") : slotId === "builder" ? t("制片", "Produce") : t("审片", "Review"))
      : (slotId === "planner" ? t("策划", "Plan") : slotId === "builder" ? t("执行", "Build") : t("质检", "Review"));
    const roleShort = (r.custom_label || "").trim() || defaultShort;

    const pLbl = document.getElementById("pill-label-" + nodeId);
    if (pLbl) pLbl.textContent = `${roleShort} · ${eng.short}`;

    const rTxt = document.getElementById("rtxt-" + nodeId);
    if (rTxt) rTxt.textContent = eng.short;
    const rTitle = document.getElementById("rtitle-" + nodeId);
    if (rTitle) rTitle.textContent = `${roleShort} · ${eng.name}${r.model ? ' (' + r.model + ')' : ''}`;

    const roleDisplay = (r.custom_label || "").trim() || (isAigc ? (r.aigc_label || roleShort) : (r.label || roleShort));
    ROLE_INFO[nodeId] = {
      name: eng.name,
      role: `${roleDisplay}${r.model ? ' · ' + r.model : ''}`
    };
    summaryParts.push(`${eng.short}`);
  });

  // Populate Quick Model Switcher Popover (1-click fast switching!)
  const pRole = roles.planner || {};
  const bRole = roles.builder || {};
  const pEng = engMap[pRole.engine] || {};
  const bEng = engMap[bRole.engine] || {};
  const qPLbl = document.getElementById("quickPlannerLabel");
  const qBLbl = document.getElementById("quickBuilderLabel");
  if (qPLbl) qPLbl.textContent = `${t("策划模型", "Planner Model")} (${pEng.name || pRole.engine || 'AGY'})`;
  if (qBLbl) qBLbl.textContent = `${t("执行模型", "Builder Model")} (${bEng.name || bRole.engine || 'Codex'})`;

  const fillQuickSelect = (selId, eng, curVal) => {
    const sel = document.getElementById(selId);
    if (!sel || document.activeElement === sel) return;
    const list = (eng.models && eng.models.length) ? eng.models : (curVal ? [{ id: curVal, label: curVal }] : []);
    const hasCur = list.some(m => m.id === curVal);
    sel.innerHTML =
      (!hasCur && curVal ? `<option value="${escapeHtml(curVal)}" selected>${escapeHtml(curVal)}</option>` : "") +
      list.map(m => `<option value="${escapeHtml(m.id)}" ${m.id === curVal ? 'selected' : ''}>${escapeHtml(m.label || m.id)}</option>`).join("");
  };
  fillQuickSelect("quickPlannerModel", pEng, pRole.model || pEng.default_model || "");
  fillQuickSelect("quickBuilderModel", bEng, bRole.model || bEng.default_model || "");

  const qEffField = document.getElementById("quickEffortField");
  const qEffSel = document.getElementById("quickBuilderEffort");
  if (qEffField) qEffField.style.display = bEng.supports_effort ? "block" : "none";
  if (qEffSel && document.activeElement !== qEffSel) qEffSel.value = bRole.effort || "high";

  const shortP = (pRole.model || pEng.short || "").replace(/^gemini-/, "G").replace(/^claude-/, "C-");
  const shortB = bRole.model || bEng.short || "";
  document.getElementById("engineSummary").textContent = `${shortP} · ${shortB}`;

  // Update Skills count for composer menu
  const skillsList = snap.skills || [];
  const activeSkillsCount = skillsList.filter(s => s.active).length;
  const chipTxt = document.getElementById("activeSkillChipText");
  if (chipTxt) chipTxt.textContent = activeSkillsCount > 0 ? `${t("技能", "Skills")} (${activeSkillsCount})` : t("技能", "Skills");

  // Header
  document.getElementById("wsTitle").textContent = activeWs.name || "Workspace";
  document.getElementById("wsSub").textContent = isGame ? `R${st.current_round ?? '—'} · ${t("最新可玩", "Playable")} R${st.latest_playable_round ?? '—'}` : (activeWs.type || "general");
  document.getElementById("btnLaunchText").textContent = isGame ? t("启动试玩", "Launch Game") : t("打开目录", "Open Folder");

  const pill = document.getElementById("statusPill");
  const btnSend = document.getElementById("btnSend");
  const btnInsp = document.getElementById("btnInspector");
  if (job.running) {
    pill.className = "status-pill running";
    pill.innerHTML = `<i class="pulse-dot"></i><span>${escapeHtml((job.agent || "").toUpperCase())} · ${job.elapsed_seconds}s</span>`;
    btnSend.className = "send-btn stop";
    btnSend.title = t("中止当前任务", "Stop Running Task");
    btnSend.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>`;
    document.getElementById("composerHint").textContent = t("运行中 · 点击红钮可随时中止", "Running · Click red button to abort");
    btnInsp.classList.add("has-notif");
  } else {
    pill.className = "status-pill";
    pill.textContent = t("就绪", "Ready");
    btnSend.className = "send-btn";
    btnSend.title = t("发送 (Ctrl+Enter)", "Send (Ctrl+Enter)");
    btnSend.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>`;
    document.getElementById("composerHint").textContent = t("Ctrl+Enter 发送", "Ctrl+Enter to send");
    btnInsp.classList.remove("has-notif");
  }

  // Disputed Banner
  const disp = document.getElementById("disputedBanner");
  if (st.objection_active && snap.objection?.summary) {
    disp.classList.add("show");
    document.getElementById("disputedSummary").textContent = snap.objection.summary;
  } else {
    disp.classList.remove("show");
  }

  // Minimalist Inline Pipeline Approval Bar
  const apprBar = document.getElementById("approvalBar");
  const pend = job.pending_approval;
  if (apprBar) {
    const showAppr = !job.running && pend && pend.workspace_id === activeWs.id && (!pend.thread_id || pend.thread_id === activeThread.id);
    apprBar.classList.toggle("show", Boolean(showAppr));
  }

  // Mini Relay Rail Nodes
  syncRailHighlight();
  updateDesktopTitleAndNotify(job);

  // Messages + Mini Paper Plane Trigger
  const msgs = snap.messages || [];
  if (msgs.length) {
    const newest = msgs[msgs.length - 1];
    if (lastMsgId && newest.id !== lastMsgId) flyMiniPlane(newest.from, newest.to);
    lastMsgId = newest.id;
  }
  renderChat(msgs, job);

  // Inspector: Console (smart scroll lock)
  const cBox = document.getElementById("consoleBox");
  if (job.logs && job.logs.length) {
    const cTop = cBox.scrollTop;
    const cAtBot = (cBox.scrollHeight - cBox.scrollTop - cBox.clientHeight) < 40;
    const txt = job.logs.join("\n");
    if (cBox.textContent !== txt) {
      cBox.textContent = txt;
      cBox.scrollTop = cAtBot ? cBox.scrollHeight : cTop;
    }
  }

  // Inspector: Gates & Files
  const tel = snap.telemetry || {};
  const age = tel.last_age_seconds ?? 99999;
  document.getElementById("liveDiskAge").textContent = age < 60 ? `${age}s ${t("前更新", "ago")}` : (age < 3600 ? `${Math.floor(age/60)}m ${t("前更新", "ago")}` : "");

  const rms = snap.rounds_metrics || [];
  const measured = rms.filter(x => x.fps != null || x.report_exists);
  const latestM = measured.length ? measured[measured.length - 1] : {};
  document.getElementById("gatesCard").style.display = isGame ? "flex" : "none";
  if (isGame) {
    const scOk = snap.self_check?.status === "PASS" || snap.self_check?.status === "PASSED_BASELINE";
    const fpsOk = (latestM.fps ?? 0) >= 60;
    const latOk = (latestM.input_latency_ms ?? 999) < 100;
    const ac = snap.asset_contract || {};
    const rows = [
      [`R${latestM.round ?? '—'} ${t("桌面帧率", "Desktop FPS")}`, latestM.fps != null ? `${latestM.fps} FPS` : t("未测", "N/A"), fpsOk],
      [t("输入响应延迟", "Input Latency"), latestM.input_latency_ms != null ? `${latestM.input_latency_ms} ms` : t("未测", "N/A"), latOk],
      [t("提交前自检三条", "Pre-Submit 3 Gates"), scOk ? t("通过", "PASS") : t("待检", "PENDING"), scOk],
      [t("资产契约", "Asset Contract"), ac.status || t("待检", "PENDING"), ac.status === "PASS"]
    ];
    document.getElementById("gatesList").innerHTML = rows.map(([k, v, ok]) =>
      `<div class="gate-row"><span style="color:var(--text-sec)">${k}</span><span style="display:inline-flex;align-items:center;gap:6px;font-family:Consolas,monospace;font-size:12px;">${v}<i class="s-dot ${ok ? 'on' : ''}"></i></span></div>`
    ).join("");
  }

  document.getElementById("milestonesCard").style.display = ((isGame || isAigc) && (tel.milestones || []).length) ? "flex" : "none";
  const msTitle = document.getElementById("milestonesTitle");
  if (msTitle) msTitle.textContent = isAigc ? t("AIGC 五阶段制片进度", "AIGC 5-Stage Milestones") : t("本轮进度里程碑", "Round Milestones");
  document.getElementById("milestonesRow").innerHTML = (tel.milestones || []).map(m =>
    `<span class="ms-chip ${m.done ? 'done' : ''}">${m.done ? '✓ ' : ''}${escapeHtml(m.label)}</span>`
  ).join("");

  // Inspector: Git Changed Files
  const git = snap.git || {};
  const gitCard = document.getElementById("gitCard");
  if (git.is_repo && (git.files || []).length) {
    gitCard.style.display = "flex";
    document.getElementById("gitBranchTag").textContent = git.branch ? `${t("分支", "Branch")}: ${git.branch}` : "";
    const btnCommit = document.getElementById("btnGitCommit");
    if (btnCommit && !btnCommit.disabled) btnCommit.textContent = t(`提交 ${git.files.length} 个改动`, `Commit ${git.files.length} Changes`);
    document.getElementById("gitFilesBox").innerHTML = git.files.slice(0, 14).map(g => {
      const code = (g.status || "M")[0];
      const badgeCls = code === "?" ? "U" : code;
      return `<div class="file-item clickable" onclick="inspectFileDiff('${escapeHtml(g.file)}')"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(g.file)}</span><span class="diff-badge ${badgeCls}">${escapeHtml(g.status)}</span></div>`;
    }).join("");
  } else {
    gitCard.style.display = "none";
  }

  document.getElementById("recentFilesBox").innerHTML = (tel.recent_files || []).slice(0, 10).map(f =>
    `<div class="file-item clickable" onclick="inspectFileDiff('${escapeHtml(f.file)}')"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(f.file)}</span><span style="color:var(--text-muted);flex-shrink:0;">${f.mtime_str}</span></div>`
  ).join("") || `<div style="font-size:12px;color:var(--text-muted);">${t("暂无最近修改文件", "No recently modified files")}</div>`;

  // Inspector: AIGC Screening Room (Video + Audio + Storyboard Gallery)
  const aigc = snap.aigc || {};
  const hasAigcMedia = isAigc && ((aigc.videos || []).length || (aigc.audios || []).length || (aigc.images || []).length);
  const aigcCard = document.getElementById("aigcScreeningCard");
  if (aigcCard) {
    aigcCard.style.display = isAigc ? "flex" : "none";
    if (isAigc) {
      const aigcSig = JSON.stringify([aigc.videos, aigc.audios, aigc.images]);
      if (window._lastAigcSig !== aigcSig) {
        window._lastAigcSig = aigcSig;
        document.getElementById("aigcVideosBox").innerHTML = (aigc.videos || []).map(v => `
          <div>
            <video class="aigc-video" controls preload="metadata" src="/api/media?path=${encodeURIComponent(v.path)}"></video>
            <div style="font-size:11px;color:var(--text-muted);margin-top:3px;">${escapeHtml(v.rel)}</div>
          </div>`).join("");
        document.getElementById("aigcAudiosBox").innerHTML = (aigc.audios || []).map(a => `
          <div>
            <div style="font-size:11px;color:var(--text-sec);margin-bottom:2px;">${escapeHtml(a.rel)}</div>
            <audio class="aigc-audio" controls preload="metadata" src="/api/media?path=${encodeURIComponent(a.path)}"></audio>
          </div>`).join("");
        document.getElementById("aigcImagesBox").innerHTML = (aigc.images || []).map(im => {
          const url = `/api/image?path=${encodeURIComponent(im.path)}`;
          return `<div class="aigc-shot" onclick="window.open('${url}','_blank')" title="${escapeHtml(im.rel)}"><img src="${url}"/><div class="aigc-shot-cap">${escapeHtml(im.name)}</div></div>`;
        }).join("") || (!hasAigcMedia ? `<div style="grid-column:span 2;font-size:12px;color:var(--text-muted);padding:8px 0;">把分镜图、配音或成片放入 02_storyboard / 03_assets / 05_output，这里会自动显示画廊与审片播放器。</div>` : "");
      }
    }
  }

  // Inspector: Artifacts
  document.getElementById("codexPreview").textContent = snap.next_for_codex || "暂无施工单";
  const shots = [];
  const withShots = rms.filter(x => x.screenshot);
  if (withShots.length) {
    const c = withShots[withShots.length - 1];
    shots.push(`<div><img class="preview-img" src="/api/image?path=${encodeURIComponent(c.screenshot)}"/><div style="font-size:11px;color:var(--text-muted);margin-top:4px;">R${c.round} 实机 (${c.fps} FPS)</div></div>`);
  }
  if (isGame && snap.stage_concept_path) {
    shots.push(`<div><img class="preview-img" src="/api/image?path=${encodeURIComponent(snap.stage_concept_path)}"/><div style="font-size:11px;color:var(--text-muted);margin-top:4px;">深空轨道舱原画</div></div>`);
  }
  document.getElementById("mediaCard").style.display = shots.length ? "flex" : "none";
  document.getElementById("mediaGrid").innerHTML = shots.join("");
}

async function inspectFileDiff(relFile) {
  const card = document.getElementById("diffViewerCard");
  const title = document.getElementById("diffViewerTitle");
  const body = document.getElementById("diffViewerBody");
  card.style.display = "flex";
  title.textContent = `加载中: ${relFile}`;
  body.textContent = "正在读取文件 / Diff…";
  try {
    const res = await api(`/api/diff?file=${encodeURIComponent(relFile)}`);
    title.textContent = `${res.mode === 'diff' ? 'Git Diff' : '源码预览'} · ${res.file || relFile}`;
    if (res.mode === "diff") {
      body.innerHTML = (res.content || "").split("\n").map(line => {
        const esc = escapeHtml(line);
        if (line.startsWith("+") && !line.startsWith("+++")) return `<span class="diff-add">${esc}</span>`;
        if (line.startsWith("-") && !line.startsWith("---")) return `<span class="diff-del">${esc}</span>`;
        if (line.startsWith("@@")) return `<span class="diff-hunk">${esc}</span>`;
        return esc + "\n";
      }).join("");
    } else {
      body.textContent = res.content || "(空文件)";
    }
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    body.textContent = e.message || "读取失败";
  }
}

// --- API Actions (Non-overlapping polling + mutation priority) ---
async function api(path, body = null) {
  const isPost = body !== null;
  if (isPost) mutationInFlight++;
  try {
    const res = await fetch(path, isPost ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "请求失败");
    return data;
  } finally {
    if (isPost) mutationInFlight = Math.max(0, mutationInFlight - 1);
  }
}

async function refreshAll() {
  if (mutationInFlight > 0) return;
  try {
    const snap = await api("/api/state");
    render(snap, false);
  } catch (e) {}
}

async function handlePrimarySend() {
  requestDesktopNotifPerm();
  if (latestSnap?.live_job?.running) {
    await abortJob();
    return;
  }
  const instruction = cmdInput.value.trim();
  if (!instruction && !pendingAttachments.length) return;
  try {
    const res = await api("/api/dispatch", {
      target: currentMode,
      instruction,
      auto_run: true,
      skill_ids: [...attachedSkillIds],
      attachments: [...pendingAttachments]
    });
    cmdInput.value = "";
    cmdInput.style.height = "auto";
    attachedSkillIds = [];
    pendingAttachments = [];
    renderAttachedSkills();
    toggleSlashMenu(false);
    togglePlusMenu(false);
    render(res.snapshot, true);
    flyMiniPlane("xiu", currentMode === "pipeline" ? "agy" : currentMode);
  } catch (e) { showToast(e.message); }
}

async function approveAgyPlan(idx) {
  const m = (window._recentMsgs || [])[idx];
  const instruction = m && m.body
    ? `请按照刚才 AGY 制定的方案（以及 handoff/NEXT_FOR_CODEX.md）直接落地代码并完成验证：\n${m.body.slice(0, 1400)}`
    : "请按照 handoff/NEXT_FOR_CODEX.md 落地代码并完成自检验证。";
  try {
    const res = await api("/api/dispatch", { target: "codex", instruction, auto_run: true });
    render(res.snapshot);
    flyMiniPlane("agy", "codex");
    showToast("已交棒给 Codex 开始编码");
  } catch (e) { showToast(e.message); }
}

function prefillInput(prefix) {
  cmdInput.value = prefix;
  cmdInput.style.height = "auto";
  cmdInput.style.height = Math.min(180, cmdInput.scrollHeight) + "px";
  cmdInput.focus();
}

function applyStarter(idx) {
  const st = (window._starterPrompts || [])[idx];
  if (!st) return;
  setMode(st.mode || "agy");
  prefillInput(st.prompt || "");
}

async function saveUserName(val) {
  const clean = String(val || "").trim().slice(0, 16) || "我";
  try {
    lastChatSig = "";
    const res = await api("/api/settings", { user_name: clean });
    latestSnap = res.snapshot;
    render(res.snapshot, true);
    renderStudioModal();
    showToast(`称呼已更新为「${clean}」`);
  } catch (e) { showToast(e.message); }
}

async function abortJob() {
  try {
    const res = await api("/api/abort", {});
    render(res.snapshot);
    showToast("已中止当前运行任务");
  } catch (e) { showToast(e.message); }
}

// --- Git Inspector Loop: Diff -> AI Draft -> Commit (local only, never pushes) ---
async function draftCommitMessage() {
  const btn = document.getElementById("btnGitDraft");
  const box = document.getElementById("gitCommitMsg");
  if (!btn || !box) return;
  if (latestSnap?.live_job?.running) { showToast("当前有任务在运行，请稍后再起草"); return; }
  const label = btn.querySelector("span");
  btn.disabled = true;
  if (label) label.textContent = "起草中…";
  try {
    // Long-running read-only request: bypass mutation guard so live polling keeps flowing
    const resp = await fetch("/api/git", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "draft" }) });
    const res = await resp.json();
    if (!resp.ok || !res.ok) throw new Error(res.error || "起草失败");
    box.value = res.message || "";
    box.style.height = "auto";
    box.style.height = Math.min(160, box.scrollHeight + 2) + "px";
    box.focus();
    showToast("已生成提交信息，可直接修改后提交");
  } catch (e) {
    showToast(e.message);
  } finally {
    btn.disabled = false;
    if (label) label.textContent = "AI 起草";
  }
}

async function commitAllChanges() {
  const box = document.getElementById("gitCommitMsg");
  const btn = document.getElementById("btnGitCommit");
  const msg = (box?.value || "").trim();
  if (!msg) { showToast("请先填写提交信息，或点「AI 起草」"); box?.focus(); return; }
  btn.disabled = true;
  const prevText = btn.textContent;
  btn.textContent = "提交中…";
  try {
    const res = await api("/api/git", { action: "commit", message: msg });
    box.value = "";
    box.style.height = "";
    btn.disabled = false;
    render(res.snapshot, true);
    showToast(`已提交 ${res.commit?.hash || ""} · ${res.commit?.subject || ""}`);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = prevText;
    showToast(e.message);
  }
}

async function toggleApproveBeforeBuild(enabled) {
  try {
    const res = await api("/api/settings", { approve_before_build: Boolean(enabled) });
    latestSnap = res.snapshot;
    render(res.snapshot, true);
    showToast(enabled ? t("已开启：全自动执行前暂停审批", "Enabled: Pause for approval before build") : t("已关闭：全自动流水线直通执行", "Disabled: Auto pipeline runs straight through"));
  } catch (e) { showToast(e.message); }
}

async function toggleExitOnClose(enabled) {
  try {
    const res = await api("/api/settings", { exit_on_close: Boolean(enabled) });
    latestSnap = res.snapshot;
    render(res.snapshot, true);
    showToast(enabled ? t("已开启：关闭窗口时将同时退出后台服务", "Enabled: Background service stops when window closes") : t("已恢复默认：点 × 仅关闭窗口，后台保持运行", "Default: Clicking × only closes window"));
  } catch (e) { showToast(e.message); }
}

async function quitBackendService() {
  if (!confirm(t("确定立即停止后台服务并关闭工作台？", "Stop the background service and close Super Workbench now?"))) return;
  try {
    await fetch("/api/shutdown", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  } catch (e) {}
  showToast(t("后台服务已停止", "Background service stopped"));
  setTimeout(() => { try { window.close(); } catch (e) {} }, 250);
}

window.addEventListener("pagehide", () => {
  if (latestSnap?.settings?.exit_on_close && navigator.sendBeacon) {
    try {
      navigator.sendBeacon("/api/client_closed", new Blob(["{}"], { type: "application/json" }));
    } catch (e) {}
  }
});

async function handleApproval(action) {
  const note = action === "approve" ? cmdInput.value.trim() : "";
  try {
    const res = await api("/api/approve", { action, note });
    if (action === "approve") {
      cmdInput.value = "";
      cmdInput.style.height = "auto";
      flyMiniPlane("xiu", "codex");
      showToast("已批准方案，交棒给核心执行");
    } else {
      showToast("已取消自动交棒，可继续与策划调整方案");
    }
    render(res.snapshot, true);
  } catch (e) { showToast(e.message); }
}

async function saveModelConfig() {
  try {
    const res = await api("/api/models", {
      agy_model: document.getElementById("selAgyModel").value,
      codex_model: document.getElementById("selCodexModel").value,
      codex_effort: document.getElementById("selCodexEffort").value
    });
    render(res.snapshot);
    showToast("模型配置已更新");
  } catch (e) { showToast(e.message); }
}

// --- Multi-Thread Conversations & Context Compaction ---
async function createNewThread() {
  try {
    lastChatSig = "";
    lastWsSig = "";
    const res = await api("/api/thread", { action: "create", title: "新对话" });
    render(res.snapshot, true);
    cmdInput.focus();
    showToast("已新建对话");
  } catch (e) { showToast(e.message); }
}

async function switchThread(id) {
  if (!id) return;
  document.querySelectorAll(".thread-tree .thread-item").forEach(el => {
    el.classList.toggle("active", el.dataset.threadId === id);
  });
  try {
    lastChatSig = "";
    lastWsSig = "";
    const res = await api("/api/thread", { action: "switch", id });
    render(res.snapshot, true);
  } catch (e) { showToast(e.message); }
}

async function renameThreadPrompt(id) {
  const cur = (latestSnap?.threads || []).find(t => t.id === id);
  const next = prompt("重命名当前对话：", cur?.title || "");
  if (!next || !next.trim()) return;
  try {
    lastWsSig = "";
    const res = await api("/api/thread", { action: "rename", id, title: next.trim() });
    render(res.snapshot, true);
  } catch (e) { showToast(e.message); }
}

async function deleteThreadConfirm(id) {
  if (!confirm("确定删除该对话及其聊天记录？（绝不会删除本地代码文件）")) return;
  try {
    lastChatSig = "";
    lastWsSig = "";
    const res = await api("/api/thread", { action: "delete", id });
    render(res.snapshot, true);
    showToast("已删除对话");
  } catch (e) { showToast(e.message); }
}

async function compactCurrentThread() {
  const msgs = latestSnap?.messages || [];
  if (!msgs.length) { showToast("当前对话暂无消息，无需压缩"); return; }
  if (!confirm(`确定压缩当前对话（共 ${msgs.length} 条消息）为长期记忆摘要？\n压缩后后续每轮都会自动携带这份记忆摘要，防止长对话遗忘早期决策。`)) return;
  try {
    const res = await api("/api/compact", {});
    render(res.snapshot, true);
    showToast("正在后台提炼会话长期记忆摘要…");
  } catch (e) { showToast(e.message); }
}

// --- Workspace CRUD ---
async function switchWorkspace(id) {
  if (!id) return;
  // Instant optimistic highlight so click feels 0ms snappy
  document.querySelectorAll("#wsList .ws-item").forEach(el => {
    el.classList.toggle("active", el.dataset.wsId === id);
  });
  try {
    lastChatSig = "";
    const res = await api("/api/workspace", { action: "switch", id });
    lastWsSig = "";
    render(res.snapshot, true);
  } catch (e) { showToast(e.message); }
}
function openWsModal() {
  editingWsId = null;
  document.getElementById("wsModalTitle").textContent = "新建工作空间";
  document.getElementById("wsModalSubmit").textContent = "创建空间";
  document.getElementById("wsTypeField").style.display = "block";
  document.getElementById("newWsName").value = "";
  document.getElementById("newWsPath").value = "";
  document.getElementById("wsModal").classList.add("show");
  setTimeout(() => document.getElementById("newWsName").focus(), 40);
}
function openRenameModal(id) {
  const ws = (latestSnap?.workspaces?.items || []).find(x => x.id === id);
  if (!ws) return;
  editingWsId = id;
  document.getElementById("wsModalTitle").textContent = "编辑工作空间";
  document.getElementById("wsModalSubmit").textContent = "保存修改";
  document.getElementById("wsTypeField").style.display = "none";
  document.getElementById("newWsName").value = ws.name || "";
  document.getElementById("newWsPath").value = ws.path || "";
  document.getElementById("wsModal").classList.add("show");
}
function closeWsModal() { document.getElementById("wsModal").classList.remove("show"); }

async function submitWsModal() {
  const name = document.getElementById("newWsName").value.trim();
  const path = document.getElementById("newWsPath").value.trim();
  const type = document.getElementById("newWsType").value;
  if (!name || !path) { showToast("请填写名称与目录路径"); return; }
  try {
    const payload = editingWsId
      ? { action: "rename", id: editingWsId, name, path }
      : { action: "create", name, path, type };
    const res = await api("/api/workspace", payload);
    closeWsModal();
    lastChatSig = "";
    render(res.snapshot);
    showToast(editingWsId ? "已更新空间信息" : `已创建空间：${name}`);
  } catch (e) { showToast(e.message); }
}

function openDelModal(id) {
  const ws = (latestSnap?.workspaces?.items || []).find(x => x.id === id);
  if (!ws) return;
  deletingWsId = id;
  document.getElementById("delWsName").textContent = ws.name;
  document.getElementById("delModal").classList.add("show");
}
function closeDelModal() { document.getElementById("delModal").classList.remove("show"); }
async function confirmDeleteWorkspace() {
  if (!deletingWsId) return;
  const purge = document.getElementById("delPurgeMsgs").checked;
  try {
    const res = await api("/api/workspace", { action: "delete", id: deletingWsId, purge_messages: purge });
    closeDelModal();
    lastChatSig = "";
    render(res.snapshot);
    showToast("已从工作台移除该空间");
  } catch (e) { showToast(e.message); }
}

async function clearCurrentChat() {
  if (!confirm("确定清空当前空间的对话记录？（不会影响本地代码文件）")) return;
  try {
    const res = await api("/api/clear_chat", {});
    lastChatSig = "";
    render(res.snapshot);
    showToast("已清空当前空间对话");
  } catch (e) { showToast(e.message); }
}

async function submitVerdict(verdict) {
  const notes = cmdInput.value.trim();
  if (verdict === "REJECT" && !notes) { showToast("请先在输入框写一句退回原因"); return; }
  try {
    const res = await api("/api/verdict", { verdict, notes });
    cmdInput.value = "";
    render(res.snapshot);
    flyMiniPlane("xiu", verdict === "PASS" ? "agy" : "codex");
    showToast(verdict === "PASS" ? "本轮验收通过" : "已退回修改");
  } catch (e) { showToast(e.message); }
}

async function runSelfCheck() {
  try {
    showToast("正在运行提交前自检三条…");
    const res = await api("/api/self_check", {});
    render(res.snapshot);
    flyMiniPlane("codex", res.result.status === "PASS" ? "dsh" : "codex");
    showToast(`自检三条：${res.result.status}`);
  } catch (e) { showToast(e.message); }
}
async function runDshVerify() {
  try {
    const res = await api("/api/dsh_verify", {});
    render(res.snapshot);
    flyMiniPlane("dsh", res.result.overall_pass ? "agy" : "codex");
    showToast(res.result.overall_pass ? "DSH 客观门禁全部通过" : "存在未达标项");
  } catch (e) { showToast(e.message); }
}
async function openObjectionPrompt() {
  const summary = prompt("异议摘要："); if (!summary) return;
  const evidence = prompt("代码或实测依据：", "scripts/core/"); if (!evidence) return;
  try {
    const res = await api("/api/objection", { summary, evidence });
    render(res.snapshot); flyMiniPlane("codex", "xiu");
  } catch (e) { showToast(e.message); }
}
async function arbitrate(resolution) {
  try {
    const res = await api("/api/arbitrate", { resolution, note: "" });
    render(res.snapshot); flyMiniPlane("xiu", "codex");
  } catch (e) { showToast(e.message); }
}
async function launchGame() {
  try { await api("/api/launch_game", {}); showToast("已执行打开操作"); }
  catch (e) { showToast(e.message); }
}

// --- Desktop App Capabilities: Native Notifications, Shortcuts & OS Folder Picker ---
let _wasJobRunning = false;
let _lastNotifiedApprId = "";

function requestDesktopNotifPerm() {
  if ("Notification" in window && Notification.permission === "default") {
    try { Notification.requestPermission(); } catch (e) {}
  }
}

function notifyDesktop(title, body) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const n = new Notification(title, {
      body: String(body || "").slice(0, 140),
      icon: "/icon-256.png",
      silent: false
    });
    n.onclick = () => { window.focus(); n.close(); };
  } catch (e) {}
}

function updateDesktopTitleAndNotify(job) {
  const running = Boolean(job?.running);
  const appr = job?.pending_approval;
  if (running) {
    const ag = (job.agent || "AI").toUpperCase();
    document.title = `● ${ag} (${job.elapsed_seconds || 0}s) — Super Workbench`;
  } else if (appr && appr.id) {
    document.title = t("✦ 待批准执行 — Super Workbench", "✦ Approval Needed — Super Workbench");
    if (_lastNotifiedApprId !== appr.id) {
      _lastNotifiedApprId = appr.id;
      notifyDesktop(
        t("方案已就绪 · 等待批准执行", "Plan Ready · Approval Needed"),
        t("点击切回工作台确认方案并交棒给执行方", "Click to return to Super Workbench and approve handoff")
      );
    }
  } else if (_wasJobRunning && !running) {
    const ok = (job?.exit_code ?? 0) === 0;
    if (document.hidden) {
      document.title = `${ok ? "✓" : "⚠"} ${t("任务已完成 — Super Workbench", "Task Finished — Super Workbench")}`;
    } else {
      document.title = "Super Workbench";
    }
    notifyDesktop(
      ok ? t("任务执行完成", "Task Completed") : t("任务中止或异常", "Task Stopped or Failed"),
      job?.title || t("点击切回 Super Workbench 查看结果", "Click to view results in Super Workbench")
    );
  } else if (!document.hidden) {
    document.title = "Super Workbench";
  }
  _wasJobRunning = running;
}

window.addEventListener("focus", () => {
  const job = latestSnap?.live_job;
  if (!job?.running && !job?.pending_approval) {
    document.title = "Super Workbench";
  }
});

// Global Desktop Keyboard Shortcuts (Ctrl+B, Ctrl+J, Ctrl+`, Ctrl+,, Alt+N, Esc)
window.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    closeStudioModal();
    closeWsModal();
    closeDelModal();
    closeGuideModal();
    toggleModelPopover(false);
    togglePlusMenu(false);
    toggleSlashMenu(false);
    return;
  }
  const mod = e.ctrlKey || e.metaKey;
  if (mod && (e.key === "b" || e.key === "B")) {
    e.preventDefault();
    toggleSidebar();
    return;
  }
  if (mod && (e.key === "j" || e.key === "J" || e.key === "`")) {
    e.preventDefault();
    toggleInspector();
    return;
  }
  if (mod && e.key === ",") {
    e.preventDefault();
    const sm = document.getElementById("studioModal");
    if (sm?.classList.contains("show")) closeStudioModal();
    else openSettings("general");
    return;
  }
  if ((e.altKey && (e.key === "n" || e.key === "N")) || (mod && e.shiftKey && (e.key === "n" || e.key === "N"))) {
    e.preventDefault();
    createNewThread();
  }
});

async function pickNativeFolder(target) {
  const isWs = target === "ws";
  const btn = document.getElementById(isWs ? "btnPickWsFolder" : "btnPickSkillFolder");
  const input = document.getElementById(isWs ? "newWsPath" : "importSkillPath");
  if (!input) return;
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/pick_folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: isWs ? t("选择工作空间目录", "Select Workspace Directory") : t("选择本地 Skill 文件夹", "Select Local Skill Folder"),
        initial_dir: input.value.trim() || ""
      })
    });
    const res = await resp.json();
    if (res.ok && res.path) {
      input.value = res.path;
      if (isWs) {
        const nameEl = document.getElementById("newWsName");
        if (nameEl && !nameEl.value.trim()) {
          const parts = res.path.replace(/[\\/]+$/, "").split(/[\\/]/);
          nameEl.value = parts[parts.length - 1] || "";
        }
      }
    }
  } catch (e) {
    showToast(e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// --- Ultra-Smooth 180ms In-Place Streaming Patch (Zero DOM Thrashing) ---
let lastLiveReplyRendered = "";
function patchLiveStream(job) {
  if (!latestSnap) return;
  latestSnap.live_job = job;
  updateDesktopTitleAndNotify(job);

  const pill = document.getElementById("statusPill");
  if (pill && job.running) {
    pill.className = "status-pill running";
    pill.innerHTML = `<i class="pulse-dot"></i><span>${escapeHtml((job.agent || "").toUpperCase())} · ${job.elapsed_seconds}s</span>`;
  }

  // Console Box (strictly respects user scroll-up)
  const cBox = document.getElementById("consoleBox");
  if (cBox && (job.logs || []).length) {
    const nextLog = job.logs.join("\n");
    if (cBox.textContent !== nextLog) {
      const cAtBottom = (cBox.scrollHeight - cBox.scrollTop - cBox.clientHeight) < 36;
      const cPrev = cBox.scrollTop;
      cBox.textContent = nextLog;
      cBox.scrollTop = cAtBottom ? cBox.scrollHeight : cPrev;
    }
  }

  const card = document.getElementById("liveAgentCard");
  const activeTid = latestSnap.active_thread?.id || "";
  if (!card || (job.thread_id && job.thread_id !== activeTid) || card.dataset.agent !== (job.agent || "agy")) {
    renderChat(latestSnap.messages, job);
    lastLiveReplyRendered = job.live_reply || "";
    return;
  }

  const scrollEl = document.getElementById("chatScroll");
  const wasAtBottom = (scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight) < 48;
  const prevTop = scrollEl.scrollTop;

  const elTime = document.getElementById("liveElapsed");
  if (elTime) elTime.textContent = `${job.elapsed_seconds}s`;
  const elStep = document.getElementById("liveStepDesc");
  if (elStep) elStep.textContent = job.current_step_desc || "正在思考与执行…";
  const elLogs = document.getElementById("liveTraceLogs");
  if (elLogs) elLogs.textContent = (job.logs || []).slice(-18).join("\n") || "正在初始化进程…";

  const reply = job.live_reply || "";
  const elBody = document.getElementById("liveReplyBody");
  if (elBody && reply !== lastLiveReplyRendered) {
    lastLiveReplyRendered = reply;
    if (reply) {
      elBody.style.display = "block";
      elBody.innerHTML = renderMarkdown(reply, true);
    } else {
      elBody.style.display = "none";
      elBody.innerHTML = "";
    }
  }
  scrollEl.scrollTop = wasAtBottom ? scrollEl.scrollHeight : prevTop;
}

async function pollLoop() {
  if (mutationInFlight === 0 && latestSnap?.live_job?.running) {
    try {
      const live = await api("/api/live");
      const job = live.live_job || {};
      const verChanged = Number(live.version || 0) > lastAppliedVersion;
      if (!job.running || verChanged) {
        lastLiveReplyRendered = "";
        await refreshAll();
      } else {
        patchLiveStream(job);
      }
    } catch (e) {}
    setTimeout(pollLoop, 180);
    return;
  }
  lastLiveReplyRendered = "";
  await refreshAll();
  setTimeout(pollLoop, latestSnap?.live_job?.running ? 180 : 1600);
}
applyLang(currentLang);
pollLoop();
