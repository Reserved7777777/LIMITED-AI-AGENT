# v5 Anchor — 2026-05-06 23:41

## 核心变更：Sparkline 来源切换（API > 浏览器截图）

### 8 指数卡数据流

| 指数 | 实时价格 | 分时曲线 | 点数 | 浏览器依赖 |
|------|---------|---------|------|-----------|
| SPX | Futunn `__INITIAL_STATE__` | `minuteChartsData` | 116 | ❌ |
| NDX | Futunn `__INITIAL_STATE__` | `minuteChartsData` | 116 | ❌ |
| DJI | Futunn `__INITIAL_STATE__` | `minuteChartsData` | 116 | ❌ |
| VIX | Playwright (VXMAIN futures) | Canvas 截图 | 73 | ✅ 唯一 |
| 上证 | 腾讯 minichart | API 分钟数据 | 242 | ❌ |
| 深证 | 腾讯 minichart | API 分钟数据 | 242 | ❌ |
| 创业板 | 腾讯 minichart | API 分钟数据 | 242 | ❌ |
| 恒科 | 腾讯 hkHSTECH | API 分钟数据 | 242 | ❌ |

### 关键改动

**fetch_idx_data.py**
- 新增 `_extract_init_state()` — 括号匹配+字符串处理提取 Futunn `__INITIAL_STATE__`
- 新增 `fetch_us_indices_futunn_init()` — 提取 SPX/NDX/DJI 的 `minuteChartsData` + `stock_info` 价格
- `fetch_all_indices()` 重写 — futunn_init 优先，API 兜底，browser 仅 VIX
- `assemble_output()` 优先级变更 — minute_prices > spark_path (canvas)

**browser_monitor.py**
- `INDEX_CARDS` 从 8 缩到 1（仅 VIX）
- Playwright 调用从 48x/天 → 6x/天

**update_realtime.py**
- `sync_indices()` 的 up/down 类替换改为卡片边界内替换（修复全局覆盖 bug）

### 文件清单

| 文件 | 大小 | 说明 |
|------|------|------|
| `fetch_idx_data.py` | 34KB | 指数数据获取器（API 主力） |
| `build_report.py` | 30KB | 报告生成器 |
| `update_realtime.py` | 33KB | 30分钟实时更新脚本 |
| `browser_monitor.py` | 10KB | 仅 VIX 的 Playwright 截图 |
| `report-template.html` | 34KB | HTML 模板 |
| `report-anchor.html` | 54KB | 2026-05-06 最终版报告 |
| `report-data-anchor.json` | 22KB | 全量数据快照（含 30 只股票） |
| `browser_snapshot.json` | 1KB | VIX 浏览器截图数据 |

### 运行确认
- ✅ 8/8 指数价格正确
- ✅ 8/8 SVG 分时曲线（116-242 点，无浏览器误差）
- ✅ 30 只个股三级动量表完整
- ✅ 涨跌色正确（红涨绿跌）
- ✅ 13 项 HTML 标记完整
- ✅ 商品/分析/风险/事件正常
