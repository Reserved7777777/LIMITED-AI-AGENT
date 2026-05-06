#!/usr/bin/env python3
"""
每30分钟同步实时数据(仅修改 HTML,不重建)
只更新:XAU/USD, VIX, WTI, Brent, USD/CNY + 财联社风险
"""

import os, sys, re, argparse
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
OUTPUT_DIR = '/var/www/openclaw'

# ============================================================
# FUTUNN - headless browser
# ============================================================
def futunn_text(url):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            ctx = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')
            page = ctx.new_page()
            page.goto(url, timeout=25000, wait_until='load')
            page.wait_for_timeout(3000)
            text = page.evaluate('() => document.body.innerText')
            browser.close()
            return text
    except Exception as e:
        print(f"  futunn failed: {e}", file=sys.stderr)
        return None

def parse(text):
    if not text: return None, None, None
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    for i, line in enumerate(lines):
        if re.match(r'^[\d,]+\.?\d*$', line):
            nxt = lines[i+1] if i+1 < len(lines) else ''
            m = re.match(r'^([+-]?[\d,.]+)\s*([+-]?[\d.]+%)?\s*$', nxt)
            if m:
                raw = m.group(1).replace(',', '')
                # guard against malformed numbers like '0.000000.0'
                if raw.count('.') > 1:
                    raw = raw[:raw.find('.', raw.find('.') + 1)]
                try:
                    ch = float(raw)
                except ValueError:
                    ch = None
                if m.group(2):
                    raw_cp = m.group(2).replace('%', '')
                    if raw_cp.count('.') > 1:
                        raw_cp = raw_cp[:raw_cp.find('.', raw_cp.find('.') + 1)]
                    try:
                        cp = float(raw_cp)
                    except ValueError:
                        cp = None
                else:
                    cp = None
            else:
                ch = None
                cp = None
            try:
                pr = float(line.replace(',', ''))
            except ValueError:
                pr = None
            if pr is not None:
                return pr, ch, cp
    return None, None, None

# ============================================================
# HTML PATCHER
# ============================================================
def patch_html(html, marker, new_price, new_change, new_chgp):
    pos = html.find(marker)
    if pos == -1:
        print(f"  marker '{marker}' not found")
        return html, False

    # Restrict search to within the SAME card/article element
    # Find the enclosing card section to avoid matching other cards
    # Look for </a> before marker (we're inside a card), or find the card separator
    search_end = html.find('</a>', pos)
    if search_end >= 0:
        search_end += 4  # include the </a>
    after = html[pos:search_end] if search_end > pos else html[pos:pos+500]

    m = re.search(r'<div class="(price|p)\s+(up|down)">([^<]*)</div>', after)
    if not m:
        return html, False
    price_old = m.group(3)
    price_new = f"{new_price:,.2f}"

    m2 = re.search(r'<div class="(change|c)\s+(up|down)">([^<]*?)(?:\s*<span[^>]*>([^<]*)</span>)?\s*</div>', after)
    if not m2:
        return html, False

    change_old = m2.group(3).strip()
    chgp_old = m2.group(4) if m2.group(4) else ''
    change_new = f"{'+' if new_change >= 0 else ''}{new_change:.2f}" if new_change is not None else ''
    chgp_new = f"{'+' if new_chgp >= 0 else ''}{new_chgp:.2f}%" if new_chgp is not None else '+0.00%'

    html = html.replace(price_old, price_new, 1)
    html = html.replace(change_old, change_new, 1)
    if chgp_old:
        html = html.replace(chgp_old, chgp_new, 1)

    is_up = new_change >= 0 if new_change is not None else True
    cls = 'up' if is_up else 'down'

    old_price_cls = f'class="price {m.group(2)}"' if 'price' in m.group(1) else f'class="p {m.group(2)}"'
    new_price_cls = f'class="price {cls}"' if 'price' in m.group(1) else f'class="p {cls}"'
    html = html.replace(old_price_cls, new_price_cls, 1)

    old_change_cls = f'class="change {m2.group(2)}"' if 'change' in m2.group(1) else f'class="c {m2.group(2)}"'
    new_change_cls = f'class="change {cls}"' if 'change' in m2.group(1) else f'class="c {cls}"'
    html = html.replace(old_change_cls, new_change_cls, 1)

    return html, True

def fmt_price_gold(v):
    return f"{v:,.2f}"

