#!/usr/bin/env python3
"""
每日动量报告 - HTML 构建脚本
用法: python3 build_report.py --date YYYY-MM-DD [--template PATH] [--output PATH]

数据从以下来源获取:
1. 腾讯财经 API (A股指数分钟数据)
2. Finnhub API (美股 OHLC 用于合成分时路径)
3. --data JSON 文件 (报告文本数据)
"""
import sys, json, os, re, random, math, urllib.request, argparse, time as _time_module

random.seed(int(_time_module.time()))

TEMPLATE_DEFAULT = '/root/.openclaw/workspace/report-template.html'
OUTPUT_DEFAULT  = '/var/www/openclaw/report-{date}.html'
FINNHUB_TOKEN   = os.environ.get('FINNHUB_TOKEN', '')

# ============================================================
# HELPERS: Nesting-aware HTML section replacement
# ============================================================
def _find_closing_tag(html, start, tag='div'):
    """Find matching closing tag for an opening tag at `start`."""
    open_tag = f'<{tag}'
    close_tag = f'</{tag}>'
    depth = 1
    i = html.index('>', start) + 1
    while i < len(html) and depth > 0:
        if html[i:i+len(open_tag)] == open_tag and '>' in html[i:]:
            tag_end = html.index('>', i)
            if '/>' not in html[i:tag_end+1]:
                depth += 1
            i = tag_end + 1
        elif html[i:i+len(close_tag)] == close_tag:
            depth -= 1
            if depth > 0:
                i += len(close_tag)
            else:
                return i + len(close_tag)
        else:
            i += 1
    return i

def _replace_tag(html, class_name, new_html, tag='div'):
    """Replace <tag class='class_name'>…</tag> with new_html, handling nesting."""
    if tag == 'ul':
        pattern = f'<ul class="{class_name}">'
    else:
        pattern = f'<{tag} class="{class_name}">'
    start = html.find(pattern)
    if start < 0:
        return html
    end = _find_closing_tag(html, start, tag)
    return html[:start] + new_html + html[end:]

def _replace_section_between(html, start_marker, end_marker, new_html):
    """Replace everything between start_marker and end_marker."""
    s = html.find(start_marker)
    e = html.find(end_marker, s)
    if s < 0 or e < 0:
        return html
    return html[:s] + new_html + html[e:]

# ============================================================
# HELPER: Fetch intraday minute data (A-share)
# ============================================================
def fetch_minute_data(code):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data_{code}&code={code}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=8)
        raw = resp.read().decode('utf-8')
        j = json.loads(raw.split('=', 1)[1])
        for key in [code, code.replace('.', '')]:
            td = j.get('data', {}).get(key, {}).get('data', {}).get('data', [])
            if td:
                return [float(p.split()[1]) for p in td if p.strip()]
        return []
    except Exception:
        return []

def fetch_finnhub_quote(symbol):
    if not FINNHUB_TOKEN:
        return None
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_TOKEN}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=8)
        return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None

