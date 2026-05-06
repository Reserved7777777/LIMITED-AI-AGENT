# v4 Anchor — 2026-05-06 20:55

## 状态
HTML 报告结构已固化，风险提示区域加固完成，整站架构稳定。

## 包含文件

| 文件 | 说明 | 大小 |
|------|------|------|
| `report-template.html` | 最新 HTML 模板 | 34KB |
| `build_report.py` | 构建脚本（含 self-check + marker 边界风险替换） | 28KB |
| `browser_monitor.py` | 浏览器监测 + 73pt 稳定 sparkline 提取 | 11KB |
| `fetch_idx_data.py` | 指数数据获取（含归档模式 VIX spark 合并） | 30KB |
| `daily-momentum-report.md` | Marcus Agent 完整指令 | 36KB |
| `report-anchor.html` | 2026-05-06 最终版报告（54,568 bytes） | 55KB |
| `report-data-anchor.json` | 报告当日数据（分析/风险/事件/商品全量） | 18KB |
| `idx-anchor.json` | 指数数据快照 | ～KB |
| `browser_snapshot.json` | 浏览器监测快照（8 指数 73pt spark） | 8KB |
| `idx-2026-05-06.json` | 当日存档 | 7KB |
| `SNAPSHOT.md` | 本文件 | |

## 架构要点

### HTML 生成流程
```
fetch_idx_data.py → idx JSON
browser_monitor.py → browser_snapshot.json (spark_path)
build_report.py → HTML（模板 + idx数据 + 报告数据）
```

### 关键修复（本版已固化）
1. **风险提示区域** — 使用 `<!-- RISK -->`→`<!-- EVENTS -->` marker 边界替换，不再依赖 `_replace_tag`/`_find_closing_tag` 深度计数
2. **13 项自检** — 写入前验证所有 section marker 完整性，缺失自动告警
3. **Sparkline 73 点** — 单像素最大饱和度 + 7 窗口中值滤波，稳定锯齿线
4. **VIX 使用 futures 价格** — 去掉 .VIX spot 覆盖逻辑，显示 VXMAIN 期货
5. **归档模式合并 snapshot** — 非交易时段自动合并最新 browser_snapshot spark_path

### 固定规则
- 分析 8 段顺序：铜→白银→黄金→原油→金油比→金银铜比→DXY/CNH→SOX（不可变）
- 商品卡：4 张（XAU/USD、WTI、布伦特、USD/CNY）
- 风险：5 条 FIFO 队列，链接需 curl 验证 200
- ETF 名称：类型+ETF（不带基金公司）

## 报告 URL
`http://1.14.93.56/static/report-YYYY-MM-DD.html`

## 下一步（可选）
- 增加点密度到 120-150（需更好的降噪算法，用户反馈 73 点更清晰）
- 接入东方财富 push2 API 替代 Finnhub 解决 A 股 ETF 数据为零问题
- 改用正规 HTML parser（html.parser/lxml）替代字符串正则替换