def fmt_price_cnh(v):
    return f"{v:,.4f}"

# ============================================================
# RISK SYNC - 财联社
# ============================================================
def sync_risks_from_cls(html):
    """Fetch latest headlines from Cailian, sync risk items (keep 3-5, newest first)."""
    risk_kw = ['中东', '冲突', '制裁', '关税', '封锁', '扣押', '能源危机',
               '债务', '违约', '通胀', 'CPI', '加息', '降息',
               '战事', '军事', '霍尔木兹', '油价', '危机', '谈判',
               '美联储', '非农', '就业', 'GDP', '衰退', '抛售',
               '美股', 'A股', '港股', '市场震荡', '停牌', '退市',
               '核', '打击', '伊朗', '以色列', '俄罗斯', '乌克兰',
               '大涨', '市值', '突破', '新高', '利好', '财报',
               '收涨', '收跌', '涨幅', '跌幅', '贸易']

    import urllib.request as _ur
    try:
        req = _ur.Request('https://www.cls.cn/telegraph',
                          headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                   'Referer': 'https://www.cls.cn/'})
        resp = _ur.urlopen(req, timeout=15)
        html_raw = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print("  Cailian fetch failed: " + str(e))
        return html

    # Extract all titles with detail URLs - collect BOTH keyword matched and top headlines
    kw_matched = []
    all_headlines = []
    pos = 0
    while True:
        ob = html_raw.find(chr(0x3010), pos)
        if ob < 0:
            break
        cb = html_raw.find(chr(0x3011), ob)
        if cb < 0:
            pos = ob + 3
            continue
        title = html_raw[ob+1:cb]
        if not title or len(title) > 80:
            pos = cb + 1
            continue

        nearby = html_raw[ob:ob+2000]
        url_m = re.search(r'/detail/(\d+)', nearby)

        after = html_raw[cb+1:cb+300]
        for tag in ['<br', '<div', '</div', '<a', '</a', '<span', '&nbsp']:
            ti = after.find(tag)
            if ti > 0:
                after = after[:ti]
        after = re.sub(r'<[^>]+>', '', after).strip()
        if len(after) > 120:
            after = after[:120] + '...'

        line = chr(0x3010) + title + chr(0x3011) + after
        if url_m:
            is_kw = any(kw in line for kw in risk_kw)
            if is_kw:
                kw_matched.append(('/detail/' + url_m.group(1), line, title))
            else:
                all_headlines.append(('/detail/' + url_m.group(1), line, title))
        pos = cb + 1

    print("  Cailian: " + str(len(kw_matched)) + " keyword items, " + str(len(all_headlines)) + " total items")

    # Merge: keyword items first, then top headlines, then existing
    seen_titles = set()
    merged = []
    for url, line, t in kw_matched:
        key = t[:20]
        if key not in seen_titles:
            merged.append((url, line))
            seen_titles.add(key)

    merged = merged[:5]
    print("  Risks merged: " + str(len(merged)) + " items")

    # Build risk HTML
    risk_html = '<!-- ===== RISK ===== -->\n  <div class="sec-label">\n    <span>⚠️ 关键风险提示</span>\n  </div>\n  <div class="risk-list">\n'
    for url, line in merged:
        title_end = line.find(chr(0x3011))
        title = line[1:title_end] if title_end > 0 else line[:30]
        desc = line.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        if url:
            full_url = url
            if not full_url.startswith('http'):
                full_url = 'https://www.cls.cn' + full_url
            item = '''    <a class="risk-item" href="%s" target="_blank">
      <div class="r-dot"></div>
      <div class="r-text"><strong>%s</strong> - %s</div>
    </a>
''' % (full_url, title, desc)
        else:
            item = '''    <div class="risk-item">
      <div class="r-dot"></div>
      <div class="r-text"><strong>%s</strong> - %s</div>
    </div>
''' % (title, desc)
        risk_html += item
    risk_html += '    </div>'

    # Replace risk section in HTML
    start = html.find('<!-- ===== RISK ===== -->')
    if start < 0:
        start = html.find('<div class="risk-list">')
        if start < 0:
            print("  risk-list not found in HTML")
            return html
    end = html.find('<!-- ===== EVENTS ===== -->', start)
    if end < 0:
        end = html.find('<div class="sec-label"', start + 30)
        if end < 0:
            end = html.find('</div>', start + 30)
            if end >= 0:
                end += 6
    if end < 0:
        return html
    html = html[:start] + risk_html + html[end:]
    print("  Risks synced: " + str(len(merged)) + " items")
    return html

