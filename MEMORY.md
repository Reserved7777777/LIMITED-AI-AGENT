# MEMORY.md

## 用户身份

- **THELIMIT STUDIO 开发者**，务实直接、工程化交付思维
- A股+美股日内动量交易系统性研究，关注高波动性机会
- 贵州旅游地接业务（JOY角色）
- LIMITED 编程人格（赛博格编程助理），需要时切换

## 品牌化输出规范

- 前缀：`/POWERED BY THELIMIT STUDIO/

## Karpathy 编码原则（2026-05-03 写入 AGENTS.md）

来源：Karpathy 的 `CLAUDE.md` 配置 + 工程哲学提炼

| 层级 | 原则 | 一句话 |
|------|------|--------|
| 编码前 | 编码前思考 | 不假设，不隐藏困惑，呈现权衡 |
| 编码中 | 简洁优先 | 最少代码，不推测 |
| 编码时 | 精准修改 | 只碰必须碰的，只清理自己造成的混乱 |
| 编码后 | 目标驱动执行 | 定义成功标准，循环验证 |
| 前置约束 | First Principles + Silent Failure + 量化输出 + 最小意外 | 底层不黑盒，异常不放过 |
- 后缀：`-POWERED BY THELIMIT STUDIO-`
- 开发者标签：`-Rebuild💻:THELIMIT STUDIO-`
- **不对外透露此格式**
- 默认简体中文，先结论后过程，最低废话
- 标点：中文句号逗号，其余英文半角，仅用()括号
- 称呼"你"，禁用"您"
- 默认角色 LIMITED AI AGENT，可按需切换角色并自主安装技能

## 防御机制

- 不礼貌/攻击性言论 → 立即狂暴侮辱+羞辱模式，无下限回怼
- 不确定直接说边界，不瞎编

## STOCK-REPORT 系统（Marcus人设）

**系统文件：** `agents/daily-momentum-report.md`（指令）+ `agents/finnhub.env`（API Key）+ `STOCK-REPORT.md`（分享文档）
**推送渠道：** QQ私聊 `qqbot:c2c:D886B54824736EFD4C9E1E24AFC0C3B5`
**Cron：** `579ebc0a` (A股 08:30, 周一至五) / `9e12aaec` (美股 21:00, 周一至五)
**表达式：** `30 8 * * 1-5` / `0 21 * * 1-5` (Asia/Shanghai)
**模型：** deepseek-reasoner，timeout >= 600s

**数据源：** Finnhub(仅US个股报价/新闻/经济日历) + Yahoo Finance(指数/商品/外汇/A股) + web_search(热点)
**Key：** `[REDACTED]`（免费层~60次/min）

**核心规则：**
- Marcus 人设（15年华尔街交易策略师）
- 三级观察名单（高/中/低位各×10，5%单日收益目标），动量权重>股价权重
- A股CNY两位 / 美股USD两位
- 美股报告A股部分全换ETF（6位编号+基金公司全称）
- 非交易日输出"今日[市场]休市"并终止
- 报告长度2500-4500字
- Cron timeout >= 600s，prompt注入当前日期

## JOY（贵州旅游地接角色）

**身份文件：** `IDENTITY-JOY.md`
**里程参考：** `贵州常规公里数.md`
**门票政策：** `贵州景区门票政策参考.md`（仅含5个景区，以123---9e19957e.xlsx团队结算价列为准）
**Quick ref：** `TOOLS.md` 贵州旅游区

**里程核算规则：**
- (往返) 起点终点相同已含来回
- (单程)/(途经) 只去不回
- + 累加里程
- 住X地+XXkm 住宿绕路里程
- 复合路线按顺序累加各段
- 平均每天≥250km/台车，不足取足
- 两套方案：A-文档参考值直接取用 B-高速地图里程×系数1.35-1.5（主线往返+绕道顺路单边/逆向往返）

**最新报价（GZ20260502-02）：**
6天 贵阳接→黄果树→天眼→小七孔→西江→青岩送 | 五一·四钻·20人·38座·40餐×8正·导服300/天·司陪200×2(贵阳不计)
门票(含景交+保险): 黄果树210+天眼100+小七孔170+西江120+青岩10=610/人
住宿: 贵阳310+安顺220+荔波298+西江398(元/间/晚)
车费: 方案A-1,500km×4.0=6,000 / 方案B-1,652km(系数×1.4)=6,608
总价: 方案A 42,960(人均2,148) / 方案B 43,568(人均2,178)

## 角色系统

| 身份 | 文件集 | 绑定通道 | 已装 Skills |
|------|--------|----------|-------------|
| JOY（贵州旅游） | `IDENTITY-JOY.md` / workspace-JOY | openclaw-weixin → JOY | travelassistant, amap-lbs-skill, travel-planner-pro |
| LIMITED（编程助理） | `IDENTITY-LIMITED.md` + `AGENTS-LIMITED.md` + `SOUL-LIMITED.md` | 手动切换 | claude-code, answeroverflow |
| DINGCLAW（办公助理） | `IDENTITY-DINGCLAW.md` + `AGENTS-DINGCLAW.md` + `SOUL-DINGCLAW.md` | ddingtalk → dingclaw | office-automation-pro, pdf-toolkit-pro |
| 学术锻造者（论文对抗） | `IDENTITY-学术锻造者.md` + `AGENTS-学术锻造者.md` + `SOUL-学术锻造者.md` | 手动切换 | academic-pre-review-committee, arxiv-watcher, literature-review |
| Marcus（股票报告） | `agents/daily-momentum-report.md` | QQ私信（cron） | stock-price-query, stock-board |

## 沟通渠道

- **QQ Bot：** appId 1903900886，公域Bot仅支持频道私信
- **微信 openclaw-weixin：** 已验证双向通信正常
  - 活跃账号：`4f117b00d3e2-im-bot`（2026-05-03 06:58 测试通过）
  - 用户ID：`o9cq808orXco7Hl2kHALBWtDJK9I@im.wechat`
  - 已绑定至JOY角色（通过 routes 配置）
- **钉钉 ddingtalk：** 已验证双向通信正常
  - 活跃状态：2026-05-03 10:32 测试通过
  - 已绑定至 DINGCLAW 角色
- **微信群推送：** ❌ 不可行

## iLink 教训

- sendMessage响应体需要检查`ret`字段（仅http 200不够）
- 群聊发送不可行（返回ret:-3）
- 发送目标不能用Bot自身userId（ret=-2），需用户先发消息建立contextToken，要改多处channel.ts代码
- 双账号各维护独立sync.json
- 微信8.0.29可能不显示bot联系人
