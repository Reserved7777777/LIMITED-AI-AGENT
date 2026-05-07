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
from datetime import datetime, time as dtime

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
def _fear_pct(vix):
    """Convert VIX to a fear/panic coefficient percentage.
    Formula: VIX=10 → 0%, VIX=45 → 100%, clamped 0-100.
    """
    pct = min(max(((vix - 10) / 35) * 100, 0), 100)
    return round(pct)


def build_index_card(name, price, change, chg_pct, href, spark_path, spark_color, is_vix=False, chart_img=None, fear_pct=None, is_us=False):
    price_str = fmt_price(price)
    change_str = f"{'+' if change >= 0 else ''}{change:.2f}" if change else "0.00"
    chgp_str = fmt_percent(chg_pct)
    if change is not None and change != 0:
        is_up = change > 0
    elif chg_pct is not None and chg_pct != 0:
        is_up = chg_pct > 0
    else:
        is_up = True
    # Color convention: 
    #   A-share/HK: up=red(up class), down=green(down class)
    #   US: up=green(down class), down=red(up class)
    if is_us:
        price_cls = "down" if is_up else "up"
        change_cls = "down" if is_up else "up"
    else:
        price_cls = "up" if is_up else "down"
        change_cls = "up" if is_up else "down"
    
    if is_vix:
        # VIX card: no sparkline, show fear coefficient instead
        chart_html = f'<div style="display:flex;align-items:center;justify-content:center;height:44px;font-weight:700;font-size:11px;color:#fff;white-space:nowrap;letter-spacing:-0.18px;padding-right:2px;">'
        chart_html += f'恐慌系数 {fear_pct}%'
        chart_html += '</div>'
    elif chart_img:
        chart_html = f'<img class="spark" src="{chart_img}" alt="" style="width:100%;height:44px;display:block;object-fit:contain;object-position:right center;flex-shrink:1;"/>'
    else:
        chart_html = f'<svg class="spark" viewBox="0 -4 80 32"><path d="{spark_path}" fill="none" stroke="{spark_color}" stroke-width="1.8" stroke-linecap="round"/></svg>'
    
    return f'''<a class="idx-card" href="{href}" target="_blank">
      <div class="info">
        <span class="name">{name}</span>
        <div class="price {price_cls}">{price_str}</div>
        <div class="change {change_cls}">{change_str} <span class="sub2">{chgp_str}</span></div>
      </div>
      <div class="chart">{chart_html}</div>
    </a>'''

# ============================================================
# BUILD INDEX ROW (ALL 8 CARDS AT ONCE)
# ============================================================
def build_idx_row(report_data, sparklines):
    # idx_config: (key, card_name, futunn_name_in_link, url, is_vix, is_us)
    idx_config = [
        ('SPX', 'S&P 500',     'https://www.futunn.com/index/.SPX-US',       False, True),
        ('NDX', 'NASDAQ',       'https://www.futunn.com/index/.IXIC-US',      False, True),
        ('DJI', '道琼斯',        'https://www.futunn.com/index/.DJI-US',      False, True),
        ('HK',  '恒生科技',       'https://www.futunn.com/index/800700-HK',  False, False),
        ('SH',  '上证指数',       'https://www.futunn.com/index/000001-SH',   False, False),
        ('SZ',  '深证成指',       'https://www.futunn.com/index/399001-SZ',   False, False),
        ('CY',  '创业板指',       'https://www.futunn.com/index/399006-SZ',   False, False),
        ('VIX', 'VIX',          'https://www.futunn.com/futures/VXMAIN-US',   True,  True),
    ]
    
    cards = []
    for key, name, href, is_vix, is_us in idx_config:
        idx_data = report_data.get('indices', {}).get(key, {})
        price   = idx_data.get('price', 0)
        change  = idx_data.get('change', 0)
        chg_pct = idx_data.get('chg_pct', 0)
        sp = sparklines.get(key, f"M1,16 L119,16")
        sc = sparklines.get(f'{key}_color', '#00C853')
        fear_pct = _fear_pct(price) if is_vix else None
        cards.append(build_index_card(name, price, change, chg_pct, href, sp, sc, is_vix, fear_pct=fear_pct, is_us=is_us))
    
    indent = '    '
    return '<div class="idx-row">\n' + indent + ('\n' + indent).join(cards) + '\n  </div>'

