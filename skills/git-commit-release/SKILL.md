---
name: git-commit-release
description: 自动整理清晰规范的 Git Commit 信息、中英文 Changelog 与 GitHub Release 发布说明
---

# 规范化 Git 提交与开源发布说明规范

输出代码提交信息或版本发布日志时，遵循以下格式：

1. **Conventional Commits 标题**：
   - 使用 `feat:` / `fix:` / `refactor:` / `perf:` / `docs:` / `ui:` 前缀，标题不超过 72 字符；
2. **结构化变更摘要**：
   - 分条列出：**新增功能（Added）**、**问题修复（Fixed）**、**性能与体验优化（Improved）**；
   - 每条说明“改了什么 + 对用户有什么实际好处”，避免堆砌琐碎变量名；
3. **开源安全自查提醒**：
   - 提交前核对是否误包含 `.workbench/`、API Key、本机绝对路径或临时日志文件。
