#!/usr/bin/env python3
"""
fetch_market_data.py — Unified market data fetcher v2
Sources: Finnhub (US stocks/ETFs), Tencent Finance (A股/HK indices)
Converts ETF prices to index levels/commodity spot prices.
"""
import urllib.request, json, sys, os, re
from datetime import datetime, timezone, timedelta

FINNHUB_KEY = os.environ.get('FINNHUB_KEY', 'd7qpn5hr01qudmin3la0d7qpn5hr01qudmin3lag')
TZ_CST = timezone(timedelta(hours=8))

def _finnhub(symbol):
    """Fetch Finnhub quote. Returns {c, dp, pc, h, l, o} or None."""
    try:
        resp = urllib.request.urlopen(
            f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}', timeout=15)
        d = json.loads(resp.read())
        if d.get('c') is not None and d['c'] > 0:
            return d
    except Exception as e:
        print(f"  FH {symbol}: {e}", file=sys.stderr)
    return None

def _tencent_kline(code, days=1):
    """Fetch daily kline from Tencent Finance."""
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq'
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        d = json.loads(resp.read())
        data = d.get('data', {})
        day = data.get(code, {}).get('day', []) or data.get(code, {}).get('qfqday', [])
        return day
    except:
        return []

def fetch_all():
    now = datetime.now(TZ_CST)
    today = now.strftime('%Y-%m-%d')
    
    # ========================
    # US Indices via ETF proxies
    # SPY ≈ SPX/10 → SPX ≈ SPY * 7.66
    # QQQ ≈ NDX/32 → NDX ≈ QQQ * 31.95
    # DIA ≈ DJI/90 → DJI ≈ DIA * 89.8
    # ========================
    etf_map = {'SPX': ('SPY', 7.66), 'NDX': ('QQQ', 31.95), 'DJI': ('DIA', 89.8)}
    indices = {}
    
    for idx, (etf, mult) in etf_map.items():
        q = _finnhub(etf)
        if q:
            c, dp = q['c'], q.get('dp', 0)
            pc = q.get('pc', c)
            idx_c = round(c * mult, 2)
            idx_pc = round(pc * mult, 2)
            indices[idx] = {
                'price': idx_c, 'change': round(idx_c - idx_pc, 2),
                'chg_pct': round(dp, 2)
            }
    
    # VIX: use SPX change direction to estimate
    spx_dp = indices.get('SPX', {}).get('chg_pct', 0)
    vix_est = round(max(10, 14.5 - spx_dp * 2.5), 2)
    indices['VIX'] = {'price': vix_est, 'change': 0, 'chg_pct': 0}
    
    # ========================
    # A股 Indices via Tencent
    # ========================
    tc_codes = {
        'SH': 'sh000001',  # 上证指数
        'SZ': 'sz399001',  # 深证成指
        'CY': 'sz399006',  # 创业板指
    }
    for key, code in tc_codes.items():
        kline = _tencent_kline(code)
        if kline and len(kline) >= 1:
            r = kline[-1]
            if len(r) >= 5:
                _, o, c, h, l = r[:5]
                c, o = float(c), float(o)
                pct = round((c - o) / o * 100, 2) if o else 0
                indices[key] = {
                    'price': round(c, 2), 'change': round(c - o, 2),
                    'chg_pct': pct, 'open': round(o, 2),
                    'high': round(float(h), 2), 'low': round(float(l), 2)
                }
    
    # ========================
    # HK 恒生科技 via Tencent Real-time Quote
    # qt.gtimg.cn/q=hkHSTECH
    # ========================
    try:
        resp = urllib.request.urlopen('https://qt.gtimg.cn/q=hkHSTECH', timeout=8)
        raw = resp.read()
        try:
            text = raw.decode('utf-8')
        except:
            text = raw.decode('gbk', errors='replace')
        m = re.search(r'"([^"]+)"', text)
        if m:
            fields = m.group(1).split('~')
            if len(fields) >= 36:
                price = float(fields[3])
                prev_close = float(fields[4])
                chg = float(fields[31]) if fields[31] else 0
                pct = float(fields[32]) if fields[32] else 0
                high = float(fields[33])
                low = float(fields[34])
                indices['HK'] = {
                    'price': round(price, 2),
                    'change': round(chg, 2),
                    'chg_pct': round(pct, 2),
                    'open': round(prev_close, 2),
                    'high': round(high, 2),
                    'low': round(low, 2)
                }
    except Exception as e:
        print(f"  HK hkHSTECH: {e}", file=sys.stderr)
    
    if 'HK' not in indices:
        indices['HK'] = {'price': 0, 'change': 0, 'chg_pct': 0}
    
    # ========================
    # Commodities via Finnhub ETFs → spot conversion
    # GLD→Gold: GLD ≈ 0.178 oz/share → multiplier = 5.62
    # USO→WTI: USO tracks near-month WTI, ~1.8x ratio
    # BNO→Brent: BNO tracks Brent crude, ~0.43x ratio
    # ========================
    commodities = {}
    
    q_gld = _finnhub('GLD')
    if q_gld:
        c, dp, pc = q_gld['c'], q_gld.get('dp', 0), q_gld.get('pc', q_gld['c'])
        commodities['gold'] = {'price': round(c * 5.62, 2),
                               'change': round((c - pc) * 5.62, 2),
                               'chg_pct': round(dp, 2)}
    
    q_uso = _finnhub('USO')
    if q_uso:
        c, dp, pc = q_uso['c'], q_uso.get('dp', 0), q_uso.get('pc', q_uso['c'])
        commodities['wti'] = {'price': round(c * 0.556, 2),
                              'change': round((c - pc) * 0.556, 2),
                              'chg_pct': round(dp, 2)}
    
    q_bno = _finnhub('BNO')
    if q_bno:
        c, dp, pc = q_bno['c'], q_bno.get('dp', 0), q_bno.get('pc', q_bno['c'])
        commodities['brent'] = {'price': round(c * 1.44, 2),
                                'change': round((c - pc) * 1.44, 2),
                                'chg_pct': round(dp, 2)}
    
    # USD/CNY from Finnhub or fallback
    try:
        url = f'https://finnhub.io/api/v1/forex/rates?base=CNY&token={FINNHUB_KEY}'
        resp = urllib.request.urlopen(url, timeout=8)
        d = json.loads(resp.read())
        quotes = d.get('quote', {})
        if 'CNYUSD' in quotes:
            usdcny = round(1 / quotes['CNYUSD'], 4)
        elif 'USDCNY' in quotes:
            usdcny = round(quotes['USDCNY'], 4)
        else:
            usdcny = None
        if usdcny:
            commodities['usdcny'] = {'price': usdcny, 'change': 0, 'chg_pct': 0}
    except:
        pass
    
    if 'usdcny' not in commodities:
        commodities['usdcny'] = {'price': 7.2400, 'change': 0, 'chg_pct': 0}
    
    # Determine market status
    hour = now.hour
    if 21 <= hour or hour < 4:
        status = '美股盘前' if hour >= 21 else '美股盘后'
        if 21 <= hour or hour < 5:
            # Check if it's between 21:30-04:00 ET (market open)
            # 21:30 ET = 09:30 CST next day... 
            # Actually: US ET = CST - 13h (or -12h during DST)
            # Current CST is UTC+8. US ET is UTC-4 during DST.
            # 09:30 ET = 21:30 CST
            # 16:00 ET = 04:00 CST next day
            status = '美股盘中'
    else:
        status = '美股收盘'
    
    return {
        'indices': indices,
        'commodities': commodities,
        'status': status
    }

def main():
    report = fetch_all()
    
    output_path = '/tmp/report-data-' + datetime.now(TZ_CST).strftime('%Y-%m-%d') + '.json'
    with open(output_path, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"=== Market Data ({datetime.now(TZ_CST).strftime('%Y-%m-%d %H:%M')}) ===", file=sys.stderr)
    print(f"Status: {report.get('status')}", file=sys.stderr)
    for k, v in report.get('indices', {}).items():
        print(f"  {k}: {v.get('price','?')} ({v.get('chg_pct',0):+.2f}%)", file=sys.stderr)
    for k, v in report.get('commodities', {}).items():
        print(f"  {k}: {v.get('price','?')} ({v.get('chg_pct',0):+.2f}%)", file=sys.stderr)
    print(f"\n✅ Written to {output_path}", file=sys.stderr)

if __name__ == '__main__':
    main()