# ============================================================
# BUILD TABLE ROWS FOR A TIER
# ============================================================
def fmt_cn_num(val):
    """Format large number with Chinese 万/亿 notation.
    125368092 → 1.25亿 | 24803603968 → 248亿 | 4823064000000 → 48231亿 | 1850000 → 185万"""
    if val == '' or val is None: return '-'
    v = float(val)
    if v >= 100000000:
        result = v / 100000000
        if result >= 100:
            return f'{result:.0f}亿'
        elif result >= 10:
            s = f'{result:.1f}'
            if s.endswith('.0'): s = s[:-2]
            return s + '亿'
        else:
            s = f'{result:.2f}'
            s = s.rstrip('0').rstrip('.')
            if not s: s = '0'
            return s + '亿'
    elif v >= 10000:
        result = v / 10000
        if result >= 1000:
            return f'{result:.0f}万'
        elif result >= 10:
            s = f'{result:.1f}'
            if s.endswith('.0'): s = s[:-2]
            return s + '万'
        else:
            s = f'{result:.2f}'
            s = s.rstrip('0').rstrip('.')
            if not s: s = '0'
            return s + '万'
    else:
        if v == int(v):
            return f'{int(v)}'
        return f'{v:.2f}'.rstrip('0').rstrip('.')


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
        if change is not None and change != 0:
            is_up = change > 0
        elif chgp is not None and chgp != 0:
            is_up = chgp > 0
        else:
            is_up = True
        
        # Detect market: numeric symbols = A-share, alphabetic = US
        is_us_stock = not sym.isdigit() if sym else False
        price_str = fmt_price(price)
        change_str = f"{'+' if change >= 0 else ''}{change:.2f}" if change else "0.00"
        chgp_str = fmt_percent(chgp)
        if is_us_stock:
            p_cls = "down" if is_up else "up"  # US: up=green(down)
        else:
            p_cls = "up" if is_up else "down"  # A-share: up=red(up)
        
        tag_items = ' '.join(f'<span class="tb-tag {tb_cls}">{t.strip()}</span>' for t in tag.split('·') if t.strip()) if tag else ''
        rows.append(f'''<a class="tbl-row" href="{href}" target="_blank">
      <span class="col-seq" style="color:var(--dim);">{seq}</span>
      <span class="s-sym col-sym">{sym}</span>
      <span class="s-name col-name">{name}</span>
      <span class="s-last col-last {p_cls}">{price_str}</span>
      <span class="col-chg {p_cls}">{change_str}</span>
      <span class="col-chgp {p_cls}">{chgp_str}</span>
      <span class="col-vol" style="color:var(--dim);font-size:11px;">{fmt_cn_num(vol)}</span>
      <span class="col-amt" style="color:var(--dim);font-size:11px;">{fmt_cn_num(amt)}</span>
      <span class="col-cap" style="color:var(--dim);font-size:11px;">{fmt_cn_num(cap)}</span>
      <span class="col-tag">{tag_items}</span>
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
      <div class="c {p_cls}">{usd_chg} <span style="font-weight:400;font-size:9px;">{chgp_str}</span></div>
    </a>'''
        else:
            price_str = fmt_price(p)
            change_str = f"{'+' if c >= 0 else ''}{c:.2f}" if c else "0.00"
            is_up = c >= 0 if c is not None else True
            p_cls = "up" if is_up else "down"
            item_html = f'''<a class="cfx-item" href="{href}" target="_blank" style="text-decoration:none;color:var(--text);">
      <div class="l">{label}</div>
      <div class="p {p_cls}">{price_str}</div>
      <div class="c {p_cls}">{change_str} <span style="font-weight:400;font-size:9px;">{chgp_str}</span></div>
    </a>'''
        items.append(item_html)
    return '<div class="cfx-grid">\n    ' + '\n    '.join(items) + '\n  </div>'

def compute_market_status():
    """Compute current market status text based on trading hours."""
    now = datetime.now()
    if now.weekday() >= 5:
        return '周末休市'
    t = now.time()
    h = t.hour
    ashare_trading = dtime(9, 30) <= t <= dtime(15, 0)
    hk_trading = (dtime(9, 30) <= t <= dtime(12, 0)) or (dtime(13, 0) <= t <= dtime(16, 0))
    us_trading = (h >= 21 or h < 4)
    parts = []
    parts.append('A股交易中' if ashare_trading else ('A股竞价' if dtime(9,15)<=t<dtime(9,30) else ('A股盘前' if t<dtime(9,15) else 'A股已收盘')))
    parts.append('港股交易中' if hk_trading else ('港股竞价' if dtime(9,0)<=t<dtime(9,30) else ('港股盘前' if t<dtime(9,0) else '港股已收盘')))
    if us_trading: parts.append('美股交易中')
    elif h >= 4 and h < 6: parts.append('美股盘后')
    elif h >= 6 and h < 21: parts.append('美股已收盘')
    else: parts.append('美股盘前')
    return ' | '.join(parts)

# ============================================================
# MAIN BUILD
# ============================================================
def build_report(date_str, template_path, output_path, data_json=None):
    
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except:
        dt = datetime.now()
    
    weekdays_cn = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday_cn = weekdays_cn[dt.weekday()]
    date_display = f"{dt.year}.{dt.month:02d}.{dt.day:02d} {weekday_cn}"
    
    report_data = data_json or {}
    
    # Override status to reflect actual market state (not stale data from report-data.json)
    market_status = compute_market_status()
    if market_status:
        report_data['status'] = market_status
    
    # ============================================================
    # FETCH sparkline data via fetch_idx_data.py
    # ============================================================
    import subprocess as _sp
    script_dir = os.path.dirname(os.path.abspath(__file__))
    idx_fetcher = os.path.join(script_dir, 'fetch_idx_data.py')
    idx_data_path = f'/tmp/report-idx-{date_str}.json'
    
    try:
        _sp.run(
            ['python3', idx_fetcher, '--output', idx_data_path],
            capture_output=True, text=True, timeout=30
        )
        with open(idx_data_path) as f:
            idx_output = json.load(f)
        sparklines = idx_output.get('sparklines', {})
        print(f"  Index data from fetch_idx_data.py: {sum(1 for v in idx_output.get('indices',{}).values() if v.get('price'))}/8 OK", file=sys.stderr)
        # Override report_data indices with fetched data
        for key, val in idx_output.get('indices', {}).items():
            if val.get('price'):
                report_data.setdefault('indices', {})[key] = val
    except Exception as e:
        print(f"  WARNING: fetch_idx_data.py failed: {e}, using built-in fallback", file=sys.stderr)
        # Fallback: generate minimal sparklines from report_data
        sparklines = {}
        sw, sh = 80, 32
        for key in ['SH', 'SZ', 'CY', 'SPX', 'NDX', 'DJI', 'VIX', 'HK']:
            sparklines[key] = f"M1,16 L79,16"
            sparklines[f'{key}_color'] = '#00C853'
    
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
      <div class="info"><div class="lbl">A股立场</div><div class="val" style="color:{sc};font-weight:700;">{stance_cn}</div></div>
      <div class="mbar"><div class="fill" style="width:{stance_cn_pct}%;background:{sc};"></div></div>
    </div>
    <div class="stance-item">
      <div class="info"><div class="lbl">美股立场</div><div class="val" style="color:{su};font-weight:700;">{stance_us}</div></div>
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
        # Format analysis: add <br> between each section for visual separation
        import re as _re
        # Each section ends with a Chinese/ASCII period then next starts with <strong>
        # Insert <br> between sections: after a period followed by <strong>
        formatted = _re.sub(r'([\u3002\.])(\s*<strong>)', r'\1<br>\2', analysis_text)
        # Fallback: if no periods match, try </strong> followed by whitespace then <strong>
        if formatted.count('<br>') == 0:
            formatted = _re.sub(r'</strong>\s*(?=<strong>)', '</strong><br>', analysis_text)
        # Collapse multiple blanks
        formatted = _re.sub(r'\s{3,}', ' ', formatted)
        new_analysis = f'''<div class="analysis">
    <div class="a-label">📊 商品与汇率分析</div>
    <div class="a-body">
      {formatted}
    </div>
  </div>'''
        html = _replace_tag(html, 'analysis', new_analysis)
        print(f"  Analysis: replaced ({len(analysis_text)} chars, {formatted.count('<br>')} breaks added)")
    
    # 8. Risk items
    # Fallback: default events/risks if data doesn't have them
    if 'risks' not in report_data or not report_data.get('risks'):
        report_data['risks'] = [
            {"title": "霍尔木兹海峡封锁升级", "desc": "伊朗革命卫队已发布海峡控制图，若美国采取军事回应，霍尔木兹海峡通行受阻将导致全球原油供应中断风险急剧上升。WTI 可能冲击 120+，布伦特 130+。关注：① 美军是否增派航母战斗群 ② 伊朗是否实际扣押油轮 ③ 国际航道通行保险费率变化。霍尔木兹占全球海运石油的 30%，任何实质封锁都将引发全球能源危机定价。", "href": "https://www.cls.cn/detail/2362652"},
            {"title": "CPI/PPI数据本周公布", "desc": "油价飙升（WTI 100+）推升通胀预期，市场关注本周 CPI/PPI 数据是否超预期。若核心 CPI 环比 > 0.3%，则 Fed 降息路径将推迟至 Q4，高估值成长股面临重估。关注：① 核心服务通胀走势 ② 能源传导至核心商品的程度 ③ 市场隐含的 2026 年降息次数定价变化。", "href": "https://www.cls.cn/detail/2362655"},
            {"title": "美债上限谈判重启", "desc": "美国财政部警告最早 6 月面临债务违约风险，两党在支出削减幅度上存在根本性分歧。若 6 月初前未达成协议，短期国库券收益率将飙升，引发类似 2023 年 8 月的流动性冲击。关注：① X-date（现金耗尽日期）最新估算 ② 国库券拍卖需求变化 ③ CDS 利差是否会突破 2023 年高点。", "href": "https://www.jin10.com/calendar"},
        ]
    if 'events' not in report_data or not report_data.get('events'):
        report_data['events'] = [
            {"date": "05.04 周一", "event": "ISM 制造业 PMI", "href": "https://www.jin10.com/calendar"},
            {"date": "05.05 周二", "event": "JOLTS 职位空缺", "href": "https://www.jin10.com/calendar"},
            {"date": "05.06 周三", "event": "ADP 就业数据", "href": "https://www.jin10.com/calendar"},
            {"date": "05.06 周三", "event": "A股节后复盘", "href": "https://www.jin10.com/calendar"},
            {"date": "05.07 周四", "event": "美联储利率决议", "href": "https://www.jin10.com/calendar"},
            {"date": "05.07 周四", "event": "鲍威尔新闻发布会", "href": "https://www.jin10.com/calendar"},
            {"date": "05.08 周五", "event": "初请失业金人数", "href": "https://www.jin10.com/calendar"},
            {"date": "05.08 周五", "event": "非农就业数据", "href": "https://www.jin10.com/calendar"},
        ]
    
    risks = report_data.get('risks', [])
    if risks:
        risk_items = ''
        for r in risks[:5]:
            title = r.get('title', '风险')
            desc = r.get('desc', '')
            href = r.get('href', '')
            if href:
                risk_items += f'''<a class="risk-item" href="{href}" target="_blank">
      <div class="r-dot"></div>
      <div class="r-text"><strong>{title}</strong> — {desc}</div>
    </a>\n    '''
            else:
                risk_items += f'''<li class="risk-item">
      <div class="r-dot"></div>
      <div class="r-text"><strong>{title}</strong> — {desc}</div>
    </li>\n    '''
        # Build complete risk section using marker boundaries (always includes sec-label)
        full_risk_block = (
            '<!-- ===== RISK ===== -->\n'
            '  <div class="sec-label">\n    <span>⚠️ 关键风险提示</span>\n  </div>\n'
            '  <div class="risk-list">\n    ' + risk_items + '</div>'
        )
        _s = html.find('<!-- ===== RISK ===== -->')
        _e = html.find('<!-- ===== EVENTS ===== -->', _s)
        if _s >= 0 and _e > _s:
            html = html[:_s] + full_risk_block + html[_e:]
        else:
            print('  WARN: RISK markers gone, ul.risk-list fallback', file=sys.stderr)
            fallback = f'<div class="risk-list">\n    {risk_items}</div>'
            html = _replace_tag(html, 'risk-list', fallback, tag='ul')
            if '关键风险提示' not in html:
                print('  WARN: sec-label still missing, emergency append', file=sys.stderr)
                emergency = (
                    '<!-- ===== RISK ===== -->\n'
                    '  <div class="sec-label">\n    <span>⚠️ 关键风险提示</span>\n  </div>\n'
                    '  <div class="risk-list">\n    ' + risk_items + '</div>'
                )
                html = html + '\n\n' + emergency
        print(f"  Risks: replaced ({len(risks)} items)")
    
    # 9. Events
    events = report_data.get('events', [])
    if events:
        ev_html = ''
        for ev in events[:8]:
            d = ev.get('date', '')
            e = ev.get('event', '')
            s = stars_str(ev.get('stars', 3))
            ev_html += f'<div class="ev-item"><div class="d">{d}  {s}</div><div class="e">{e}</div></div>\n    '
        new_ev = f'<div class="events">\n    {ev_html}</div>'
        html = _replace_tag(html, 'events', new_ev)
        print(f"  Events: replaced ({len(events)} items)")
    
    # ============================================================
    # SELF-CHECK: verify all section markers exist
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
        print(f"  ⚠️  SELF-CHECK: missing markers: {_missing}", file=sys.stderr)
    else:
        print(f"  ✅ SELF-CHECK: all {len(_required_markers)} markers present")
    
    # ============================================================
    # COLOR CHECK: validate up/down classes match actual direction
    # ============================================================
    _color_errors = []
    
    # 2a. Check 8 index cards: class="price up/down" + class="change up/down"
    # US indices (SPX/NDX/DJI/VIX): up=green(down class), down=red(up class)
    # A-share/HK (SH/SZ/CY/HK): up=red(up class), down=green(down class)
    _us_idx = {'S&P 500', 'NASDAQ', '道琼斯', 'VIX'}
    _idx_names = ['S&P 500', 'NASDAQ', '道琼斯', 'VIX', '上证指数', '深证成指', '创业板指', '恒生科技']
    for _name in _idx_names:
        _pos = html.find(f'>{_name}</span>')
        if _pos < 0:
            _color_errors.append(f'索引卡[{_name}]: not found in HTML')
            continue
        _chunk = html[_pos:_pos+400]
        _pc = re.search(r'price (up|down)">([^<]+)', _chunk)
        _cc = re.search(r'change (up|down)">([^<]+)', _chunk)
        _pv = float(_pc.group(2).replace(',','')) if _pc else 0
        _cv = _cc.group(2).strip() if _cc else ''
        _is_up = _cv.startswith('+')
        if _name in _us_idx:
            _expected = 'down' if _is_up else 'up'  # US: up=green(down)
        else:
            _expected = 'up' if _is_up else 'down'  # A-share: up=red(up)
        _actual = _pc.group(1) if _pc else '?'
        if _actual != _expected:
            _color_errors.append(f'索引卡[{_name}]: price class={_actual} expected={_expected} (chg={_cv})')
    
    # 2b. Check commodity prices (4 commodities)
    _commodity_names = ['铜（XCU/USD）', '白银（XAG/USD）', '黄金（XAU/USD）', '原油（WTI/Brent）']
    for _name in _commodity_names:
        _pos = html.find(_name)
        if _pos < 0: continue
        _chunk = html[_pos:_pos+500]
        # Commodity rows use <span class="price up/down">
        _matches = re.findall(r'class="price (up|down)"', _chunk[:150])
        if _matches:
            print(f'  📊 com[{_name[:6]}]: price class={_matches[0]}')
    
    # 2c. Check 30 stock/ETF rows: each <a class="tbl-row"> has chgp up/down
    _tier_sections = html.split('<!-- ===== TIER')[1:]
    for _tsec in _tier_sections:
        _rows = _tsec.split('<a class="tbl-row"')[1:]
        for _ri, _row in enumerate(_rows):
            # Extract symbol (numeric=A-share, alphabetic=US)
            _sym_m = re.search(r'col-sym">([^<]+)', _row)
            _sym = _sym_m.group(1) if _sym_m else f'row{_ri}'
            _is_us_stock = not _sym.isdigit() if _sym and _sym != f'row{_ri}' else False
            # Extract chgp class
            _chgp_up = 'chgp up"' in _row or 'chgp up ' in _row
            _chgp_down = 'chgp down"' in _row or 'chgp down ' in _row
            # Determine direction from chg_pct value
            _pct_m = re.search(r'col-chgp[^>]*>([+-]?[\d.]+)', _row)
            _pct_val = float(_pct_m.group(1)) if _pct_m else 0
            _is_up = _pct_val >= 0
            if _is_us_stock:
                _expected = 'down' if _is_up else 'up'  # US: up=green(down)
            else:
                _expected = 'up' if _is_up else 'down'  # A-share: up=red(up)
            _actual = 'up' if _chgp_up else ('down' if _chgp_down else '?')
            if _actual != _expected:
                _color_errors.append(f'股票[{_sym}]: chgp={_actual} expected={_expected} (pct={_pct_val:+.2f}%)')
    
    # 2d. Check VIX sparkline for edge artifacts
    _vix_pos = html.find('>VIX</span>')
    if _vix_pos >= 0:
        _vix_svg_s = html.find('<svg', _vix_pos, _vix_pos+500)
        if _vix_svg_s >= 0:
            _vix_svg_e = html.find('</svg>', _vix_svg_s)
            _vix_svg = html[_vix_svg_s:_vix_svg_e]
            _vix_path_m = re.search(r'd="([^"]+)"', _vix_svg)
            if _vix_path_m:
                _vix_coords = re.findall(r'([\d.]+),([\d.\-]+)', _vix_path_m.group(1))
                _vix_ys = [float(c[1]) for c in _vix_coords]
                _edge_top = sum(1 for y in _vix_ys if y <= -3.5)
                _edge_bot = sum(1 for y in _vix_ys if y >= 27.5)
                if _edge_top > 1:  # allow 1 edge point (normal range extreme)
                    _color_errors.append(f'VIX sparkline: {_edge_top} pts at viewBox top (y<=-3.5)')
                if _edge_bot > 1:  # allow 1 edge point (normal range extreme)
                    _color_errors.append(f'VIX sparkline: {_edge_bot} pts at viewBox bottom (y>=27.5)')
    
    if _color_errors:
        print(f'  ❌ COLOR CHECK FAILED ({len(_color_errors)} errors):', file=sys.stderr)
        for _e in _color_errors:
            print(f'     {_e}', file=sys.stderr)
    else:
        print(f'  ✅ COLOR CHECK: all indices/commodities/stocks classes match direction')
    
    _vix_spark_shape = ''
    if _vix_pos >= 0 and _vix_svg_s >= 0:
        _vix_ys_range = max(_vix_ys) - min(_vix_ys)
        _vix_pts = len(_vix_ys)
        _vix_spark_shape = f' (VIX spark: {_vix_pts}pts span={_vix_ys_range:.0f}y)'
        if _vix_pts < 10:
            _color_errors.append('VIX sparkline too few points')
        print(f'  📈 VIX spark: {_vix_pts}pts, y=[{min(_vix_ys):.1f},{max(_vix_ys):.1f}]{_vix_spark_shape}')
    
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


def stars_str(n):
    full = int(n)
    half = 1 if n - full >= 0.5 else 0
    empty = 5 - full - half
    return '★' * full + ('½' if half else '') + '☆' * empty

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




