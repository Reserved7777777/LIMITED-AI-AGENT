
### 风险提示区域缺失（2026-05-06 19:27）

**现象：** HTML 报告风险提示区域不显示，`⚠️ 关键风险提示` sec-label 在生成文件中丢失，`<!-- ===== RISK ===== -->` 注释消失

**根因：** 未完全确认。排查发现：
- 模板文件 `report-template.html` 中风险区域结构完整
- `_replace_tag()` 函数单独测试正常，能正确保留 sec-label
- 完整 pipeline 模拟（Python 内联执行）正常
- 但通过 `build_report.py` 命令行执行后，生成文件确缺失风险 sec-label
- 复现不稳定 — 有几次发现存在，有几次缺失

**可能原因：**
1. `_replace_tag` 在部分场景下 `_find_closing_tag` 嵌套深度计算偏差（`<div>` 打开/闭合不匹配）
2. `analysis` 替换步骤和风险区域边界有重叠
3. 生成过程中 HTML 被多次处理，某次替换吞掉了边界内容

**修复（20:13）v2 — 永久加固方案：**
1. **自修复 fallback**：`_replace_tag` 替换完 `risk-list` 后立即检查 sec-label 是否完整。若丢失 → 用 `<!-- ===== RISK ===== -->` 到 `<!-- ===== EVENTS ===== -->` 为边界重建完整风险区块
2. **HTML 自检清单**：写入输出前扫描 13 个关键标记，缺任意一个都打印警告到 stderr
3. 不再依赖 `_replace_tag` 单次调用的正确性，双层兜底保障

**当前状态：** 每次构建都会通过 13 项标记完整性检查，风险区域有自修复能力。

**教训：**
- `_replace_tag` / `_find_closing_tag` 对嵌套 `<div>` 结构的边界处理不够稳健，尤其是替换内容本身也含嵌套 `<div>` 时
- 生成完成后必须做自检：检查关键标签完整性
- 考虑改用正规 HTML parser（`html.parser` 或 `lxml`）替代字符串正则替换

**提交：** `c25c8e4` — fix: robust risk section + HTML self-check validation

### 风险链接验证规则强化（2026-05-06）

**背景：** 风险链接可能存在 HTTP 404，导致用户点击后跳转失败

**规则（已写入 agent 指令 5f-ii）：**
- 所有 `cls.cn/detail/{id}` 链接必须 `curl -s -o /dev/null -w "%{http_code}" -A "Mozilla/5.0"` 验证返回 200
- 非 200 → 兜底到 `https://www.cls.cn/telegraph`
- 已验证链接：
  - `cls.cn/detail/2362652` → ✅ 200（伊朗-阿联酋冲突）
  - `cls.cn/detail/2363755` → ✅ 200（存储芯片）
  - `cls.cn/telegraph` → ✅ 200（通用兜底）

### 分析顺序变更（用户强制锁定）

**事件：** 用户坚持分析原顺序是「铜→白银→黄金→原油→金油比→金银铜比→DXY/CNH→SOX」，但当天报告是「黄金→金油比→原油→DXY→VIX」。覆盖顺序导致全部重新生成。

**教训：** 分析模块 8 段顺序已写入 agent 指令锁定，**不可改变**。
