# v4 Anchors — 2026-05-06

## Core Innovation: Weighted Centroid Sparkline Extraction

### Problem
Previous method (per-column max-saturation pixel) caused stair-stepping on diagonal chart lines. Edge pixels (2-7 per sparkline) were noisy due to axis label interference.

### Solution: Weighted Centroid
Instead of picking the single brightest pixel per column, compute `sum(y * weight) / sum(weight)` across ALL chart-line pixels in that column (weight = saturation × brightness). This gives sub-pixel y-position precision and eliminates stair-stepping naturally.

### Results
- **Direction changes**: 55-74% (sawtooth) vs previous 42-48%
- **Edge quality**: 5% trim removes axis noise, remaining 67 points clean
- **viewBox**: Properly maps `0 -4 80 32` (full range used)
- **All 8 indices**: same approach (SPX, NDX, DJI, VIX, SH, SZ, CY, HK)

### File Inventory
```
anchors/v4/
├── browser_monitor.py    — Playwright chrome CDP monitor + PIL centroid extractor
├── browser_snapshot.json — Latest index data (8 indices, 67pt sparklines)
├── build_report.py       — HTML report builder (4 commodity cards, 30 stocks, 8 analysis sections)
├── daily-momentum-report.md — Marcus agent instructions (v4 rules)
├── idx-2026-05-06.json   — Raw index data from fetch_idx_data.py
├── report-anchor.html    — Generated report (53KB)
├── report-data-anchor.json — Enriched report data (analysis, risks, events, commodities)
└── report-template.html  — HTML template (SVG sparklines, responsive, dark theme)
```

## System State

### Index Card Configs
| Key | Symbol | Market | futunn URL |
|-----|--------|--------|------------|
| SPX | .SPX-US | US | /index/.SPX-US |
| NDX | .IXIC-US | US | /index/.IXIC-US |
| DJI | .DJI-US | US | /index/.DJI-US |
| VIX | VXMAIN-US | US | /futures/VXMAIN-US |
| SH | 000001-SH | A-Share | /index/000001-SH |
| SZ | 399001-SZ | A-Share | /index/399001-SZ |
| CY | 399006-SZ | A-Share | /index/399006-SZ |
| HK | 800700-HK | HK | /index/800700-HK |

### Report Structure
- **Header**: 8 index cards (SVG spark, price, change%) — 4-up grid
- **Cfx Grid**: XAU/USD, WTI原油, 布伦特, USD/CNY — 4 cards
- **Analysis**: 8 sections in fixed order:
  1. 铜 → 2. 白银 → 3. 黄金 → 4. 原油 → 5. 金油比 → 6. 金银铜比 → 7. DXY/CNH → 8. SOX
- **Stocks**: 30 (Tier 1/2/3, 10 each) — 沪深主板优先
- **Risks**: 5 items (FIFO queue, new in → oldest out)
- **Events**: 8 items (from cls.cn/telegraph)

### Risk Link Rules
1. All cls.cn/detail/XXXXX links MUST be verified via `curl` returning HTTP 200
2. Fallback: `https://www.cls.cn/telegraph` (always available)
3. No dead/404 links allowed
4. 5-item FIFO queue: new risk in → oldest out

### Key File Paths (production)
```
/root/.openclaw/workspace/
├── build_report.py
├── browser_monitor.py
├── report-template.html
├── agents/daily-momentum-report.md
├── idx_data/
│   ├── browser_snapshot.json
│   └── idx-YYYY-MM-DD.json
/var/www/openclaw/
├── report-YYYY-MM-DD.html
/tmp/
└── report-data-YYYY-MM-DD.json
```

### Cron Schedule
- A股: Mon-Fri 08:30 CST → QQ (579ebc0a) + 钉钉 (b0cdbf9e)
- 美股: Mon-Fri 22:30 CST → QQ (9e12aaec) + 钉钉 (f63e0eee)
- Timeout: 600s, model: deepseek-reasoner

## SVG Sparkline Spec
- **viewBox**: `0 -4 80 32` (x:0-80, y:-4 to 28)
- **stroke-width**: 1.8
- **stroke-linecap**: "round"
- **Color**: `#FF4060` (up), `#00C853` (down)
- **Points**: ~67 per sparkline (after 5% edge trim from 73 target)
- **Filter**: 3-point weighted moving average (0.5/1.0/0.5)
- **Extraction**: Weighted centroid (sub-pixel), not single-pixel max

## Market Data Sources
- **Indices**: futunn browser (Playwright CDP)
- **Gold/XAU**: Swissquote API
- **Oil**: Oilprice.com HTML parse
- **USD/CNY**: Swissquote API
- **Silver/Copper/DXY**: Swissquote (copper/DXY limited availability)
- **SOX**: Sina finance API
- **Stock prices**: Finnhub (free tier, limited)
- **Risk sources**: cls.cn/telegraph keyword matching
