#!/usr/bin/env python3
"""
fetch_market_data.py — v3 直接报价版
主源：东方财富 (US股/指数/ETF) + 腾讯财经 (A股指数/港股) + Swissquote (商品/外汇)
后备：Finnhub (仅当不可达时，用于 DXY / WTI)

商品/外汇统一使用直接报价源，无 ETF 换算。
"""
import urllib.request, json, os, sys, ssl, re
from datetime import datetime, timezone, timedelta

# ============================================================
# FUTUNN PRIMARY — headless browser for real-time items
# ============================================================
def futunn_fetch(url):
    """Open futunn page with Playwright, return body text."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
            )
            page = ctx.new_page()
            page.goto(url, timeout=25000, wait_until='load')
            page.wait_for_timeout(3000)
            text = page.evaluate('() => document.body.innerText')
            browser.close()
            return text
    except Exception as e:
        print(f'  ⚠  futunn browser failed: {e}', file=sys.stderr)
        return None

def futunn_parse(text):
    """Extract (price, change, chg_pct) from futunn page text."""
    if not text:
        return None, None, None
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    for i, line in enumerate(lines):
        if re.match(r'^[\d,]+\.?\d*$', line):
            next_text = lines[i+1] if i+1 < len(lines) else ''
            m = re.match(r'^([+-]?[\d,.]+)\s*([+-]?[\d.]+%)?\s*$', next_text)
            change_val = float(m.group(1).replace(',', '')) if m else None
            chg_pct_val = float(m.group(2).replace('%', '')) if m and m.group(2) else None
            price_val = float(line.replace(',', ''))
            return price_val, change_val, chg_pct_val
    return None, None, None

TZ_CST = timezone(timedelta(hours=8))
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

def em_get(secid):
    """Fetch from EastMoney push2 API."""
    url = f'https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f169,f170,f171,f172'
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            'Referer': 'https://quote.eastmoney.com/'
        })
        return json.loads(urllib.request.urlopen(req, timeout=10).read()).get('data')
    except: return None

def tenc_get(symbol):
    """Fetch from Tencent qt.gtimg.cn."""
    try:
        req = urllib.request.Request(f'https://qt.gtimg.cn/q={symbol}', headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=8).read()
        try: text = data.decode('utf-8')
        except: text = data.decode('gbk')
        for line in text.strip().split('\n'):
            if '=' in line:
                p = line.strip().split('=')[1].strip('"').split('~')
                if len(p) > 3: return p
    except: pass
    return None

def oilprice_get(label):
    """Parse WTI/Brent price from oilprice.com HTML.
    Format on page: '<td>WTI Crude<span>•</span><span>11 mins</span></td><td>104.8<i></td><td>-1.59</td><td>-1.49%</td>'
    Returns {price, change, chg_pct, prev_close, source} or None."""
    try:
        url = 'https://oilprice.com/futures/wti/'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})
        resp = urllib.request.urlopen(req, timeout=10)
        html = resp.read().decode('utf-8', errors='replace')
        text = re.sub(r'<[^>]+>', ' ', html)
        # Replace whitespace runs with single space
        text = re.sub(r'\s+', ' ', text)
        # Try compact format first: "WTI Crude • 11 mins 104.8 -1.59 -1.49%"
        m = re.search(rf'{re.escape(label)} Crude.*?mins\s+([0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)%', text)
        if not m:
            # Try line-by-line: WTI Crude text followed by numbers on separate lines
            # Replace <br> and </td> with newlines for line-by-line approach
            text2 = re.sub(r'<[^>]+>', '\n', html)
            lines = [l.strip() for l in text2.split('\n') if l.strip()]
            for i, line in enumerate(lines):
                if f'{label} Crude' in line or line == label and i+4 < len(lines):
                    # Look for price within next 8 lines
                    for j in range(i, min(i+8, len(lines))):
                        try:
                            val = float(lines[j])
                            if val > 10 and i+1 < len(lines):
                                m = re.match(r'^([-0-9.]+)$', lines[j])
                                if m:
                                    price = float(lines[j])
                                    change_str = lines[j+1] if j+1 < len(lines) else '0'
                                    pct_str = lines[j+2] if j+2 < len(lines) else '0%'
                                    change = float(re.sub(r'[^0-9.-]', '', change_str))
                                    chg_pct = float(re.sub(r'[^0-9.-]', '', pct_str.replace('%','')))
                                    return {'price': price, 'change': change, 'chg_pct': chg_pct,
                                            'prev_close': round(price - change, 2), 'source': 'oilprice.com'}
                        except: pass
                    break
        else:
            price = float(m.group(1))
            change = float(m.group(2))
            chg_pct = float(m.group(3))
            return {'price': price, 'change': change, 'chg_pct': chg_pct,
                    'prev_close': round(price - change, 2), 'source': 'oilprice.com'}
    except Exception as e:
        import sys; print(f'  oilprice_get({label}) failed: {e}', file=sys.stderr)
    return None


def finnhub_get(symbol):
    """Finnhub fallback (US stocks, indices not available from Chinese sources)."""
    key = os.environ.get('FINNHUB_KEY', 'd7qpn5hr01qudmin3la0d7qpn5hr01qudmin3lag')
    try:
        d = json.loads(urllib.request.urlopen(
            f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={key}', timeout=10).read())
        if d.get('c') and d['c'] > 0:
            return {'price': d['c'], 'prev_close': d.get('pc', d['c']),
                    'high': d.get('h'), 'low': d.get('l')}
    except: pass
    return None


def sq_get(inst):
    """Fetch from Swissquote public quotes.
    Works for: XAU/USD, XAG/USD, LCO/USD (Brent), USD/CNH, EUR/USD, etc.
    No API key needed.
    Returns {price (mid), bid, ask, source} or None."""
    try:
        url = f'https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/{inst}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10, context=SSL_CTX)
        data = json.loads(resp.read().decode('utf-8'))
        if data and len(data) > 0:
            spp = data[0].get('spreadProfilePrices', [])
            if spp and len(spp) > 0:
                bid = float(spp[0].get('bid', 0))
                ask = float(spp[0].get('ask', 0))
                mid = round((bid + ask) / 2, 2)
                return {'price': mid, 'bid': bid, 'ask': ask,
                        'change': 0.0, 'chg_pct': 0.0,
                        'prev_close': mid, 'source': 'Swissquote'}
    except: pass
    return None

# ============================================================
# STOCK CATALYTIC TAGS
# ============================================================
CATALYTIC_TAGS = {
    'NVDA': 'AI芯片龙头·Blackwell爆单',
    'AAPL': 'WWDC AI战略发布·超卖反弹',
    'MSFT': '云业务加速·OpenAI整合',
    'AMZN': 'AWS AI重构·广告高增',
    'AMD':  'MI300放量·先进封装',
    'TSLA': 'FSD入华审批·储能翻倍',
    'GOOGL': 'Gemini搜索·云计算追赶',
    'META': 'Llama 3开源·VR生态',
    'INTC': '代工订单复苏·18A工艺突破',
    'BA':   '737MAX复产·国防订单',
    'NIO':  '交付回暖·换电网络扩张',
    'PLTR': '国防AI订单·AIP落地',
}

# A-share ETF link suffix (SH for 510xxx, SZ for 159xxx) + catalytic reason, not fund name
ETF_META = {
    '510300': {'suffix': 'SH', 'tag': '核心资产底仓·高流动性'},
    '510050': {'suffix': 'SH', 'tag': '权重蓝筹底仓·红利属性'},
    '510500': {'suffix': 'SH', 'tag': '中小盘成长弹性·量化首选'},
    '159915': {'suffix': 'SZ', 'tag': '科技成长先锋·双创核心'},
    '159949': {'suffix': 'SZ', 'tag': '创业板龙头组合·赛道配置'},
    '512100': {'suffix': 'SH', 'tag': '小盘超额收益·宽基覆盖'},
}

def main():
    now = datetime.now(TZ_CST)
    print(f"=== Fetch Market Data v3 (Swissquote+EastMoney+Tencent) ===")
    print(f"Time: {now.strftime('%Y-%m-%d %H:%M')} CST")
    
    report = {
        'date': now.strftime('%Y-%m-%d'),
        'source': 'Swissquote + EastMoney + Tencent (Finnhub fallback)',
        'indices': {},
        'tiers': [],
        'commodities': {},
    }
    
    # ============== US INDICES (EastMoney) ==============
    print("\n--- US Indices (EastMoney) ---")
    for secid, key, label, div in [
        ("100.SPX", "SPX", "标普500", 100),
        ("100.NDX", "NDX", "纳指100", 100),
    ]:
        d = em_get(secid)
        if d and d.get('f43'):
            p = round(d['f43']/div, 2)
            pc = round(d.get('f60',0)/div, 2)
            report['indices'][key] = {'price': p, 'prev_close': pc,
                'change': round(p-pc, 2), 'chg_pct': round((p-pc)/pc*100, 2)}
            print(f"  {label}: {p} ({report['indices'][key]['chg_pct']:+.2f}%)")
    
    # DJI fallback (EastMoney doesn't have it)
    fh = finnhub_get('DIA')  # DIA → Dow ETF proxy
    if fh:
        # DIA to DJI multiplier: DIA≈DJI/100 (correct)
        report['indices']['DJI'] = {'price': round(fh['price'] * 100, 2),
            'prev_close': round(fh['prev_close'] * 100, 2),
            'source': 'Finnhub(DIA×100)'}
        dji_pct = round((fh['price']-fh['prev_close'])/fh['prev_close']*100, 2)
        report['indices']['DJI']['chg_pct'] = dji_pct
        print(f"  DJI: {report['indices']['DJI']['price']} ({dji_pct:+.2f}%) (Finnhub fallback)")
    
    # ============== A-SHARE INDICES (Tencent) ==============
    print("\n--- A-Share Indices (Tencent) ---")
    for sym, key, label in [
        ("sh000001", "SH", "上证指数"),
        ("sz399001", "SZ", "深证成指"),
        ("sz399006", "CY", "创业板指"),
    ]:
        d = tenc_get(sym)
        if d and len(d) > 32:
            report['indices'][key] = {'price': float(d[3]),
                'change': float(d[31]) if d[31] else 0,
                'chg_pct': float(d[32]) if d[32] else 0}
            print(f"  {label}: {d[3]} ({d[32]}%)")
    
    # ============== HK INDEX (Tencent) ==============
    print("\n--- HK Index (Tencent) ---")
    d = tenc_get('hkHSTECH')
    if d and len(d) > 32:
        report['indices']['HK'] = {'price': float(d[3]),
            'change': float(d[31]) if d[31] else 0,
            'chg_pct': float(d[32]) if d[32] else 0}
        print(f"  恒生科技: {d[3]} ({d[32]}%)")
    
    # ============== VIX (futunn primary, Finnhub fallback) ==============
    text = futunn_fetch('https://www.futunn.com/futures/VXMAIN-US')
    if text:
        p, ch, cp = futunn_parse(text)
        if p:
            report['indices']['VIX'] = {'price': round(p, 2),
                'change': round(ch, 2) if ch else 0,
                'chg_pct': round(cp, 2) if cp else 0,
                'source': 'futunn'}
            print(f"  VIX: {p} ({cp:+.2f}%, futunn)")
    if 'VIX' not in report['indices']:
        vix_fh = finnhub_get('VIXY')
        if vix_fh:
            report['indices']['VIX'] = {'price': round(vix_fh['price'], 2),
                'change': round(vix_fh.get('change', 0), 2),
                'chg_pct': round(vix_fh.get('chg_pct', 0), 2),
                'source': 'Finnhub(VIXY)'}
            print(f"  VIX: {vix_fh['price']} (Finnhub fallback)")
    
    # ============== US STOCKS (EastMoney) ==============
    tiers = {
        'high': [('NVDA',105), ('AAPL',105), ('MSFT',105), ('AMZN',105)],
        'mid':  [('AMD',105), ('TSLA',105), ('GOOGL',105), ('META',105)],
        'low':  [('INTC',105), ('BA',106), ('NIO',106), ('PLTR',105)],
    }
    tier_names = {'high':'高位动量', 'mid':'中位动量', 'low':'低位动量'}
    
    print("\n--- US Stocks (EastMoney) ---")
    for tier_key, stocks in tiers.items():
        tier_stocks = []
        for sym, mk in stocks:
            d = em_get(f'{mk}.{sym}')
            if d and d.get('f43'):
                p = d['f43']/1000; pc = d['f60']/1000; chg = round(p-pc, 2)
                chg_pct = round((p-pc)/pc*100, 2)
                s = {
                    'symbol': sym,
                    'name': d.get('f58',''),
                    'price': round(p, 2),
                    'prev_close': round(pc, 2),
                    'change': chg,
                    'chg_pct': chg_pct,
                    'open': round(d.get('f46',0)/1000, 2),
                    'high': round(d.get('f44',0)/1000, 2),
                    'low': round(d.get('f45',0)/1000, 2),
                    'volume': d.get('f47',0),
                    'amount': d.get('f48',0),
                    'market_cap': d.get('f116',0),
                }
                tier_stocks.append(s)
        # Add catalytic tag from static map
        for s in tier_stocks:
            sym = s['symbol']
            if sym in CATALYTIC_TAGS and not s.get('tag'):
                s['tag'] = CATALYTIC_TAGS[sym]
                print(f"  [{tier_key}] {sym:5s}: {p:.2f} ({chg_pct:+.2f}%)")
            else:
                print(f"  ❌ {sym}: no data")
        
        # Add 6 A-share ETFs to each tier
        etf_stocks = fetch_a_share_etfs()
        tier_stocks.extend(etf_stocks)
        report['tiers'].append({'label': tier_key, 'stocks': tier_stocks})
    
    # ============== COMMODITIES (direct quotes, no ETF conversion) ==============
    print("\n--- Commodities (futunn primary) ---")
    
    def store_cfx(key, price, change, chg_pct, src, dec=2):
        p = round(price, dec)
        ch = round(change, dec) if change is not None else 0
        cp = round(chg_pct, 2) if chg_pct is not None else 0
        report['commodities'][key] = {'price': p, 'change': ch, 'chg_pct': cp, 'source': src}
        print(f"  {key}: {p} ({ch:+.02f}%, {src})")
    
    # 1. XAU/USD Gold → futunn primary, Swissquote fallback
    text = futunn_fetch('https://www.futunn.com/currency/XAUUSD-FX')
    if text:
        p, ch, cp = futunn_parse(text)
        if p: store_cfx('gold', p, ch, cp, 'futunn', 2)
    if 'gold' not in report['commodities']:
        sq = sq_get('XAU/USD')
        if sq: store_cfx('gold', sq['price'], sq.get('change'), sq.get('chg_pct'), 'Swissquote', 2)
    
    # 2. USD/CNY → futunn primary, Swissquote fallback
    text = futunn_fetch('https://www.futunn.com/currency/USDCNH-FX')
    if text:
        p, ch, cp = futunn_parse(text)
        if p: store_cfx('usdcny', p, ch, cp, 'futunn', 4)
    if 'usdcny' not in report['commodities']:
        sq = sq_get('USD/CNH')
        if sq: store_cfx('usdcny', sq['price'], sq.get('change'), sq.get('chg_pct'), 'Swissquote', 4)
    
    # 3. WTI → futunn primary, oilprice.com fallback
    text = futunn_fetch('https://www.futunn.com/futures/CLMAIN-US')
    if text:
        p, ch, cp = futunn_parse(text)
        if p: store_cfx('wti', p, ch, cp, 'futunn', 2)
    if 'wti' not in report['commodities']:
        op = oilprice_get('WTI')
        if op: store_cfx('wti', op['price'], op.get('chg'), op.get('chg_pct'), 'oilprice.com', 2)
    
    # 4. Brent → futunn primary, Swissquote/oilprice fallback
    text = futunn_fetch('https://www.futunn.com/futures/BZMAIN-US')
    if text:
        p, ch, cp = futunn_parse(text)
        if p: store_cfx('brent', p, ch, cp, 'futunn', 2)
    if 'brent' not in report['commodities']:
        sq = sq_get('LCO/USD')
        if sq: store_cfx('brent', sq['price'], sq.get('change'), sq.get('chg_pct'), 'Swissquote', 2)
        else:
            op = oilprice_get('Brent')
            if op: store_cfx('brent', op['price'], op.get('chg'), op.get('chg_pct'), 'oilprice.com', 2)
    
    # 5. Silver + DXY (no futunn link specified, keep as-is)
    sq = sq_get('XAG/USD')
    if sq:
        report['commodities']['silver'] = {'price': sq['price'], 'source': 'Swissquote'}
        print(f"  silver: {sq['price']} (Swissquote)")
    fh = finnhub_get('DX-Y.NYB')
    if fh:
        report['commodities']['usd_idx'] = {'price': fh['price'],
            'prev_close': fh.get('prev_close', fh['price']), 'source': 'Finnhub'}
        print(f"  DXY: {fh['price']}")
    
    # ============== WRITE OUTPUT ==============
    output = f'/tmp/report-data-{now.strftime("%Y-%m-%d")}.json'
    with open(output, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Written to {output}")
    print(f"   Indices: {len(report['indices'])} items")
    print(f"   Tiers: {len(report['tiers'])} ({sum(len(t['stocks']) for t in report['tiers'])} total)")
    print(f"   Commodities: {len(report['commodities'])} items")
    # Source labels are per-item in report['commodities'][*]['source']
    
    return report

def fetch_a_share_etfs():
    """Fetch 6 A-share ETFs from EastMoney."""
    etfs = [
        (1, "510300", "沪深300ETF"),
        (1, "510050", "上证50ETF"),
        (1, "510500", "中证500ETF"),
        (0, "159915", "创业板ETF"),
        (0, "159949", "创业板50ETF"),
        (1, "512100", "中证1000ETF"),
    ]
    results = []
    for mk, code, name in etfs:
        d = em_get(f'{mk}.{code}')
        if d and d.get('f43'):
            meta = ETF_META.get(code, {'suffix': 'SH', 'tag': ''})
            p = d['f43']*0.001; pc = d['f60']*0.001
            results.append({
                'symbol': code, 'name': name,
                'href': f'https://www.futunn.com/stock/{code}-{meta["suffix"]}',
                'tag': meta['tag'],
                'price': round(p, 3), 'prev_close': round(pc, 3),
                'change': round(p-pc, 3), 'chg_pct': round((p-pc)/pc*100, 2),
                'volume': d.get('f47',0), 'amount': d.get('f48',0),
                'market_cap': d.get('f116',0),
            })
            print(f"  {name}: {p:.3f} ({((p-pc)/pc*100):.2f}%)")
        else:
            print(f"  ❌ {code}: no data")
    return results

if __name__ == '__main__':
    main()
