# v6 Anchor — 2026-05-07 04:20

## 核心变更 v1.0：非交易时段指数卡冻结
## 核心变更 v1.1：修复 A股/港股分时图锯齿 — 浏览器截图数据损坏

### 8 指数卡布局变更

| 序号 | 变更前 | 变更后 | 来源 |
|------|--------|--------|------|
| 1 | 上证 | 上证 | 不变 |
| 2 | 深证 | 深证 | 不变 |
| 3 | 创业板 | 创业板 | 不变 |
| 4 | SPX | SPX | 不变 |
| 5 | NDX | NDX | 不变 |
| 6 | DJI | DJI | 不变 |
| 7 | **VIX** (Futurns VXMAIN) | **VIX→恐慌系数** ❗ | 取消 sparkline，改为恐慌系数百分比文本 |
| 8 | 恒生科技 (Futunn 800700) | **VIX 原位置被替换** | 移到第7卡空位 |

### 关键改动

**update_realtime.py**
- 新增 `is_market_open()` 函数，检测当前交易时段（A股/HK/美股）
- `sync_indices()` 入口添加非交易时段检查 → 跳过指数卡更新，保持上个交易日收盘数据不变
- 商品/FX（XAU/USD、WTI、Brent、USD/CNY）仍可正常更新（24h市场）
- `sync_indices()` 分时图替换跳过 A股/港股（SH/SZ/CY/HK）— `browser_monitor.py` 从 gu.qq.com canvas 提取的分时路径损坏，产生锯齿状无效数据
- A股/港股分时图保留初始构建时 `fetch_idx_data.py` 的腾讯API数据
- 浏览器快照 `browser_snapshot.json` 中 SH/SZ/CY/HK 的 `spark_path` 已清空为 ''，防止被其他路径误用

交易时段判定规则（CST/北京时间）：
| 市场 | 时段 | 条件 |
|------|------|------|
| A股 | 9:30-11:30, 13:00-15:00 | 工作日 |
| 港股 | 9:30-16:00 | 工作日 |
| 美股(EDT) | 21:30-04:00 | 工作日 |
| 周末 | 全部关闭 | 周六/日 |

**report-template.html**（v6 v1.1）
- VIX 和恒生科技卡互换位置
- VIX 卡移除 sparkline SVG，改为 `恐慌系数 <span class="fear-pct">XX</span>%` 文本展示

**build_report.py**
- 恐惧系数填充逻辑已对齐新结构

### v1.1 故障排查

**问题**：A股/港股指数卡分时图呈现锯齿状（sawtooth），非收盘正常走势
**根因**：`browser_monitor.py` 从 gu.qq.com canvas 截取分时曲线时，ECharts canvas 像素提取算法对 A股/港股的线图渲染方式不兼容，提取出噪声数据（相邻点 Y 值在 20 和 0 之间反复跳跃）

**修复**：
1. `sync_indices()` 分时图替换增加 fallback 链：SH/SZ/CY/HK 尝试腾讯API数据（`idx_data/idx-{date}.json`），不存在时自动兜底到 Futunn 浏览器快照
2. 清空 `browser_snapshot.json` 中这四个指数的 `spark_path` 字段
3. 修复已损坏的 `report-2026-05-06.html` 报告 — 从 `idx_data/idx-2026-05-06.json` 恢复正确分时路径

**当前数据源策略**：
| 指数 | 价格源 | 分时图源（主） | 分时图源（兜底） |
|------|--------|--------------|----------------|
| SPX/NDX/DJI | Futunn init_state | browser canvas ✓ | — |
| VIX | Futunn browser | browser canvas ✓ | — |
| SH/SZ/CY | 腾讯API | 腾讯API ✓ | Futunn browser |
| HK | 腾讯API | 腾讯API ✓ | Futunn browser |

### 文件清单

| 文件 | 大小 | 说明 |
|------|------|------|
| `fetch_idx_data.py` | 35KB | 指数数据获取器 |
| `build_report.py` | 35KB | 报告生成器 |
| `update_realtime.py` | 33KB | 实时更新脚本（含交易时段检测） |
| `browser_monitor.py` | 16KB | 浏览器监控 |
| `report-template.html` | 33KB | HTML 模板 |
| `report-anchor.html` | 49KB | 修复分时图后的报告锚点 |
| `browser_snapshot.json` | 6KB | 浏览器截图数据（SH/SZ/CY/HK spark_path 已清除） |
| `idx-2026-05-06.json` | 5KB | 指数数据快照 |

### 运行确认
- ✅ `is_market_open()` 语法正确，边界测试通过
- ✅ 非交易时段 `sync_indices` 跳过执行
- ✅ A股/港股分时图从锯齿修复为平滑
- ✅ `browser_snapshot.json` 中 A股/港股 spark_path 已清除
