#!/usr/bin/env python3
"""
指数数据获取器 - 从多个数据源获取8个指数卡的真实数据并生成分时图。

数据源：
  - US 指数 (SPX/NDX/DJI): Sina Finance API (需 Referer)
  - VIX: Finnhub VIXY ETF
  - A股指数 (SH/SZ/CY): 腾讯财经 minute + quote API
  - 恒生科技 (HK): 腾讯财经 minute + quote API

用法：
  python3 fetch_idx_data.py [--output PATH] [--date YYYY-MM-DD]

输出：
  JSON 包含 indices 数据 + sparkline paths + colors，可直接供 build_report.py 使用。
  
归档：
  每日收盘后自动保存到 idx_data/idx-YYYY-MM-DD.json
  latest.json 随时更新为最新可用数据
"""
import sys, json, os, urllib.request, time

# ============================================================
# CONFIG
# ============================================================
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'idx_data')
FINNHUB_TOKEN = 'd7qpn5hr01qudmin3la0d7qpn5hr01qudmin3lag'

# ============================================================
# HELPER: fetch with retries
# ============================================================
def _fetch(url, headers=None, timeout=10):
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req, timeout=timeout)
            raw = resp.read()
            try:
                return raw.decode('utf-8')
            except UnicodeDecodeError:
                return raw.decode('gbk', errors='replace')
        except Exception as e:
            if attempt == 0:
                time.sleep(1)
            else:
                return None

# ============================================================
# DATA SOURCES
# ============================================================

# --- Sina US indices ---
def fetch_us_indices_sina():
    """Fetch SPX, NDX, DJI from Sina Finance."""
    url = "https://hq.sinajs.cn/list=gb_$dji,gb_$ixic,gb_$inx"
    raw = _fetch(url, headers={'Referer': 'https://finance.sina.com.cn'})
    if not raw:
        return {}
    
    result = {}
    for line in raw.strip().split('\n'):
        if 'gb_' not in line:
            continue
        try:
            parts = line.split('"')[1].split(',')
            name = parts[0].strip()
            current = float(parts[1])
            chg_pct = float(parts[2])
            chg_amt = float(parts[4])
            open_p = float(parts[5])
            high_p = float(parts[6])
            low_p = float(parts[7])
            # prev_close computed from current price and change amount (most reliable)
            prev_close = round(current - chg_amt, 2)
            
            key_map = {'道琼斯': 'DJI', '纳斯达克': 'NDX', '标普500指数': 'SPX',
                       'S&P 500': 'SPX', 'NASDAQ': 'NDX', 'DJIA': 'DJI'}
            key = key_map.get(name, name)
            
            result[key] = {
                'price': round(current, 2),
                'change': round(chg_amt, 2),
                'chg_pct': round(chg_pct, 2),
                'open': round(open_p, 2),
                'high': round(high_p, 2),
                'low': round(low_p, 2),
                'prev_close': round(prev_close, 2) if prev_close else None,
                'source': 'sina'
            }
        except (IndexError, ValueError) as e:
            continue
    return result

# --- Sina A-share indices ---
def fetch_ashare_indices_sina():
    """Fetch SH, SZ, CY latest data from Sina Finance."""
    url = "https://hq.sinajs.cn/list=s_sh000001,s_sz399001,s_sz399006"
    raw = _fetch(url, headers={'Referer': 'https://finance.sina.com.cn'})
    if not raw:
        return {}
    
    result = {}
    for line in raw.strip().split('\n'):
        if 'hq_str_' not in line:
            continue
        try:
            parts = line.split('"')[1].split(',')
            name = parts[0]
            current = float(parts[1]) if parts[1] and float(parts[1]) != 0 else None
            chg_amt = float(parts[2]) if parts[2] else None
            chg_pct = float(parts[3]) if parts[3] else None
            
            key_map = {'上证指数': 'SH', '深证成指': 'SZ', '创业板指': 'CY'}
            key = key_map.get(name)
            if key and current:
                result[key] = {
                    'price': current,
                    'change': chg_amt,
                    'chg_pct': chg_pct,
                    'source': 'sina'
                }
        except (IndexError, ValueError):
            continue
    return result

