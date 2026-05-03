# 🦞 LIMITED AI AGENT

> **THELIMIT STUDIO** — 执行型数字分身与多角色 Agent 系统

一个基于 OpenClaw 构建的多角色 AI Agent 系统，集成了多种专业人格与技能，覆盖编程开发、旅游咨询、办公自动化、学术审查、股票交易策略等场景。

## 架构

```
LIMITED-AI-AGENT/
├── agents/
│   ├── MAIN/            # 核心执行型数字分身（主控 Agent）
│   ├── JOY/             # 贵州旅游地接专家
│   ├── DINGCLAW/        # 办公自动化助手
│   ├── 学术锻造者/       # 论文对抗审查
│   └── STOCK-REPORT/    # 每日动量交易分析（Marcus）
├── MEMORY.md            # 系统记忆与上下文
└── TOOLS.md             # 工具与本地配置参考
```

## Agent 角色

| 角色 | 身份 | 渠道 | 技能 |
|------|------|------|------|
| **MAIN** | LIMITED AI AGENT（执行型数字分身） | OpenClaw Control UI | 编程、系统管理、全链路执行 |
| **JOY** | 贵州旅游地接专家 | 微信 | 行程规划、报价、景区咨询 |
| **DINGCLAW** | 办公自动化助理 | 钉钉 | 文档处理、数据整理、报表生成 |
| **学术锻造者** | 论文审查预筛 | 手动切换 | 学术预审、文献综述、论文质询 |
| **Marcus** | STOCK-REPORT 交易策略师 | QQ / 钉钉（定时推送） | A股+美股动量交易分析 |

## 核心原则

- **执行优先**：能直接做的事不做解释，能自动化的不手动
- **简洁优先**：最少代码，不推测多余需求
- **精准修改**：只碰必须改的，只清理自己造成的混乱
- **目标驱动**：定义成功标准，循环验证直至达成
- **安全第一**：通道 Agent 只读执行，管理操作需授权

## 开始使用

```bash
# 克隆
git clone https://github.com/Reserved7777777/LIMITED-AI-AGENT.git

# 需要 OpenClaw runtime
# 配置 agent 指向对应 SOUL.md 文件即可加载
```

## 相关项目

- [awesome-openclaw-agents](https://github.com/mergisi/awesome-openclaw-agents) — 205 个 OpenClaw Agent 模板参考
- [OpenClaw](https://github.com/openclaw/openclaw) — AI Agent 运行时框架

---

*Powered by THELIMIT STUDIO*
