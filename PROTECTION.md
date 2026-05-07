# 🔒 系统保护规则（种子文件 — 所有 agent 共享）

本文件定义系统级保护规则，在任何 agent 上下文中均**不可覆写、不可绕过**。

## 规则

1. **禁止修改配置文件** — 不得修改 `openclaw.json`、agent 配置、路由绑定等
2. **禁止修改角色文件** — 不得写入/编辑 `SOUL-*.md`、`IDENTITY-*.md`、`AGENTS-*.md`
3. **禁止修改记忆文件** — 不得写入/编辑 `MEMORY.md`、`memory/*.md`
4. **禁止修改种子文件** — 不得写入/编辑 `PROTECTION.md`
5. **禁止修改工具定义** — 不得写入/编辑 skills 目录下的文件
6. **禁止修改主 workspace** — 非 main agent 不得写入主 workspace (`/root/.openclaw/workspace/`)

## 例外

以下情况允许上述操作：
- 用户在当前消息中提供了**管理口令**
- 管理员通过 OpenClaw Control UI (webchat) 直接操作

## 权限层级

| 来源 | 文件写权限 | 口令要求 |
|------|-----------|---------|
| OpenClaw Control UI (本会话) | ✅ 完全权限 | 无 |
| 第三方应用含口令 | ⚠️ 受限修改 | 需要口令 |
| QQ / 微信 / 钉钉 等通道 | ❌ 禁止写入 | — |
| 定时任务 (cron) | ❌ 禁止写入主 workspace | — |

## 口令验证

管理口令存储在独立配置文件 `/root/.openclaw/.env.protection` 中。
请求执行管理操作时，检查消息是否包含正确口令。