# --- Tencent A-share minute + QT data ---
def fetch_ashare_indices_tencent():
    """Fetch intraday minute data + quote for SH, SZ, CY from Tencent API."""
    codes = {'SH': 'sh000001', 'SZ': 'sz399001', 'CY': 'sz399006'}
    result = {}
    for key, code in codes.items():
        url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data_{code}&code={code}"
        raw = _fetch(url)
        if not raw:
            continue
        try:
            obj = json.loads(raw.split('=', 1)[1])
            # Minute data
            data_list = obj.get('data', {}).get(code, {}).get('data', {}).get('data', [])
            prices = []
            if data_list and len(data_list) >= 5:
                prices = [float(p.split()[1]) for p in data_list if p.strip()]
            
            # Quote data
            qt = obj.get('data', {}).get(code, {}).get('qt', {}).get(code, [])
            entry = {}
            if qt and len(qt) > 32 and qt[3]:
                entry['price'] = round(float(qt[3]), 2)
                entry['prev_close'] = round(float(qt[4]), 2) if qt[4] else None
                entry['change'] = round(float(qt[31]), 2) if qt[31] else None
                entry['chg_pct'] = round(float(qt[32]), 2) if qt[32] else None
                entry['timestamp'] = qt[30]
                entry['source'] = 'tencent'
                entry['minute_prices'] = prices[:200]  # Limit to 200 points
            else:
                # Fallback: use minute data to compute
                if prices:
                    entry['price'] = round(prices[-1], 2)
                    entry['change'] = round(prices[-1] - prices[0], 2)
                    entry['chg_pct'] = round((prices[-1] - prices[0]) / prices[0] * 100, 2)
                    entry['prev_close'] = None
                    entry['source'] = 'tencent_minute'
                    entry['minute_prices'] = prices[:200]
            if entry.get('price'):
                result[key] = entry
        except Exception:
            continue
    return result

# --- Tencent HSTECH data ---
def fetch_hk_index_tencent():
    """Fetch 恒生科技 intraday minute data + quote from Tencent API."""
    url = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data_hkHSTECH&code=hkHSTECH"
    raw = _fetch(url)
    if not raw:
        return {}
    try:
        obj = json.loads(raw.split('=', 1)[1])
        data_list = obj.get('data', {}).get('hkHSTECH', {}).get('data', {}).get('data', [])
        prices = []
        if data_list and len(data_list) >= 5:
            prices = [float(p.split()[1]) for p in data_list if p.strip()]
        
        qt = obj.get('data', {}).get('hkHSTECH', {}).get('qt', {}).get('hkHSTECH', [])
        entry = {}
        if qt and len(qt) > 32 and qt[3]:
            entry['price'] = round(float(qt[3]), 2)
            entry['prev_close'] = round(float(qt[4]), 2) if qt[4] else None
            entry['change'] = round(float(qt[31]), 2) if qt[31] else None
            entry['chg_pct'] = round(float(qt[32]), 2) if qt[32] else None
            entry['timestamp'] = qt[30]
            entry['source'] = 'tencent'
            entry['minute_prices'] = prices[:200]
        if entry.get('price'):
            return {'HK': entry}
    except Exception:
        pass
    return {}

# --- Finnhub VIXY for VIX ---
def fetch_vix_finnhub():
    """Fetch VIX data via VIXY ETF from Finnhub."""
    url = f"https://finnhub.io/api/v1/quote?symbol=VIXY&token={FINNHUB_TOKEN}"
    raw = _fetch(url)
    if not raw:
        return {}
    try:
        q = json.loads(raw)
        if q.get('c'):
            c, o, h, l, pc = q['c'], q.get('o', 0), q.get('h', 0), q.get('l', 0), q.get('pc', 0)
            change = round(c - pc, 2)
            chg_pct = round((c - pc) / pc * 100, 2) if pc else 0
            return {'VIX': {
                'price': round(c, 2),
                'change': change,
                'chg_pct': chg_pct,
                'open': round(o, 2),
                'high': round(h, 2),
                'low': round(l, 2),
                'prev_close': round(pc, 2),
                'source': 'finnhub_vixy'
            }}
    except Exception:
        pass
    return {}