# ============================================================
# ANALYSIS SYNC - generate from current prices
# ============================================================
def sync_analysis(html):
    """Read current prices from cfx cards and regenerate analysis text."""
    def extract_cfx_price(html, marker):
        pos = html.find(marker)
        if pos < 0: return None, None, None
        card_end = html.find('</a>', pos)
        if card_end >= 0: card_end += 4
        section = html[pos:card_end] if card_end > pos else html[pos:pos+500]
        p = re.search(r'class="p[^"]*"[^>]*>([\d.,]+)', section)
        c = re.search(r'class="c[^"]*"[^>]*>([+\-]?[\d.]+)', section)
        cp = re.search(r'([+\-]?[\d.]+%)', section)
        try:
            price = float(p.group(1).replace(',', '')) if p else None
        except ValueError:
            price = None
        try:
            chg = float(c.group(1)) if c else None
        except ValueError:
            chg = None
        try:
            chgp = float(cp.group(1).replace('%', '')) if cp else None
        except ValueError:
            chgp = None
        return price, chg, chgp

    g, _, gcp = extract_cfx_price(html, 'XAU')
    wti, _, wcp = extract_cfx_price(html, 'WTI')
    brent, _, bcp = extract_cfx_price(html, '布伦特')
    vix_p, _, vix_cp = extract_cfx_price(html, 'VIX')

    # Extract CNH from cfx card
    cnh = None
    cnh_pos = html.find('USD/CNY')
    if cnh_pos < 0: cnh_pos = html.find('USDCNH')
    if cnh_pos >= 0:
        cnh_section = html[cnh_pos:cnh_pos+100]
        cnh_m = re.search(r'class="p[^"]*"[^>]*>([\d.]+)', cnh_section)
        if cnh_m: cnh = cnh_m.group(1)

    g_str = f"${g:,.2f}" if g else "N/A"
    w_str = f"${wti:.2f}" if wti else "N/A"
    b_str = f"${brent:.2f}" if brent else "N/A"
    v_str = f"{vix_p:.2f}" if vix_p else "N/A"
    cnh_str = cnh if cnh else "N/A"

    g_chg_str = f"(+{gcp:.2f}%)" if gcp and gcp >= 0 else f"({gcp:.2f}%)" if gcp else ""
    w_chg_str = f"(+{wcp:.2f}%)" if wcp and wcp >= 0 else f"({wcp:.2f}%)" if wcp else ""
    b_chg_str = f"(+{bcp:.2f}%)" if bcp and bcp >= 0 else f"({bcp:.2f}%)" if bcp else ""

    lines = []
    # Add 金油比 (gold/oil ratio)
    gold_wti_ratio = f"{g/wti:.1f}" if g and wti and wti > 0 else "N/A"
    lines.append(f'      <strong><a href="https://www.futunn.com/currency/XAUUSD-FX" target="_blank" style="color:var(--text);text-decoration:none;">\u9ec4\u91d1</a></strong>:{g_str}{g_chg_str}。\u91d1\u4ef7\u7ef4\u6301\u5386\u53f2\u9ad8\u4f4d\u533a\u95f4,\u5730\u7f18\u6ea2\u4ef7+\u592e\u884c\u8d2d\u91d1\u53cc\u652f\u6491,\u5173\u6ce8\u5468\u4e09 Fed \u51b3\u8bae\u6307\u5f15。<br>')
    lines.append(f'      <strong>\u91d1\u6cb9\u6bd4</strong>:{gold_wti_ratio}:1\uff08\u9ec4\u91d1/WTI\uff09。\u5386\u53f2\u4e2d\u4f4d\u7ea7\u522b,\u5730\u7f18\u98ce\u9669\u5b9a\u4ef7\u5145\u5206,\u6ce8\u610f\u6cb9\u4ef7\u5f31\u52bf\u5bfc\u81f4\u6bd4\u7387\u504f\u9ad8\u3002<br>')
    lines.append(f'      <strong>\u539f\u6cb9</strong>:{w_str}{w_chg_str},{b_str}{b_chg_str}。\u6cb9\u4ef7 100+ \u9ad8\u4f4d\u8fd0\u884c,\u970d\u5c14\u6728\u5179\u5730\u7f18\u6ea2\u4ef7\u6301\u7eed,\u5173\u6ce8\u5c40\u52bf\u5347\u7ea7\u5bf9\u4f9b\u5e94\u94fe\u7684\u5f71\u54cd。<br>')
    lines.append(f'      <strong>\u7f8e\u5143/\u4eba\u6c11\u5e01</strong>:{cnh_str}。\u4eba\u6c11\u5e01\u6c47\u7387\u77ed\u671f\u7a33\u5b9a,\u8de8\u5883\u8d44\u91d1\u65e0\u5f02\u5e38。\u5173\u6ce8 Fed \u51b3\u8bae\u5bf9\u7f8e\u5143\u65b9\u5411\u7684\u5f71\u54cd。<br>')
    lines.append(f'      <strong>VIX</strong>:{v_str}。\u5904\u4e8e\u4e2d\u4f4d\u533a\u95f4,\u5e02\u573a\u5bf9\u672c\u5468 Fed \u51b3\u8bae+\u975e\u519c\u6570\u636e\u4fdd\u6301\u8b66\u60d5。<br>')
    new_html = '<!-- ANALYSIS -->\n  <div class="analysis">\n    <div class="a-label">\U0001f4ca \u5546\u54c1\u4e0e\u6c47\u7387\u5206\u6790</div>\n    <div class="a-body">\n' + '\n'.join(lines) + '\n    </div>\n  </div>'

    # Find the analysis section between COMMODITY & FX and risk-list
    # The cfx-grid ends, then the analysis text starts, then risk-list
    start = html.find('  <div class="cfx-grid">')
    if start >= 0:
        # Find the end of cfx-grid
        cfx_end = html.find('  </div>', start)
        if cfx_end >= 0:
            cfx_end = html.find('\n', cfx_end + 8)  # line after </div>
            # After cfx grid, there's the analysis text, then risk-list
            risk_start = html.find('<!-- ===== RISK ===== -->', cfx_end)
            if risk_start < 0:
                risk_start = html.find('<div class="risk-list">', cfx_end)
            if risk_start >= 0 and risk_start > cfx_end:
                html = html[:cfx_end] + '\n' + new_html + '\n' + html[risk_start:]
                print("  Analysis synced")
                return html

    # Fallback: find analysis lines by their position
    start = html.find('<!-- ===== COMMODITY & FX ===== -->')
    if start >= 0:
        # Find the first analysis line (look for '黄金')
        an_start = html.find('<strong><a', start)
        if an_start < 0:
            an_start = html.find('<strong>\u9ec4\u91d1', start)
        an_end = html.find('<!-- ===== RISK ===== -->', an_start) if an_start >= 0 else -1
        if an_end < 0:
            an_end = html.find('<div class="risk-list">', an_start) if an_start >= 0 else -1
        if an_start >= 0 and an_end > an_start:
            html = html[:an_start] + new_html + html[an_end:]
            print("  Analysis synced")
            return html

    print("  analysis section not found")
    return html

