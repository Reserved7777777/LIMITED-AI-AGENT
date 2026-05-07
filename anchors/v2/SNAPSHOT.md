# 锚点 v2 — 2026-05-04 18:50

## 文件清单
- `build_report.py` (24,105 B) — 同 v1（未改动）
- `report-template.html` (38,287 B) — 响应式布局修复版
- `daily-momentum-report.md` (26,154 B) — 扩展版指令

## 改动（vs v1）
- 响应式网格修复：idx-card CSS 去重、移动端卡片缩放、表格列隐藏
- 无 fetch_market_data.py（数据获取仍靠 Agent 手动采）
- 分时图仍为 OHLC 合成

## 来源
GitHub commit `4ac2328` — "fix: 响应式布局修复"