# --- Browser fallback for futunn index pages ---
def fetch_via_browser_futunn(futunn_url, index_key):
    """
    Browser fallback: open a futunn index page, extract price data via snapshot.
    Returns dict with price/change/chg_pct or None.
    
    Requires the host Chrome to have a logged-in futunn session.
    If login screen appears, returns None (skips silently), and the
    API pipeline (Sina/Tencent/Finnhub) serves as the fallback.
    """
    import subprocess as _sp, json as _json
    try:
        # Attempt 1: HTTP SSR data extraction (futunn sometimes embeds data in HTML)
        import urllib.request as _ur
        req = _ur.Request(futunn_url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,application/xhtml+xml'})
        resp = _ur.urlopen(req, timeout=10)
        body = resp.read().decode('utf-8', errors='replace')
        
        import re as _re
        price_matches = _re.findall(r'"price"\s*:\s*([\d.]+)', body)
        change_matches = _re.findall(r'"change"\s*:\s*([\d.-]+)', body)
        chgp_matches = _re.findall(r'"chgPct"\s*:\s*([\d.-]+)', body)
        if price_matches and change_matches:
            return {
                'price': round(float(price_matches[0]), 2),
                'change': round(float(change_matches[0]), 2),
                'chg_pct': round(float(chgp_matches[0]), 2) if chgp_matches else 0,
                'source': 'futunn_html'
            }
    except Exception:
        pass
    
    # Attempt 2: Browser-based monitoring.
    # futunn index pages are accessible without login via browser.
    # The browser snapshot data is saved by the AI assistant via browser tool.
    return None

def monitor_futunn_pages():
    """
    Load futunn browser snapshot data if available and recent.
    Auto-runs browser_monitor.py if snapshot is missing/stale,
    keeping index card data in sync with the report generation cycle.
    """
    import os as _os
    from datetime import datetime as _dt
    import subprocess as _sp
    
    snapshot_path = _os.path.join(ARCHIVE_DIR, 'browser_snapshot.json')
    script_dir = _os.path.dirname(_os.path.abspath(__file__))
    bm_path = _os.path.join(script_dir, 'browser_monitor.py')
    
    need_fresh = False
    if not _os.path.exists(snapshot_path):
        need_fresh = True
        print('  No browser snapshot, launching browser_monitor...', file=sys.stderr)
    else:
        try:
            with open(snapshot_path) as f:
                snap = json.load(f)
            if snap.get('date', '') != _dt.now().strftime('%Y-%m-%d'):
                need_fresh = True
                print('  Stale browser snapshot, refreshing...', file=sys.stderr)
        except Exception:
            need_fresh = True
    
    if need_fresh:
        try:
            r = _sp.run(['python3', bm_path], capture_output=True, text=True, timeout=80)
            if r.stdout:
                for line in r.stdout.strip().split('\n')[-5:]:
                    print('  ' + line, file=sys.stderr)
            if r.returncode != 0:
                print('  browser_monitor failed, fallback to API', file=sys.stderr)
                if r.stderr:
                    print('  ' + r.stderr.strip().split('\n')[-1], file=sys.stderr)
                return None
        except Exception as e:
            print('  browser_monitor error: ' + str(e) + ', fallback to API', file=sys.stderr)
            return None
    
    try:
        with open(snapshot_path) as f:
            snap = json.load(f)
        indices_data = {}
        for key, val in snap.get('indices', {}).items():
            if val.get('price'):
                indices_data[key] = val
        if len(indices_data) >= 6:
            print('  Using browser snapshot (' + str(len(indices_data)) + ' indices)', file=sys.stderr)
            return indices_data
    except Exception as e:
        print('  Browser snapshot error: ' + str(e), file=sys.stderr)
    
    return None

# ============================================================
# SPARKLINE GENERATION
# ============================================================
def gen_sparkline_svg(prices, width=80, height=32):
    """Generate SVG path from price array."""
    if not prices or len(prices) < 2:
        # Return flat line
        mid = height / 2
        return f"M1,{mid} L{width-1},{mid}"
    
    n = len(prices)
    min_p = min(prices)
    max_p = max(prices)
    rng = max_p - min_p
    if rng == 0:
        rng = 1
    
    # Downsample to fit width (about 2px per point)
    pts_needed = min(n, width // 2)
    step = max(1, n // pts_needed)
    sampled = prices[::step]
    if sampled[-1] != prices[-1]:
        with_append = sampled[:]
        with_append.append(prices[-1])
        sampled = with_append
    
    n2 = len(sampled)
    points = []
    for i, p in enumerate(sampled):
        x = round((i / (n2 - 1)) * (width - 4) + 2, 1) if n2 > 1 else width / 2
        y = round(height - 4 - ((p - min_p) / rng) * (height - 8), 1)
        points.append(f"{x},{y}")
    return "M" + " L".join(points)

def gen_sparkline_from_ohlc(open_p, high_p, low_p, close_p, points=40, width=80, height=32):
    """Generate synthetic sparkline path from OHLC with minimal noise."""
    prices = [open_p]
    for i in range(1, points - 1):
        progress = i / (points - 1)
        target = open_p + (close_p - open_p) * progress * 0.9  # slight curve toward close
        # Small noise ~10% of daily range
        rng = high_p - low_p if high_p > low_p else abs(close_p - open_p) * 0.02
        noise_amp = max(rng, 0.01) * 0.08
        import random as _r
        noise = (_r.random() - 0.5) * noise_amp
        prices.append(target + noise)
    prices.append(close_p)
    return gen_sparkline_svg(prices, width, height)

def get_sparkline_color(change, chg_pct, is_vix=False):
    """Determine sparkline stroke color."""
    if change is None and chg_pct is None:
        return '#00C853'
    delta = change if change else 0
    is_up = delta >= 0
    if is_vix:
        return '#FF6900' if is_up else '#00C853'
    return '#FF4060' if is_up else '#00C853'

# ============================================================
# MAIN FETCHER
# ============================================================
def fetch_all_indices():
    """Fetch all 8 index data.
    Strategy:
    - Closed markets (US): browser snapshot preferred (definitive close data)
    - Trading markets (A-share, HK): API pipeline (real-time + real minute data for sparklines)
    - Cross-validate: API sparklines always win over synthetic"""
    results = {}
    browser_data = monitor_futunn_pages()
    
    # A. Closed US markets: use browser snapshot as baseline
    if browser_data:
        for key in ['SPX', 'NDX', 'DJI', 'VIX']:
            if key in browser_data:
                val = browser_data[key]
                status = val.get('status', '')
                if '收盘' in status or val.get('market') == 'us':
                    results[key] = val
                    results[key]['source'] = 'futunn_browser'
    
    # B. Trading A-share markets: API pipeline (real-time + minute_prices for sparklines)
    tencent_ashare = fetch_ashare_indices_tencent()
    if tencent_ashare:
        results.update(tencent_ashare)
        print(f"  A-share (Tencent): {', '.join(tencent_ashare.keys())} OK", file=sys.stderr)
    else:
        sina_ashare = fetch_ashare_indices_sina()
        if sina_ashare:
            results.update(sina_ashare)
            print(f"  A-share (Sina fallback): {', '.join(sina_ashare.keys())} OK", file=sys.stderr)
    
    # C. Trading HK market: API pipeline
    hk = fetch_hk_index_tencent()
    if hk:
        results.update(hk)
        print(f"  HK (Tencent): OK", file=sys.stderr)
    
    # D. US indices from Sina API (provides correct OHLC for sparklines)
    us = fetch_us_indices_sina()
    if us:
        for key in us:
            if key not in results:
                results[key] = us[key]
            else:
                # Carry over open/high/low from Sina for accurate sparklines
                for field in ['open', 'high', 'low', 'prev_close']:
                    if us[key].get(field) is not None:
                        results[key][field] = us[key][field]
        print(f"  US indices (Sina): {', '.join(us.keys())} OK", file=sys.stderr)
    
    # E. VIX: browser snapshot provides VXMAIN futures, Finnhub provides .VIX spot
    # Prefer browser snapshot (VXMAIN is the actual displayed value on futunn)
    # Only fill if missing
    if 'VIX' not in results:
        vix = fetch_vix_finnhub()
        if vix:
            results.update(vix)
            print(f"  VIX (Finnhub fill): OK", file=sys.stderr)
    
    # F. Fill any remaining missing indices from browser snapshot
    if browser_data:
        for key in browser_data:
            if key not in results:
                results[key] = browser_data[key]
                print(f"  {key} (browser fill): OK", file=sys.stderr)
    
    return results

# ============================================================
# OUTPUT ASSEMBLY
# ============================================================
def assemble_output(index_data, date_str=None):
    """Build the output dict with index data + sparklines."""
    from datetime import datetime
    
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    # Index card configs
    idx_config = [
        ('SPX', 'S&P 500', 'https://www.futunn.com/index/.SPX-US', False),
        ('NDX', 'NASDAQ', 'https://www.futunn.com/index/.IXIC-US', False),
        ('DJI', '道琼斯', 'https://www.futunn.com/index/.DJI-US', False),
        ('VIX', 'VIX', 'https://www.futunn.com/futures/VXMAIN-US', True),
        ('SH', '上证指数', 'https://www.futunn.com/index/000001-SH', False),
        ('SZ', '深证成指', 'https://www.futunn.com/index/399001-SZ', False),
        ('CY', '创业板指', 'https://www.futunn.com/index/399006-SZ', False),
        ('HK', '恒生科技', 'https://www.futunn.com/index/800700-HK', False),
    ]
    
    indices_out = {}
    sparklines = {}
    
    for key, name, href, is_vix in idx_config:
        entry = index_data.get(key, {})
        
        if entry:
            price = entry.get('price', 0)
            change = entry.get('change', 0)
            chg_pct = entry.get('chg_pct', 0)
            
            # Generate sparkline — prefer canvas-extracted path from browser snapshot
            spark_path = entry.get('spark_path')
            minute_prices = entry.get('minute_prices', [])
            if spark_path and key in index_data and 'spark_path' in index_data[key]:
                sparklines[key] = spark_path
                # Determine color from change
                change_val = entry.get('change', 0) or entry.get('chg_pct', 0)
                if is_vix:
                    sparklines[f'{key}_color'] = '#FF4060' if change_val >= 0 else '#00C853'
                else:
                    sparklines[f'{key}_color'] = '#FF4060' if change_val >= 0 else '#00C853'
            elif minute_prices and len(minute_prices) >= 5:
                sparklines[key] = gen_sparkline_svg(minute_prices)
                sparklines[f'{key}_color'] = '#FF4060' if minute_prices[-1] >= minute_prices[0] else '#00C853'
            elif entry.get('open') is not None and entry.get('high') is not None:
                o = entry['open']
                h = entry['high']
                l = entry['low']
                c = price
                sparklines[key] = gen_sparkline_from_ohlc(o, h, l, c)
                if is_vix:
                    sparklines[f'{key}_color'] = '#FF6900' if c >= o else '#00C853'
                else:
                    sparklines[f'{key}_color'] = '#FF4060' if c >= o else '#00C853'
            elif entry.get('high') is not None and entry.get('low') is not None:
                # Has high/low from browser snapshot but no open
                h = entry['high']
                l = entry['low']
                o = price - (change * 0.5) if change else price * 0.997
                if change >= 0:
                    o = min(o, price) * 0.998  # opened lower
                else:
                    o = max(o, price) * 1.002  # opened higher
                sparklines[key] = gen_sparkline_from_ohlc(o, h, l, price)
                sparklines[f'{key}_color'] = get_sparkline_color(change, chg_pct, is_vix)
            elif entry.get('prev_close'):
                # Only have current and prev_close
                o = entry['prev_close'] * 0.995 if change >= 0 else entry['prev_close'] * 1.005
                o = o if o > 0 else price * 0.995
                h = max(price, o) * 1.002
                l = min(price, o) * 0.998
                sparklines[key] = gen_sparkline_from_ohlc(o, h, l, price)
                sparklines[f'{key}_color'] = get_sparkline_color(change, chg_pct, is_vix)
            
            indices_out[key] = {
                'price': price,
                'change': change,
                'chg_pct': chg_pct,
                'source': entry.get('source', 'unknown')
            }
        else:
            # No data at all - use placeholder
            indices_out[key] = {'price': 0, 'change': 0, 'chg_pct': 0, 'source': 'none'}
            sparklines[key] = f"M1,16 L79,16"
            sparklines[f'{key}_color'] = '#00C853'
    
    output = {
        'date': date_str,
        'indices': indices_out,
        'sparklines': sparklines,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    return output

# ============================================================
# ARCHIVE
# ============================================================
def archive_data(output, date_str=None):
    """Save to archive + update latest.json."""
    from datetime import datetime
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    
    # Daily archive
    daily_path = os.path.join(ARCHIVE_DIR, f'idx-{date_str}.json')
    with open(daily_path, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    # latest.json
    latest_path = os.path.join(ARCHIVE_DIR, 'latest.json')
    with open(latest_path, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    return daily_path

def load_latest_archive():
    """Load the latest available archive data."""
    latest_path = os.path.join(ARCHIVE_DIR, 'latest.json')
    if os.path.exists(latest_path):
        try:
            with open(latest_path) as f:
                return json.load(f)
        except:
            pass
    
    # Try most recent daily file
    if os.path.isdir(ARCHIVE_DIR):
        files = sorted(os.listdir(ARCHIVE_DIR))
        for fname in reversed(files):
            if fname.startswith('idx-') and fname.endswith('.json'):
                try:
                    with open(os.path.join(ARCHIVE_DIR, fname)) as f:
                        return json.load(f)
                except:
                    continue
    return None

# ============================================================
# MARKET HOURS CHECK
# ============================================================
def is_market_open(market, now=None):
    """Check if a given market is currently in trading hours."""
    from datetime import datetime, time as dtime
    if now is None:
        now = datetime.now()
    
    # Weekday check
    if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False
    
    t = now.time()
    h, m = t.hour, t.minute
    
    if market == 'ashare':
        return dtime(9, 30) <= t <= dtime(15, 0)
    elif market == 'hk':
        # HK morning: 09:30-12:00, afternoon: 13:00-16:00
        return (dtime(9, 30) <= t <= dtime(12, 0)) or (dtime(13, 0) <= t <= dtime(16, 0))
    elif market == 'us':
        # US: 21:30-04:00 next day (EDT)
        if h >= 21 or h < 4:
            return True
        return False
    return False

def get_market_date_for_archive(now=None):
    """Get the date string to use for today's archive."""
    from datetime import datetime
    if now is None:
        now = datetime.now()
    return now.strftime('%Y-%m-%d')

# ============================================================
# MAIN
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fetch index data for report index cards')
    parser.add_argument('--output', help='Output JSON path (default: stdout)')
    parser.add_argument('--date', help='Date string YYYY-MM-DD')
    parser.add_argument('--archive', action='store_true', default=True, help='Archive after fetch (default: True)')
    parser.add_argument('--no-archive', action='store_true', help='Skip archival')
    parser.add_argument('--use-archive', action='store_true', help='Only use latest archive, skip fetch')
    args = parser.parse_args()
    
    from datetime import datetime
    now = datetime.now()
    date_str = args.date or get_market_date_for_archive(now)
    
    # Check if any market is open
    ashare_open = is_market_open('ashare', now)
    hk_open = is_market_open('hk', now)
    us_open = is_market_open('us', now)
    any_open = ashare_open or hk_open or us_open
    
    if args.use_archive:
        print(f"  Using archive only (--use-archive)", file=sys.stderr)
        archive = load_latest_archive()
        if archive:
            print(f"  Loaded archive: {archive.get('date','?')}", file=sys.stderr)
            output = archive
        else:
            print(f"  No archive found, fetching...", file=sys.stderr)
            data = fetch_all_indices()
            output = assemble_output(data, date_str)
            if not args.no_archive:
                archive_data(output, date_str)
    elif any_open or ashare_open or hk_open or us_open:
        print(f"  Markets open: A-share={'Y' if ashare_open else 'N'} HK={'Y' if hk_open else 'N'} US={'Y' if us_open else 'N'}", file=sys.stderr)
        print(f"  Fetching real-time data...", file=sys.stderr)
        data = fetch_all_indices()
        output = assemble_output(data, date_str)
        if not args.no_archive:
            archive_path = archive_data(output, date_str)
            print(f"  Archived: {archive_path}", file=sys.stderr)
    else:
        print(f"  All markets closed, using archive", file=sys.stderr)
        archive = load_latest_archive()
        if archive:
            print(f"  Loaded archive: {archive.get('date','?')} ({archive.get('timestamp','?')})", file=sys.stderr)
            output = archive
        else:
            print(f"  No archive found, fetching...", file=sys.stderr)
            data = fetch_all_indices()
            output = assemble_output(data, date_str)
            if not args.no_archive:
                archive_data(output, date_str)
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"  Written: {args.output}", file=sys.stderr)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    
    # Summary
    ok_count = sum(1 for v in output.get('indices', {}).values() if v.get('price'))
    print(f"  Index data: {ok_count}/8 OK", file=sys.stderr)

if __name__ == '__main__':
    main()