def sync_events(html):
    """Regenerate economic calendar. Currently hardcoded 8 items with stars."""
    stars_map = {1: '\u2605\u2606\u2606\u2606\u2606',
                 2: '\u2605\u2605\u2606\u2606\u2606',
                 3: '\u2605\u2605\u2605\u2606\u2606',
                 4: '\u2605\u2605\u2605\u2605\u2606',
                 5: '\u2605\u2605\u2605\u2605\u2605'}
    events = [
        ('05.04', 'ISN制造业PMI', 4),
        ('05.05', 'JOLTS职位空缺', 3),
        ('05.06', 'ADP就业数据', 4),
        ('05.06', 'A股节后复盘', 2),
        ('05.07', '美联储利率决议', 5),
        ('05.07', '鲍威尔新闻发布会', 4),
        ('05.08', '失业金人数', 2),
        ('05.08', '非农就业数据', 5),
    ]
    ev_html = '<div class="event-calendar">\n'
    for date_str, name, r in events:
        s = stars_map.get(r, stars_map[3])
        ev_html += '    <div class="ev-item"><div class="d">' + date_str + '  ' + s + '</div><div class="e">' + name + '</div></div>\n'
    ev_html += '    </div>'

    start = html.find('<!-- ===== EVENTS ===== -->')
    if start < 0:
        print("  events section not found")
        return html
    end = html.find('<!-- FOOTER -->', start)
    if end < 0:
        end = html.find('<div class="footer"', start)
        if end < 0:
            end = start + 500
    html = html[:start] + '<!-- ===== EVENTS ===== -->\n' + ev_html + '\n' + html[end:]
    print("  Events synced: 8 items")
    return html