# ============================================================
# HELPER: Generate SVG sparkline path
# ============================================================
def gen_svg_path(prices, width=80, height=32):
    if not prices:
        mid = height / 2
        return f"M1,{mid} L{width-1},{mid}"
    n = len(prices)
    min_p = min(prices)
    max_p = max(prices)
    rng = max_p - min_p
    if rng == 0:
        rng = 1
    pts_needed = min(n, width // 2)
    step = max(1, n // pts_needed) if pts_needed > 0 else 1
    sampled = prices[::step]
    if sampled[-1] != prices[-1]:
        sampled.append(prices[-1])
    n2 = len(sampled)
    pts = []
    for i, p in enumerate(sampled):
        x = round((i / (n2 - 1)) * (width - 4) + 2, 1) if n2 > 1 else width / 2
        y = round(height - 4 - ((p - min_p) / rng) * (height - 8), 1)
        pts.append(f"{x},{y}")
    return "M" + " L".join(pts)

def gen_synthetic_path(open_p, high_p, low_p, close_p, points=60, width=120, height=32):
    prices = []
    for i in range(points):
        progress = i / (points - 1)
        target = open_p + (close_p - open_p) * progress
        noise_amp = (high_p - low_p) * 0.35
        noise = (random.random() - 0.5) * noise_amp
        prices.append(target + noise)
    prices[0] = open_p
    prices[-1] = close_p
    return gen_svg_path(prices, width, height)

def fmt_price(val):
    if val is None: return "N/A"
    if abs(val) < 10: return f"{val:.2f}"
    if abs(val) < 1000: return f"{val:.2f}"
    return f"{val:,.2f}"

def fmt_percent(val):
    if val is None: return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}%"

# ============================================================
# BUILD A SINGLE INDEX CARD
# ============================================================
def build_index_card(name, price, change, chg_pct, href, spark_path, spark_color, is_vix=False):
    price_str = fmt_price(price)
    change_str = f"{'+' if change >= 0 else ''}{change:.2f}" if change else "0.00"
    chgp_str = fmt_percent(chg_pct)
    is_up = change >= 0 if change is not None else True
    price_cls = "up" if is_up else "down"
    change_cls = "up" if is_up else "down"
    
    svg_html = f'''<svg class="spark" viewBox="0 -4 80 32"><path d="{spark_path}" fill="none" stroke="{spark_color}" stroke-width="1.8" stroke-linecap="round"/></svg>'''
    
    if is_vix:
        return f'''<a class="idx-card" href="{href}" target="_blank">
      <div class="info">
        <span class="name">{name}</span>
        <div class="price" style="color:var(--red);">{price_str}</div>
        <div class="change" style="color:var(--red);">{change_str} <span class="sub2">{chgp_str}</span></div>
      </div>
      <div class="chart">{svg_html}</div>
    </a>'''
    else:
        return f'''<a class="idx-card" href="{href}" target="_blank">
      <div class="info">
        <span class="name">{name}</span>
        <div class="price {price_cls}">{price_str}</div>
        <div class="change {change_cls}">{change_str} <span class="sub2">{chgp_str}</span></div>
      </div>
      <div class="chart">{svg_html}</div>
    </a>'''

# ============================================================
# BUILD INDEX ROW (ALL 8 CARDS AT ONCE)
# ============================================================
def build_idx_row(report_data, sparklines):
    idx_config = [
        ('SPX', 'S&P 500',     'https://www.futunn.com/index/.SPX-US',       False),
        ('NDX', 'NASDAQ',       'https://www.futunn.com/index/.IXIC-US',      False),
        ('DJI', '道琼斯',        'https://www.futunn.com/index/.DJI-US',      False),
        ('VIX', 'VIX',          'https://www.futunn.com/futures/VXMAIN-US',   True),
        ('SH',  '上证指数',       'https://www.futunn.com/index/000001-SH',   False),
        ('SZ',  '深证成指',       'https://www.futunn.com/index/399001-SZ',   False),
        ('CY',  '创业板指',       'https://www.futunn.com/index/399006-SZ',   False),
        ('HK',  '恒生科技',      'https://www.futunn.com/stock/800700-HK',   False),
    ]
    
    cards = []
    for key, name, href, is_vix in idx_config:
        idx_data = report_data.get('indices', {}).get(key, {})
        price   = idx_data.get('price', 0)
        change  = idx_data.get('change', 0)
        chg_pct = idx_data.get('chg_pct', 0)
        sp = sparklines.get(key, f"M1,16 L119,16")
        sc = sparklines.get(f'{key}_color', '#00C853')
        cards.append(build_index_card(name, price, change, chg_pct, href, sp, sc, is_vix))
    
    indent = '    '
    return '<div class="idx-row">\n' + indent + ('\n' + indent).join(cards) + '\n  </div>'

# ============================================================
# BUILD TABLE ROWS FOR A TIER
# ============================================================
def build_tier_table(tier_data, tb_cls='tb-high'):
    stocks = tier_data.get('stocks', [])
    rows = []
    for j, stock in enumerate(stocks[:10]):
        seq = j + 1
        sym = stock.get('symbol', 'N/A')
        name = stock.get('name', '')
        price = stock.get('price', 0)
        change = stock.get('change', 0)
        chgp = stock.get('chg_pct', 0)
        vol = stock.get('volume', '')
        amt = stock.get('amount', '')
        cap = stock.get('market_cap', '')
        tag = stock.get('tag', '')
        href = stock.get('href', f'https://www.futunn.com/stock/{sym}-US')
        is_up = change >= 0 if change is not None else True
        
        price_str = fmt_price(price)
        change_str = f"{'+' if change >= 0 else ''}{change:.2f}" if change else "0.00"
        chgp_str = fmt_percent(chgp)
        p_cls = "up" if is_up else "down"
        
        rows.append(f'''<a class="tbl-row" href="{href}" target="_blank">
      <span class="col-seq" style="color:var(--dim);">{seq}</span>
      <span class="s-sym col-sym">{sym}</span>
      <span class="s-name col-name">{name}</span>
      <span class="s-last col-last {p_cls}">{price_str}</span>
      <span class="col-chg {p_cls}">{change_str}</span>
      <span class="col-chgp {p_cls}">{chgp_str}</span>
      <span class="col-vol" style="color:var(--dim);font-size:11px;">{vol}</span>
      <span class="col-amt" style="color:var(--dim);font-size:11px;">{amt}</span>
      <span class="col-cap" style="color:var(--dim);font-size:11px;">{cap}</span>
      <span class="col-tag"><span class="tb-tag {tb_cls}">{tag}</span></span>
    </a>''')
    
    if not rows:
        rows.append(f'''<a class="tbl-row" href="#" style="cursor:default;">
      <span class="col-seq" style="color:var(--dim);">-</span>
      <span class="s-sym col-sym">-</span>
      <span class="s-name col-name" style="color:var(--dim);">暂无数据</span>
      <span class="col-last" style="color:var(--dim);">-</span>
      <span class="col-chg" style="color:var(--dim);">-</span>
      <span class="col-chgp" style="color:var(--dim);">-</span>
      <span class="col-vol" style="color:var(--dim);">-</span>
      <span class="col-amt" style="color:var(--dim);">-</span>
      <span class="col-cap" style="color:var(--dim);">-</span>
      <span class="col-tag"></span>
    </a>''')
    
    return f'''<div class="table-wrap">
    <div class="tb-scroll">
    <div class="table-hd">
      <span class="col-seq">#</span><span class="col-sym">代码</span><span class="col-name">名称</span>
      <span class="col-last">最新价</span><span class="col-chg">涨跌额</span><span class="col-chgp">涨跌幅</span>
      <span class="col-vol">成交量</span><span class="col-amt">成交额</span><span class="col-cap">总市值</span><span class="col-tag"></span>
    </div>
    {'\n    '.join(rows)}
  </div>
  </div>'''

# ============================================================
# BUILD COMMODITY/FX ROW
# ============================================================
def build_cfx_row(commodities):
    cfx_configs = [
        ('gold',   'XAU/USD',  'https://www.futunn.com/currency/XAUUSD-FX'),
        ('wti',    'WTI 原油', 'https://www.futunn.com/futures/CLMAIN-US'),
        ('brent',  '布伦特',   'https://www.futunn.com/futures/BZMAIN-US'),
        ('usdcny', 'USD/CNY',  'https://www.futunn.com/currency/USDCNH-FX'),
    ]
    items = []
    for key, label, href in cfx_configs:
        item = commodities.get(key, {})
        p = item.get('price', 0)
        c = item.get('change', 0)
        cp = item.get('chg_pct', 0)
        chgp_str = fmt_percent(cp)
        
        if key == 'usdcny':
            # USD/CNY: 4 decimal places (forex convention), standard red-up/green-down
            usd_price = f"{p:.4f}"
            usd_chg = f"{'+' if c >= 0 else ''}{c:.4f}"
            is_up = c >= 0
            p_cls = "up" if is_up else "down"
            item_html = f'''<a class="cfx-item" href="{href}" target="_blank" style="text-decoration:none;color:var(--text);">
      <div class="l">{label}</div>
      <div class="p {p_cls}">{usd_price}</div>
      <div class="c {p_cls}">{usd_chg} <span style="color:var(--dim);font-weight:400;font-size:10px;">{chgp_str}</span></div>
    </a>'''
        else:
            price_str = fmt_price(p)
            change_str = f"{'+' if c >= 0 else ''}{c:.2f}" if c else "0.00"
            is_up = c >= 0 if c is not None else True
            p_cls = "up" if is_up else "down"
            item_html = f'''<a class="cfx-item" href="{href}" target="_blank" style="text-decoration:none;color:var(--text);">
      <div class="l">{label}</div>
      <div class="p {p_cls}">{price_str}</div>
      <div class="c {p_cls}">{change_str} <span style="color:var(--dim);font-weight:400;font-size:10px;">{chgp_str}</span></div>
    </a>'''
        items.append(item_html)
    return '<div class="cfx-grid">\n    ' + '\n    '.join(items) + '\n  </div>'

# ============================================================
# MAIN BUILD
# ============================================================
def build_report(date_str, template_path, output_path, data_json=None):
    from datetime import datetime
    
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except:
        dt = datetime.now()
    
    weekdays_cn = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday_cn = weekdays_cn[dt.weekday()]
    date_display = f"{dt.year}.{dt.month:02d}.{dt.day:02d} {weekday_cn}"
    
    report_data = data_json or {}
    
    # ============================================================
    # FETCH sparkline data
    # ============================================================
    a_share_codes = {
        'SH': 'sh000001',
        'SZ': 'sz399001',
        'CY': 'sz399006',
    }
    
    a_share_data = {}
    for key, code in a_share_codes.items():
        data = fetch_minute_data(code)
        if data:
            a_share_data[key] = data
            print(f"  {key}: {len(data)} data points (live)")
        else:
            print(f"  {key}: no live data, synthetic fallback")
    
    us_etf_map = {'SPX': 'SPY', 'NDX': 'QQQ', 'DJI': 'DIA'}
    us_ohlc = {}
    for key, etf in us_etf_map.items():
        quote = fetch_finnhub_quote(etf)
        if quote and 'o' in quote:
            us_ohlc[key] = quote
            print(f"  {key}: OHLC from Finnhub ({etf})")
        else:
            print(f"  {key}: Finnhub OHLC unavailable")
    
    vix_quote = fetch_finnhub_quote('VIXY')
    if vix_quote:
        us_ohlc['VIX'] = vix_quote
    
    # Generate sparklines
    sparklines = {}
    sw, sh = 80, 32
    
    for key in ['SH', 'SZ', 'CY']:
        if key in a_share_data and a_share_data[key]:
            prices = a_share_data[key]
            sparklines[key] = gen_svg_path(prices, sw, sh)
            sparklines[f'{key}_color'] = '#FF4060' if prices[-1] >= prices[0] else '#00C853'
        else:
            idx_d = report_data.get('indices', {}).get(key, {})
            o = idx_d.get('open', 4000) or 4000
            h = idx_d.get('high', 4050) or 4050
            l = idx_d.get('low', 3950) or 3950
            c = idx_d.get('price', 4000) or 4000
            sparklines[key] = gen_synthetic_path(o, h, l, c, 60, sw, sh)
            sparklines[f'{key}_color'] = '#FF4060' if c >= o else '#00C853'
    
    for key in ['SPX', 'NDX', 'DJI']:
        ohlc = us_ohlc.get(key, {})
        if ohlc:
            o, h, l, c = ohlc['o'], ohlc['h'], ohlc['l'], ohlc['c']
        else:
            idx_d = report_data.get('indices', {}).get(key, {})
            price = idx_d.get('price', 5000) or 5000
            o = idx_d.get('open', price * 0.995) or price * 0.995
            h = idx_d.get('high', price * 1.005) or price * 1.005
            l = idx_d.get('low', price * 0.992) or price * 0.992
            c = price
        sparklines[key] = gen_synthetic_path(o, h, l, c, 60, sw, sh)
        sparklines[f'{key}_color'] = '#FF4060' if c >= o else '#00C853'
    
    ohlc = us_ohlc.get('VIX', {})
    if ohlc:
        o, h, l, c = ohlc['o'], ohlc['h'], ohlc['l'], ohlc['c']
    else:
        idx_d = report_data.get('indices', {}).get('VIX', {})
        c = idx_d.get('price', 14.5) or 14.5
        o = idx_d.get('open', c * 0.98) or c * 0.98
        h = idx_d.get('high', c * 1.05) or c * 1.05
        l = idx_d.get('low', c * 0.95) or c * 0.95
    sparklines['VIX'] = gen_synthetic_path(o, h, l, c, 60, sw, sh)
    sparklines['VIX_color'] = '#FF6900' if c >= o else '#00C853'
    
    # HK: 恒生科技 (synthetic from report_data)
    idx_d = report_data.get('indices', {}).get('HK', {})
    if idx_d:
        c = idx_d.get('price', 6800) or 6800
        o = idx_d.get('open', c * 0.995) or c * 0.995
        h = idx_d.get('high', c * 1.008) or c * 1.008
        l = idx_d.get('low', c * 0.992) or c * 0.992
    else:
        c, o, h, l = 6800, 6800, 6800, 6800
    sparklines['HK'] = gen_synthetic_path(o, h, l, c, 60, sw, sh)
    sparklines['HK_color'] = '#FF4060' if c >= o else '#00C853'
    
    # ============================================================
    # READ TEMPLATE
    # ============================================================
    with open(template_path, 'r') as f:
        html = f.read()
    
    # ============================================================
    # REPLACE sections using positional markers
    # ============================================================
    
    # 1. Header date
    html = re.sub(
        r'<div class="date">[^<]+</div>',
        f'<div class="date">{date_display}</div>',
        html
    )
    status = report_data.get('status', '市场等待中')
    html = re.sub(
        r'<span class="status">[^<]+</span>',
        f'<span class="status">{status}</span>',
        html
    )
    
    # 2. Index row - replace entire block
    idx_row_html = build_idx_row(report_data, sparklines)
    html = re.sub(
        r'<div class="idx-row">.*?(?=<!-- STANCE -->)',
        idx_row_html + '\n\n  <!-- STANCE -->',
        html,
        flags=re.DOTALL
    )
    
    # 3. Stance
    stance_cn = report_data.get('stance_cn', '保守买入 50%')
    stance_us = report_data.get('stance_us', '激进买入 60%')
    stance_cn_pct = report_data.get('stance_cn_pct', 50)
    stance_us_pct = report_data.get('stance_us_pct', 60)
    sc = report_data.get('stance_cn_color', 'var(--orange)')
    su = report_data.get('stance_us_color', 'var(--green)')
    
    new_stance = f'''<div class="stance-bar">
    <div class="stance-item">
      <div class="info"><div class="lbl">A股立场</div><div class="val" style="color:{sc};">{stance_cn}</div></div>
      <div class="mbar"><div class="fill" style="width:{stance_cn_pct}%;background:{sc};"></div></div>
    </div>
    <div class="stance-item">
      <div class="info"><div class="lbl">美股立场</div><div class="val" style="color:{su};">{stance_us}</div></div>
      <div class="mbar"><div class="fill" style="width:{stance_us_pct}%;background:{su};"></div></div>
    </div>
  </div>'''
    html = _replace_tag(html, 'stance-bar', new_stance)
    
    # 4. Insight
    insight_text = report_data.get('insight', '暂无核心观点')
    new_insight = f'''<div class="insight">
    <span class="label">核心观点</span>
    <span>{insight_text}</span>
  </div>'''
    html = _replace_tag(html, 'insight', new_insight)
    
    # 5. Tier tables
    tiers = report_data.get('tiers', [])
    tier_cfgs = [
        {'tag': '5%收益目标', 'cls': 'tier-sub-h', 'tb_cls': 'tb-high'},
        {'tag': '爆发力最强', 'cls': 'tier-sub-m', 'tb_cls': 'tb-mid'},
        {'tag': '超卖反弹机会', 'cls': 'tier-sub-l', 'tb_cls': 'tb-low'},
    ]
    
    for i, tc in enumerate(tier_cfgs):
        tier_data = tiers[i] if i < len(tiers) else None
        if not tier_data:
            continue
        new_table = build_tier_table(tier_data, tc['tb_cls'])
        
        # Find i-th table-wrap by counting nesting
        count = 0
        pos = 0
        while True:
            pattern = '<div class="table-wrap">'
            start = html.find(pattern, pos)
            if start < 0:
                break
            if count == i:
                end = _find_closing_tag(html, start, 'div')
                if end > start:
                    html = html[:start] + new_table + html[end:]
                    print(f"  Tier {i+1}: table replaced ({len(tier_data.get('stocks', []))} stocks)")
                break
            pos = _find_closing_tag(html, start, 'div')
            count += 1
    
        # 6. Commodity/FX
    commodities = report_data.get('commodities', {})
    if commodities:
        new_cfx = build_cfx_row(commodities)
        html = _replace_tag(html, 'cfx-grid', new_cfx)
        print(f"  Commodities: replaced")
    
    # 7. Analysis text
    analysis_text = report_data.get('analysis', '')
    if analysis_text:
        new_analysis = f'''<div class="analysis">
    <div class="a-label">📊 商品与汇率分析</div>
    <div class="a-body">
      {analysis_text}
    </div>
  </div>'''
        html = _replace_tag(html, 'analysis', new_analysis)
        print(f"  Analysis: replaced")
    
    # 8. Risk items
    risks = report_data.get('risks', [])
    if risks:
        risk_items = ''
        for r in risks[:5]:
            title = r.get('title', '风险')
            desc = r.get('desc', '')
            risk_items += f'''<li class="risk-item">
      <div class="r-dot"></div>
      <div class="r-text"><strong>{title}</strong> — {desc}</div>
    </li>\n    '''
        new_risk = f'<ul class="risk-list">\n    {risk_items}</ul>'
        html = _replace_tag(html, 'risk-list', new_risk, tag='ul')
        print(f"  Risks: replaced ({len(risks)} items)")
    
    # 9. Events
    events = report_data.get('events', [])
    if events:
        ev_html = ''
        for ev in events[:8]:
            d = ev.get('date', '')
            e = ev.get('event', '')
            ev_html += f'<div class="ev-item"><div class="d">{d}</div><div class="e">{e}</div></div>\n    '
        new_ev = f'<div class="events">\n    {ev_html}</div>'
        html = _replace_tag(html, 'events', new_ev)
        print(f"  Events: replaced ({len(events)} items)")
    
    # ============================================================
    # WRITE OUTPUT
    # ============================================================
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tmp_path = output_path + '.tmp'
    with open(tmp_path, 'w') as f:
        f.write(html)
    os.replace(tmp_path, output_path)
    
    filesize = os.path.getsize(output_path)
    print(f"\n✅ Report written to {output_path} ({filesize:,} bytes)")
    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build daily momentum report HTML')
    parser.add_argument('--date', required=True, help='Report date (YYYY-MM-DD)')
    parser.add_argument('--template', default=TEMPLATE_DEFAULT, help='Template HTML path')
    parser.add_argument('--output', help='Output HTML path')
    parser.add_argument('--data', help='JSON data file path (optional)')
    parser.add_argument('--set-env', help='Set FINNHUB_TOKEN environment variable')
    
    args = parser.parse_args()
    
    if args.set_env:
        os.environ['FINNHUB_TOKEN'] = args.set_env
        globals()['FINNHUB_TOKEN'] = args.set_env
    
    if not args.output:
        args.output = OUTPUT_DEFAULT.format(date=args.date)
    
    data = None
    if args.data and os.path.exists(args.data):
        with open(args.data, 'r') as f:
            data = json.load(f)
        print(f"Loaded data from {args.data}")
    
    build_report(args.date, args.template, args.output, data)
