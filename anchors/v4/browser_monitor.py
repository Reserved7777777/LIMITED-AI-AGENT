#!/usr/bin/env python3
"""
browser_monitor.py — Monitor futunn index pages via Playwright + existing Chrome CDP.
Extracts real-time data + actual chart sparkline from canvas.
"""
import json, os, sys, re, time
from datetime import datetime
from io import BytesIO
try:
    from PIL import Image
except ImportError:
    Image = None

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'idx_data')
os.makedirs(ARCHIVE_DIR, exist_ok=True)

INDEX_CARDS = {
    'SPX': {'url': 'https://www.futunn.com/index/.SPX-US', 'market': 'us', 'symbol': '.SPX'},
    'NDX': {'url': 'https://www.futunn.com/index/.IXIC-US', 'market': 'us', 'symbol': '.IXIC'},
    'DJI': {'url': 'https://www.futunn.com/index/.DJI-US', 'market': 'us', 'symbol': '.DJI'},
    'VIX': {'url': 'https://www.futunn.com/futures/VXMAIN-US', 'market': 'us', 'symbol': 'VXMAIN'},
    'SH':  {'url': 'https://www.futunn.com/index/000001-SH', 'market': 'ashare', 'symbol': '000001'},
    'SZ':  {'url': 'https://www.futunn.com/index/399001-SZ', 'market': 'ashare', 'symbol': '399001'},
    'CY':  {'url': 'https://www.futunn.com/index/399006-SZ', 'market': 'ashare', 'symbol': '399006'},
    'HK':  {'url': 'https://www.futunn.com/index/800700-HK', 'market': 'hk', 'symbol': '800700'},
}

def parse_num(s):
    try: return float(s.strip().replace(',', ''))
    except: return None

def extract(text, key):
    result = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    price = change = chg_pct = high = low = status = None
    for i, line in enumerate(lines):
        n = parse_num(line)
        if n and n > 0 and price is None:
            price = n
            continue
        if price is not None and price != 0:
            m = re.search(r'^([+-]\d+\.?\d*)([+-]\d+\.?\d*%)', line)
            if m and change is None:
                change = float(m.group(1))
                chg_pct = float(m.group(2).rstrip('%'))
                continue
            m = re.search(r'^([+-]\d+\.?\d*)([+-]?\d+\.?\d*%)$', line.replace(' ',''))
            if m and change is None:
                change = float(m.group(1))
                chg_pct = float(m.group(2).rstrip('%'))
                continue
            m = re.match(r'^[+-]\d+\.?\d*%$', line)
            if m and chg_pct is None:
                chg_pct = float(m.group().rstrip('%'))
                continue
        if re.search(r'\u4ea4\u6613|\u6536\u76d8|\u4f11\u5e02|\u7ade\u4ef7', line):
            status = line
        if line in ('\u6700\u9ad8\u4ef7', '\u6700\u9ad8', 'HIGH'):
            if i + 1 < len(lines):
                n2 = parse_num(lines[i+1])
                if n2: high = n2
        if line in ('\u6700\u4f4e\u4ef7', '\u6700\u4f4e', 'LOW'):
            if i + 1 < len(lines):
                n2 = parse_num(lines[i+1])
                if n2: low = n2
    if price and change is not None:
        result.update({'price': price, 'change': change, 'chg_pct': chg_pct if chg_pct is not None else 0})
        if status: result['status'] = status
        if chg_pct and abs(chg_pct) > 0.001:
            result['prev_close'] = round(price / (1 + chg_pct/100), 2)
        elif change:
            result['prev_close'] = round(price - change, 2)
        if high: result['high'] = high
        if low: result['low'] = low
        result['source'] = 'futunn_browser'
    # VIX: use the raw futures price (top value on page), NOT .VIX spot override
    # User explicitly requested: "不要用 .VIX的值用最上面的第一个值"
    # Update source label to indicate it's the futures contract
    if 'VIX' in key and result.get('price'):
        result['source'] = 'futunn_browser'
    return result if result.get('price') else None