def sync_stance(html):
    """Generate stance bar and core insight from current HTML data."""
    def extract_val_chg(html, marker):
        pos = html.find(marker)
        if pos < 0: return None, None
        # Restrict to within same card
        search_end = html.find('</a>', pos)
        if search_end >= 0: search_end += 4
        after = html[pos:search_end] if search_end > pos else html[pos:pos+500]
        p = re.search(r'<(?:div|span) class="[^"]*(?:p|price)[^"]* (up|down)">([^<]+)</(?:div|span)>', after)
        if not p:
            m_vix = re.search(r'<div class="price" style="color:var\(--red\);">([^<]+)</div>', after)
            if m_vix:
                p = type('', (), {'group': lambda self, n: m_vix.group(1) if n == 2 else 'down'})()
        c = re.search(r'<(?:div|span) class="[^"]*(?:c|change)[^"]* (up|down)">[^<]*?([+-]?[\d,.]+)[^<]*?</(?:div|span)>', after)
        price = p.group(2) if p else None
        chg = c.group(2) if c else None
        cls_p = p.group(1) if p else 'up'
        cls_c = c.group(1) if c else 'up'
        return price, chg, cls_p
    
    # Extract key data
    spx_p, spx_c, _ = extract_val_chg(html, 'S&P 500') or (None, None, '')
    vix_p, vix_c, vix_cls = extract_val_chg(html, 'VIX') or (None, None, '')
    sh_p, sh_c, _ = extract_val_chg(html, '上证指数') or (None, None, '')
    hk_p, hk_c, _ = extract_val_chg(html, '恒生科技') or (None, None, '')
    gold_p, gold_c, _ = extract_val_chg(html, 'XAU/USD') or (None, None, '')
    wti_p, wti_c, _ = extract_val_chg(html, 'WTI 原油') or (None, None, '')

    # === A股 stance ===
    a_pct, a_stance, a_color = 50, '保守买入', 'var(--orange)'
    try:
        vix_num = float(vix_p.replace(',','')) if vix_p else 20
    except ValueError:
        vix_num = 20
    try:
        gold_num = float(gold_p.replace(',','')) if gold_p else 0
    except ValueError:
        gold_num = 0
    try:
        sh_num = float(sh_p.replace(',','')) if sh_p else 0
    except ValueError:
        sh_num = 0
    try:
        hk_num = float(hk_p.replace(',','')) if hk_p else 0
    except ValueError:
        hk_num = 0
    
    # A股 logic: SH above 4100 = neutral positive; HK hold above 4900
    if sh_num and sh_num > 4120:
        a_stance, a_pct, a_color = '保守买入', 55, 'var(--orange)'
    if hk_num and hk_num < 4900:
        a_stance, a_pct, a_color = '持币观望', 30, 'var(--green)'
    if sh_num and sh_num < 4080:
        a_stance, a_pct, a_color = '持币观望', 20, 'var(--green)'
    
    # === US stance ===
    us_pct, us_stance, us_color = 50, '持币观望', 'var(--green)'
    try:
        spx_num = float(spx_p.replace(',','')) if spx_p else 0
    except ValueError:
        spx_num = 0
    
    # US logic: VIX > 20 = fear (cautious), VIX < 18 = complacency (cautious bullish)
    if vix_cls == 'up':  # VIX rising = fear
        us_stance, us_pct, us_color = '保守空头', 30, 'var(--green)'
    elif vix_num < 18:
        us_stance, us_pct, us_color = '保守买入', 50, 'var(--orange)'
    elif vix_num >= 19:
        us_stance, us_pct, us_color = '持币观望', 30, 'var(--green)'
    else:
        us_stance, us_pct, us_color = '保守买入', 40, 'var(--orange)'
    
    if spx_num and spx_num < 7150:
        us_stance, us_pct = '持币观望', 20

    # === Core insight ===
    gold_dir = '偏强' if gold_c and '+' in str(gold_c) else '承压'
    wti_dir = '偏强' if wti_c and '+' in str(wti_c) else '回调'
    
    insights = []
    if vix_num > 19:
        insights.append(f'VIX {vix_num} 中位偏高，市场对周三 Fed 决议保持警戒')
    if gold_num > 4500:
        insights.append(f'黄金 {gold_num} 维持历史高位，地缘风险定价充分')
    if hk_num and hk_num > 4900:
        insights.append(f'恒生科技 {hk_num} 稳守 4900，A股节后表现平稳')
    
    insight = '；'.join(insights) if insights else '市场整体缺乏明确方向，等待本周 Fed 决议和非农数据落地。'
    insight += ' 本周关注：Fed 5/7 利率决议 + 鲍威尔新闻发布会、5/8 非农就业、霍尔木兹局势演变。'

    # Build stance HTML
    new_stance = f'''  <div class="stance-bar">
    <div class="stance-item">
      <div class="info"><div class="lbl">A股立场</div><div class="val" style="color:{a_color};font-weight:700;">{a_stance} {a_pct}%</div></div>
      <div class="mbar"><div class="fill" style="width:{a_pct}%;background:{a_color};"></div></div>
    </div>
    <div class="stance-item">
      <div class="info"><div class="lbl">美股立场</div><div class="val" style="color:{us_color};font-weight:700;">{us_stance} {us_pct}%</div></div>
      <div class="mbar"><div class="fill" style="width:{us_pct}%;background:{us_color};"></div></div>
    </div>
  </div>'''

    new_insight = f'''  <div class="insight">
    <span class="label">核心观点</span>
    <span>{insight}</span>
  </div>'''

    # Replace stance bar
    s_start = html.find('<div class="stance-bar">')
    s_end = html.find('<!-- INSIGHT -->', s_start)
    if s_end < 0: s_end = html.find('\
  <!--', s_start)
    if s_start >= 0 and s_end > s_start:
        html = html[:s_start] + new_stance + html[s_end:]
    
    # Replace insight
    i_start = html.find('<div class="insight">')
    i_end = html.find('<!-- ===== TIER 1 ===== -->', i_start)
    if i_end < 0: i_end = html.find('\
  <!--', i_start + 50)
    if i_start >= 0 and i_end > i_start:
        html = html[:i_start] + new_insight + html[i_end:]
    
    print(f"  Stance synced: A股 {a_stance} {a_pct}% | 美股 {us_stance} {us_pct}%")
    return html

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    args = parser.parse_args()

    date = args.date
    html_path = os.path.join(OUTPUT_DIR, f'report-{date}.html')
    dstr = datetime.now(TZ).strftime('%H:%M')

    if not os.path.exists(html_path):
        print(f"ERROR: {html_path} not found"); sys.exit(1)

    with open(html_path, 'r') as f:
        html = f.read()

    updates = []

    # 1. XAU/USD
    text = futunn_text('https://www.futunn.com/currency/XAUUSD-FX')
    if text:
        p, ch, cp = parse(text)
        if p:
            html, ok = patch_html(html, 'XAU/USD', p, ch if ch else 0, cp if cp else 0)
            if ok: updates.append(f"gold={p:,.2f}")

    # 2. USD/CNY
    text = futunn_text('https://www.futunn.com/currency/USDCNH-FX')
    if text:
        p, ch, cp = parse(text)
        if p:
            html, ok = patch_html(html, 'USD/CNY', p, ch if ch else 0, cp if cp else 0)
            if ok: updates.append(f"CNH={p:,.4f}")

    # 3. WTI
    text = futunn_text('https://www.futunn.com/futures/CLMAIN-US')
    if text:
        p, ch, cp = parse(text)
        if p:
            html, ok = patch_html(html, 'WTI 原油', p, ch if ch else 0, cp if cp else 0)
            if ok: updates.append(f"WTI={p}")

    # 4. Brent
    text = futunn_text('https://www.futunn.com/futures/BZMAIN-US')
    if text:
        p, ch, cp = parse(text)
        if p:
            html, ok = patch_html(html, '布伦特', p, ch if ch else 0, cp if cp else 0)
            if ok: updates.append(f"Brent={p}")

    # 5. VIX — special handling (uses inline style, not up/down class)
    text = futunn_text('https://www.futunn.com/futures/VXMAIN-US')
    if text:
        p, ch, cp = parse(text)
        if p:
            # VIX card uses: <div class="price" style="color:var(--red);">OLD</div>
            vix_pos = html.find('VIX')
            if vix_pos >= 0:
                after = html[vix_pos:]
                m = __import__('re').search(r'<div class="price" style="color:var\(--red\);">([^<]+)</div>', after)
                if m:
                    old_p = m.group(1)
                    new_p = f"{p:,.2f}"
                    html = html.replace(old_p, new_p, 1)
                    updates.append(f"VIX={p}")
                    # Update change too (same style format)
                    m2 = __import__('re').search(r'<div class="change" style="color:var\(--red\);">([^<]+?)<span', after)
                    if m2:
                        old_ch = m2.group(1).strip()
                        new_ch = f"{'+' if ch >= 0 else ''}{ch:.2f}" if ch else '0.00'
                        html = html.replace(old_ch, new_ch, 1)
                    # Update change% in span
                    m3 = __import__('re').search(r'<span class="sub2">([^<]+)</span>', after)
                    if m3:
                        old_cp = m3.group(1)
                        new_cp = f"{'+' if cp >= 0 else ''}{cp:.2f}%" if cp else '+0.00%'
                        html = html.replace(old_cp, new_cp, 1)
                else:
                    print(f"  VIX: price element not found (style format)")

    # 6. Risks from 财联社
    html = sync_risks_from_cls(html)
    
    # 7. (SKIPPED) Stance & insight — MARCUS 当日综合分析确定，不动
    
    # 8. Analysis section — sync with current commodity prices
    html = sync_analysis(html)
    
