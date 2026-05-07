# 锚点 v3 — 2026-05-06 13:56

## 文件清单

| 文件 | 大小 | 说明 |
|------|------|------|
| `browser_monitor.py` | 10,182 B | Playwright + futunn canvas 像素提取，40点 SVG 分时图 |
| `fetch_idx_data.py` | 28,116 B | 指数数据聚合：auto-run browser_monitor → snapshot → API enrichment → sparklines |
| `build_report.py` | 28,042 B | HTML 报告构建：模板替换，9 个模块自动更新 |
| `fetch_market_data.py` | 18,971 B | 个股/商品数据获取：东方财富 push2 + Swissquote + oilprice |
| `report-template.html` | 34,361 B | HTML 报告模板，含 8 指数卡 + 3 级动量表 + 商品 + 分析 + 风险 + 日历 |
| `daily-momentum-report.md` | 34,486 B | STOCK-REPORT Agent 指令/工作流程/铁律/错误记录 |

## 架构状态

```
futunn.com (canvas)
    ↓ Playwright evaluate (JS 内像素处理，只传回线点)
browser_monitor.py
    ↓ 40点 SVG path → idx_data/browser_snapshot.json
fetch_idx_data.py (auto-runs browser_monitor if stale)
    ↓ + Sina API (US OHLC) + 腾讯 API (A/H minute prices)
    → /tmp/report-idx-YYYY-MM-DD.json
fetch_market_data.py
    ↓ 东方财富 push2 + Swissquote + oilprice
    → /tmp/report-data-YYYY-MM-DD.json
build_report.py
    ↓ 合并 idx + market data → 模板替换
    → /var/www/openclaw/report-YYYY-MM-DD.html
```

## 关键特性

- **8 张指数卡**：SPX/NDX/DJI/VIX/SH/SZ/CY/HK，分时图来自 futunn canvas 像素提取
- **30 只个股**：三级动量（高位 10 / 中位 10 / 低位 10），东方财富 push2 API
- **4 种商品**：黄金(WTI/Brent/USDCNH)，Swissquote + oilprice 直接报价
- **自动刷新**：fetch_idx_data.monitor_futunn_pages() 自动检测 snapshot 过期并运行 browser_monitor
- **数据同频**：指数卡与报告其他数据同一批次生成

## Cron 触发

- A 股报告: 08:30 → `build_report.py` → 内部串联全链路
- 美股报告: 22:30 → 同上

## 部署位置

- 报告 HTML: `/var/www/openclaw/report-YYYY-MM-DD.html`
- HTTP 访问: `http://limitedaiagent.icu/static/report-YYYY-MM-DD.html`
- HTTP IP直连: `http://1.14.93.56/static/report-YYYY-MM-DD.html`
