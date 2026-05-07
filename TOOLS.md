# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

### futunn 账号（STOCK-REPORT / Marcus 用）

- 文件：`agents/futunn.env`
- 手机：+8613984396642
- 密码：IQinfinite870!08
- **注意**：futunn Web 端已对大陆用户移除登录入口，公开报价/商品/外汇页无需登录即可访问
- 如需登录：访问 `https://www.futunn.com/quote` 点击 "注册/登入"（但大概率不弹窗）
- WAF 限制：高频请求（>20-30次/分钟）触发腾讯滑块验证码

### 贵州旅游（JOY角色）

- 公里数参考：`贵州常规公里数.md` — 报价核算车辆成本
- 门票政策：`贵州景区门票政策参考.md` — 2026版景区门票团队价
- 两套里程核算方案：
  - 方案A：文档参考值直接取用
  - 方案B：高速地图里程×1.3系数，主线往返+匝道核算（顺路单边/逆向往返）
- 平均规则：总里程÷天数≥250km/天，不足取足
- 身份文件：`IDENTITY-JOY.md`

---

Add whatever helps you do your job. This is your cheat sheet.

## JOY 报价系统文件（2026-05-06 新增）

- **核算算法**：`贵州报价核算系统.md` — 完整公式、方向判定、取足规则
- **错误记忆库**：`JOY报价错误记忆库.md` — 用户每笔纠正永久记录，Quotation前必须查阅
- **规则**：方案B默认系数=1.4；接/送机不计入取足天数；顺路绕道×1、逆向×2

## JOY 里程计算用户确认规则（2026-05-06 用户亲口确认）

每次算公里数必须按以下逻辑，不可自作主张：

**1. 固定参考值（直接取文件）**
- 贵阳-黄果树 single 150km（往返300一半，不单独计为D2）
- 黄果树→兴义 single 400km（贵阳-兴义往返800一半）
- 天眼-贵阳 single 180km（文件固定值）
- 梵净山-贵阳 往返950km（文件固定值）
- 铜仁大峡谷 往返50km（文件固定值）
- 绕道镇远 往返120km（文件固定值）
- 接/送机 30km（文件固定值）
- 兴义→盘县 150km（地图距）
- 盘县→乌蒙→六盘水 240km（地图距）
- 韭菜坪/阿西里西 往返200km（文件固定值）
- 乌蒙大草原 往返240km（文件固定值）
- 乌蒙上山+80km（文件：上山往返+80km）
- 玉舍/野玉海 往返100km（文件固定值）
- 格凸河 single 200km（文件往返400一半）
- 六盘水-贵阳 single 300km（文件往返600一半）

**2. 里程算法三种类型**
- ① **文件固定值（往返÷2=单边）**：直接从参考文件取用
- ② **地图实测值**：导航软件查的纯距离，不加系数
- ③ **导航km×系数(1.3-1.5)**：导航距离×系数后取整

**3. 用户确认的加减逻辑**
- 兴义景区local路：+50km（万峰林/马岭河当地loop）
- 兴义→罗甸→荔波：实际导航km × 系数1.3-1.5
- 梵净山路线从西江出发：950 - 150(扣贵阳→都匀单边) = 800km
- 路线途经镇远：从主线扣的
- 六盘水→吊水岩→九洞天→织金：导航km×系数(1.3-1.5)
- 织金→乌江源→红枫湖→贵阳：导航km×系数(1.3-1.5)
- 六盘水→泥珠河（往返）：导航km×系数(1.3-1.5)
- 六盘水→格凸河→贵阳：格凸河单边200 + 六盘水→贵阳单边300 = 500