# ============================================================
    # 9. HTML SELF-CHECK — verify all markers, auto-repair if broken
    # ============================================================
    _required_markers = [
        '<!-- HEADER -->',
        '<!-- ===== INDICES ===== -->',
        '<!-- STANCE -->',
        '<!-- INSIGHT -->',
        '<!-- ===== TIER 1 ===== -->',
        '<!-- ===== TIER 2 ===== -->',
        '<!-- ===== TIER 3 ===== -->',
        '<!-- ===== COMMODITY & FX ===== -->',
        '<!-- ANALYSIS -->',
        '<!-- ===== RISK ===== -->',
        '⚠️ 关键风险提示',
        '<!-- ===== EVENTS ===== -->',
        '<!-- FOOTER -->',
    ]
    _missing = [m for m in _required_markers if m not in html]
    if _missing:
        print(f"  ⚠️  SELF-CHECK: missing {len(_missing)} markers: {', '.join(_missing)}", file=sys.stderr)
        # Auto-repair: rebuild report using build_report.py with cached data
        _date = date
        _cache_path = f'/tmp/report-data-{_date}.json'
        if os.path.exists(_cache_path):
            print(f"  Auto-repair: rebuilding report from {_cache_path}", file=sys.stderr)
            import subprocess as _sp
            _r = _sp.run(
                ['python3', '/root/.openclaw/workspace/build_report.py',
                 '--date', _date, '--data', _cache_path],
                capture_output=True, text=True, timeout=90
            )
            if _r.returncode == 0:
                # Re-read the repaired HTML
                with open(html_path, 'r') as _rf:
                    html = _rf.read()
                print(f"  ✅ Auto-repair: report rebuilt successfully")
                # Re-check
                _still_missing = [m for m in _required_markers if m not in html]
                if _still_missing:
                    print(f"  ⚠️  Auto-repair partial: still missing {_still_missing}", file=sys.stderr)
            else:
                print(f"  ❌ Auto-repair failed: {_r.stderr[:200]}", file=sys.stderr)
        else:
            print(f"  ⚠️  Auto-repair: no cache at {_cache_path}, skipping", file=sys.stderr)
    else:
        print(f"  ✅ SELF-CHECK: all {len(_required_markers)} markers OK")

    # Write updated HTML
    with open(html_path, 'w') as f:
        f.write(html)

    # Verify
    import subprocess
    r = subprocess.run(['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', f'http://1.14.93.56/static/report-{date}.html'],
                     capture_output=True, text=True, timeout=5)
    if updates:
        print(f"[{dstr}] Updated {len(updates)} items: {', '.join(updates)}")
    print(f"  HTTP {r.stdout.strip()}")

if __name__ == '__main__':
    main()
