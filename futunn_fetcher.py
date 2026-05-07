#!/usr/bin/env python3
"""
futunn_fetcher.py — Fetch complete market data from futunn.com via Playwright
Produces JSON consumable by build_report.py.
"""
import json, os, sys, time, re
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

TZ_CST = timezone(timedelta(hours=8))

# US stocks to fetch (4 per tier for the evening report)
US_STOCKS = {
    'high': ['NVDA-US', 'AAPL-US', 'MSFT-US', 'AMZN-US'],
    'mid':  ['AMD-US', 'TSLA-US', 'GOOGL-US', 'META-US'],
    'low':  ['INTC-US', 'BA-US', 'NIO-US', 'PLTR-US'],
}

# A-share ETFs (6 per tier for the evening report — same 6 reused)
A_ETFS = [
    ('510300-SH', '华夏沪深300ETF', '华夏基金'),
    ('510050-SH', '华夏上证50ETF', '华夏基金'),
    ('510500-SH', '南方中证500ETF', '南方基金'),
    ('159915-SZ', '易方达创业板ETF', '易方达基金'),
    ('159949-SZ', '华安创业板50ETF', '华安基金'),
    ('512100-SH', '南方中证1000ETF', '南方基金'),
]

# Commodity proxies
COMMODITIES = ['GLD-US', 'USO-US', 'BNO-US']

def parse_detail(text):
    """Parse .detail-main text into structured dict."""
    text = re.sub(r'\s+', ' ', text).strip()
    d = {}
    
    if m := re.search(r'(\d+\.?\d*)', text): d['price'] = m.group(1)
    if m := re.search(r'([+-]\d+\.\d+)', text): d['change'] = m.group(1)
    if m := re.search(r'([+-]\d+\.\d+%)', text): d['chg_pct'] = m.group(1)
    if m := re.search(r'(交易中|盘前|盘后|休市中|已收盘)\s+\d{2}/\d{2}\s+(\d{2}:\d{2})', text): 
        d['status'] = m.group(1); d['time'] = m.group(2)
    if m := re.search(r'(\d+\.\d+)最高价', text): d['high'] = m.group(1)
    if m := re.search(r'(\d+\.\d+)最低价', text): d['low'] = m.group(1)
    if m := re.search(r'(\d+\.\d+)今开', text): d['open'] = m.group(1)
    if m := re.search(r'(\d+\.\d+)昨收', text): d['prev_close'] = m.group(1)
    if m := re.search(r'([\d.]+万?)股成交量', text): d['volume'] = m.group(1)
    if m := re.search(r'([\d.]+亿)成交额', text): d['amount'] = m.group(1)
    if m := re.search(r'([\d.]+万亿)总市值', text): d['market_cap'] = m.group(1)
    if m := re.search(r'([\d.]+)市盈率TTM', text): d['pe_ttm'] = m.group(1)
    
    # Convert price to float
    for k in ['price', 'change', 'high', 'low', 'open', 'prev_close']:
        if k in d:
            try: d[k] = round(float(d[k]), 2)
            except: pass
    if 'chg_pct' in d:
        try: d['chg_pct_num'] = round(float(d['chg_pct'].replace('%','')), 2)
        except: pass
    
    return d

def fetch_index_data(page):
    """Navigate to /quote and parse index data."""
    page.goto('https://www.futunn.com/quote', timeout=30000)
    page.wait_for_timeout(3000)
    
    text = page.evaluate("""
    () => {
        const links = document.querySelectorAll('a');
        const texts = [];
        links.forEach(a => {
            const t = a.textContent.replace(/\\s+/g, ' ').trim();
            if ((t.includes('道琼斯') || t.includes('纳斯达克') || t.includes('标普500')) && t.includes('%')) {
                texts.push(t);
            }
        });
        return texts;
    }
    """)
    
    indices = {}
    for t in text:
        # Pattern: name price_changepct  (all concatenated)
        m = re.match(r'(道琼斯|纳斯达克|标普500|恒生指数)([\d.,]+)([+-][\d.,]+)([+-][\d.]+%)', t)
        if m:
            name = m.group(1)
            name_map = {'道琼斯':'DJI', '纳斯达克':'NDX', '标普500':'SPX'}
            key = name_map.get(name, name)
            p = float(m.group(2).replace(',',''))
            c = float(m.group(3).replace(',',''))
            cp = float(m.group(4).replace('%',''))
            indices[key] = {'price': p, 'change': c, 'chg_pct': cp}
    
    return indices

def fetch_stock(page, symbol):
    """Fetch single stock data from futunn."""
    url = f'https://www.futunn.com/stock/{symbol}'
    try:
        page.goto(url, timeout=25000)
        page.wait_for_selector('.detail-main', timeout=10000)
        page.wait_for_timeout(500)
        text = page.eval_on_selector('.detail-main', 'el => el.textContent')
        return parse_detail(text)
    except Exception as e:
        return {'symbol': symbol, 'error': str(e)}

def main():
    now = datetime.now(TZ_CST)
    date_str = now.strftime('%Y-%m-%d')
    print(f"=== Futunn Fetcher ({date_str} {now.strftime('%H:%M')}) ===")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        page = ctx.new_page()
        
        result = {
            'date': date_str,
            'fetched_at': now.strftime('%H:%M'),
            'indices': {},
            'tiers': [],
            'commodities': {},
            'source': 'futunn.com'
        }
        
        # 1. Indices
        print("\n--- Indices ---")
        result['indices'] = fetch_index_data(page)
        for k, v in result['indices'].items():
            print(f"  {k}: {v['price']} ({v['chg_pct']:+.2f}%)")
        
        # 2. US Stocks by tier
        for tier_name, symbols in US_STOCKS.items():
            print(f"\n--- {tier_name} ---")
            tier_stocks = []
            for sym in symbols:
                data = fetch_stock(page, sym)
                data['symbol'] = sym.replace('-US','')
                tier_stocks.append(data)
                p = data.get('price','?')
                cp = data.get('chg_pct','?')
                print(f"  {sym}: {p} ({cp})")
            result['tiers'].append({'label': tier_name, 'stocks': tier_stocks})
        
        # 3. A-Share ETFs (add to middle tier as per spec)
        print("\n--- A-Share ETFs ---")
        etf_data = []
        for sym, name_en, fund in A_ETFS:
            data = fetch_stock(page, sym)
            data['symbol'] = sym.split('-')[0]
            data['etf_name'] = name_en
            data['fund_company'] = fund
            etf_data.append(data)
            p = data.get('price','?')
            print(f"  {sym} {name_en}: {p}")
        
        # 4. Commodities
        print("\n--- Commodities ---")
        for sym in COMMODITIES:
            data = fetch_stock(page, sym)
            key = sym.replace('-US','').lower()
            result['commodities'][key] = data
            p = data.get('price','?')
            print(f"  {sym}: {p}")
        
        browser.close()
    
    # Write output
    out = f'/tmp/futunn-data-{date_str}.json'
    with open(out, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Written to {out}")
    print(f"   Indices: {len(result['indices'])}")
    print(f"   Tiers: {len(result['tiers'])} ({sum(len(t['stocks']) for t in result['tiers'])} stocks)")
    print(f"   ETFs: {len(etf_data)}")
    print(f"   Commodities: {len(result['commodities'])}")
    return result

if __name__ == '__main__':
    main()