def extract_spark_from_canvas(page, target_points=73):
    """Extract chart line from futunn canvas via screenshot + per-column max-saturation.
    Uses the proven approach: per-column max-saturation pixel + median filter + 73pt sampling.
    Returns SVG path string matching viewBox='0 -4 80 32'."""
    if Image is None:
        print("  WARN: PIL not installed, cannot extract sparkline", file=sys.stderr)
        return None
    try:
        el = page.query_selector('.stock-chart-box canvas')
        if not el:
            return None
        raw_bytes = el.screenshot()
        img = Image.open(BytesIO(raw_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        w, h = img.size
        if w < 50 or h < 50:
            return None
        
        # Column-major pixel arrays
        pixel_data = list(img.getdata())
        col_pixels = [[] for _ in range(w)]
        for i, rgb in enumerate(pixel_data):
            col_pixels[i % w].append(rgb)
        
        # For each column, find the chart line position via max saturation
        # This picks the single most saturated non-white pixel = center of the chart line
        # More stable than weighted centroid which picks up noise from anti-aliased edges
        col_pts = []
        for col in range(w):
            best_y = -1
            best_score = 0
            for row in range(h):
                r, g, b = col_pixels[col][row]
                # Skip near-white (background)
                if r > 240 and g > 240 and b > 240:
                    continue
                # Skip near-black (axis, grid lines, labels)
                if r < 25 and g < 25 and b < 25:
                    continue
                # Color saturation
                mn = min(r, g, b)
                mx = max(r, g, b)
                sat = mx - mn
                brightness = (r + g + b) / 3.0
                if sat > 15 and brightness > 30:
                    score = sat * (brightness / 255.0)
                    if score > best_score:
                        best_score = score
                        best_y = row
            col_pts.append(best_y if best_y >= 0 else None)
        
        # Fill None gaps by linear interpolation
        valid = [i for i, v in enumerate(col_pts) if v is not None]
        if len(valid) < 5:
            return None
        for i in range(len(col_pts)):
            if col_pts[i] is None:
                before = [j for j in valid if j < i]
                after = [j for j in valid if j > i]
                if before and after:
                    b, a = before[-1], after[0]
                    col_pts[i] = int(col_pts[b] + (col_pts[a] - col_pts[b]) * (i - b) / (a - b))
                elif before:
                    col_pts[i] = col_pts[before[-1]]
                elif after:
                    col_pts[i] = col_pts[after[0]]
        valid.sort()
        ys = [col_pts[i] for i in valid]
        xs = valid
        
        # Median filter window=7 — proven effective at removing single-pixel noise
        # while preserving sawtooth character
        half = 3
        filtered = list(ys)
        for i in range(len(ys)):
            start = max(0, i - half)
            end = min(len(ys), i + half + 1)
            window_vals = sorted(ys[start:end])
            filtered[i] = window_vals[len(window_vals) // 2]
        ys = filtered
        
        # Downsample to target_points (73)
        if len(ys) > target_points:
            indices = [int(i * (len(ys) - 1) / (target_points - 1)) for i in range(target_points)]
            ys = [ys[i] for i in indices]
            xs = [xs[i] for i in indices]
        
        # Map to viewBox="0 -4 80 32": x:0-80, y:-4(top) to 28(bottom)
        min_y, max_y = min(ys), max(ys)
        y_range = max_y - min_y if max_y != min_y else 1
        min_sx, max_sx = min(xs), max(xs)
        x_range = max_sx - min_sx if max_sx != min_sx else 1
        margin = 2
        def nx(sx): return margin + (sx - min_sx) / x_range * (80 - 2 * margin)
        def ny(sy): return -4 + (sy - min_y) / y_range * 32
        
        path = 'M{:.1f},{:.1f}'.format(nx(xs[0]), ny(ys[0]))
        for sxi, syi in zip(xs[1:], ys[1:]):
            path += ' L{:.1f},{:.1f}'.format(nx(sxi), ny(syi))
        return path
        
    except Exception as e:
        print("  WARN: extract_spark error: " + str(e), file=sys.stderr)
        return None


def run():
    from playwright.sync_api import sync_playwright
    print("\n" + "=" * 50, file=sys.stderr)
    print("  futunn Browser Monitor", file=sys.stderr)
    print("  " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'), file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    indices = {}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://localhost:9222')
        context = browser.contexts[0]
        page = context.new_page()
        for key, info in INDEX_CARDS.items():
            try:
                print("  [" + key + "]: " + info['url'], file=sys.stderr)
                page.goto(info['url'], wait_until='domcontentloaded', timeout=15000)
                time.sleep(3.5)
                text = page.evaluate('() => document.body.innerText')
                if not text or len(text) < 50:
                    print("  WARN: " + key + " page too short", file=sys.stderr)
                    continue
                data = extract(text, key)
                if data:
                    data['market'] = info['market']
                    data['symbol'] = info['symbol']
                    try:
                        spark_path = extract_spark_from_canvas(page)
                        if spark_path:
                            data['spark_path'] = spark_path
                    except Exception:
                        pass
                    indices[key] = data
                    tag = 'T' if '\u4ea4\u6613' in (data.get('status','')) else 'C'
                    sp_pts = len(data.get('spark_path','').split(' ')) if data.get('spark_path') else 0
                    print("  OK " + key + ": " + str(data['price']) + " " + str(data.get('change',0)) + " [" + tag + "] spark=" + str(sp_pts), file=sys.stderr)
                else:
                    print("  WARN: " + key + " extract failed", file=sys.stderr)
            except Exception as e:
                print("  FAIL: " + key + " " + str(e), file=sys.stderr)
        page.close()
    if indices:
        snapshot = {'date': datetime.now().strftime('%Y-%m-%d'), 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'indices': indices}
        path = os.path.join(ARCHIVE_DIR, 'browser_snapshot.json')
        with open(path, 'w') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        print("\n  Saved: " + path + " (" + str(len(indices)) + " indices)", file=sys.stderr)
        for k, v in indices.items():
            s = v.get('status', '?')[:16] if v.get('status') else '?'
            sp = v.get('spark_path', '')
            sp_info = ' spark=' + str(len(sp.split('L'))) + 'pts' if sp else ''
            print("    " + k + ": " + str(v['price']) + "  " + str(v.get('change','?')) + "  " + s + sp_info, file=sys.stderr)
    else:
        print("\n  No data captured", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    run()
