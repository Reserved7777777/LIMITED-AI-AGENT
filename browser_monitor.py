#!/usr/bin/env python3
"""
browser_monitor.py — Monitor VIX (VXMAIN futures) via Playwright (only index needing browser).
Extracts real-time data + exact chart sparkline from K-line canvas.
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
    'VIX': {'url': 'https://www.futunn.com/futures/VXMAIN-US', 'market': 'us', 'symbol': 'VXMAIN'},
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
    return result if result.get('price') else None


def _extract_kline_closes(page):
    """Extract exact K-line closing prices from VXMAIN canvas.
    
    Key insight: the K-line chart canvas has thick candle bodies, thin wicks,
    thin text labels, and volume bars at the bottom. By cropping to JUST the
    candle body area and resizing down to 40 pixels wide, the resize (LANCZOS)
    averages out all thin elements, leaving only the dense candle bodies.
    
    The lowest saturated pixel in each column corresponds to the closing price
    (bottom of down-candle body for a down day).
    
    ViewBox mapping: -4(top = higher price) to 28(bottom = lower price).
    """
    if Image is None:
        return None, 0
    try:
        el = page.query_selector('.stock-chart-box canvas')
        if not el:
            return None, 0
        raw_bytes = el.screenshot()
        img = Image.open(BytesIO(raw_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        w, h = img.size
        if w < 100 or h < 50:
            return None, 0
        
        # Crop to chart body area (excludes axis labels, volume bars, gaps)
        # VXMAIN layout: chart occupies ~10-88% width, ~25-45% height
        chart = img.crop((
            int(w * 0.10),   # left: skip Y-axis labels
            int(h * 0.25),   # top: skip title/gaps above chart
            int(w * 0.87),   # right: skip right margin
            int(h * 0.48),   # bottom: skip volume bars
        ))
        
        # Resize to higher resolution for more data points
        # 80x32 matches the SVG viewBox dimensions exactly
        # Each pixel averages ~10x4 original pixels - enough to suppress thin
        # elements (wicks ~2px, text ~1px) but preserve candle bodies (~8-15px)
        tiny = chart.resize((80, 32), Image.LANCZOS)
        tw, th = tiny.size
        
        # Get pixel data
        tp = list(tiny.getdata())
        
        # For each of 80 columns, find the lowest saturated pixel
        # After LANCZOS: background ~200-230, candle bodies ~80-170
        # The bottom of a green candle body = close for down candle
        closes = []
        for cx in range(tw):
            last = None
            for cy in range(th):
                r, g, b = tp[cy * tw + cx][:3]
                # Skip bright/gray background
                if r > 210 and g > 210 and b > 210:
                    continue
                if abs(r-g) < 20 and abs(g-b) < 20 and abs(r-b) < 20:
                    continue
                last = cy
            closes.append(last)
        
        # Fill gaps between columns with close data
        # Interpolate None columns from nearest neighbors
        valid = [(i, c) for i, c in enumerate(closes) if c is not None]
        if len(valid) < 5:
            return None, 0
        
        # Build contiguous array with interpolation
        all_xs, all_ys = zip(*valid)
        all_ys = list(all_ys)
        all_xs = list(all_xs)
        
        # Median filter (window=3)
        for i in range(len(all_ys)):
            s = max(0, i-1)
            e = min(len(all_ys), i+2)
            wv = sorted(all_ys[s:e])
            all_ys[i] = wv[len(wv)//2]
        
        # Map to SVG viewBox: 0 -4 80 32
        min_y, max_y = min(all_ys), max(all_ys)
        yr = max_y - min_y if max_y != min_y else 1
        min_x, max_x = min(all_xs), max(all_xs)
        xr = max_x - min_x if max_x != min_x else 1
        
        def nx(sx): return 2 + (sx - min_x) / xr * 76
        def ny(sy): return -2 + ((sy - min_y) / yr) * 24
        
        path = 'M%.1f,%.1f' % (nx(all_xs[0]), ny(all_ys[0]))
        for xi, yi in zip(all_xs[1:], all_ys[1:]):
            yv = ny(yi)
            if yv < -3.5: yv = -3.5
            if yv > 27.5: yv = 27.5
            path += ' L%.1f,%.1f' % (nx(xi), yv)
        
        return path, len(all_xs)
        
    except Exception as e:
        print("  WARN: _extract_kline_closes error: " + str(e), file=sys.stderr)
        return None, 0


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
        
        pixel_data = list(img.getdata())
        col_pixels = [[] for _ in range(w)]
        for i, rgb in enumerate(pixel_data):
            col_pixels[i % w].append(rgb)
        
        _crop_left = int(w * 0.10)
        _crop_right = int(w * 0.90)
        
        col_pts = []
        for col in range(w):
            if col < _crop_left or col > _crop_right:
                col_pts.append(None)
                continue
            best_y = -1
            best_score = 0
            for row in range(h):
                r, g, b = col_pixels[col][row]
                if r > 240 and g > 240 and b > 240:
                    continue
                if r < 25 and g < 25 and b < 25:
                    continue
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
        
        _y_vals = [v for v in col_pts if v is not None]
        if _y_vals:
            _y_sorted = sorted(_y_vals)
            _n = len(_y_sorted)
            _q1 = _y_sorted[_n // 4]
            _q3 = _y_sorted[3 * _n // 4]
            _iqr = _q3 - _q1 if _q3 > _q1 else max(_y_sorted) - min(_y_sorted) * 0.3
            _lower = _q1 - 1.5 * _iqr
            _upper = _q3 + 1.5 * _iqr
            _lower = max(_lower, 0)
            _upper = min(_upper, h - 1)
            for i in range(len(col_pts)):
                if col_pts[i] is not None and (col_pts[i] < _lower or col_pts[i] > _upper):
                    col_pts[i] = None
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
        
        valid = [i for i, v in enumerate(col_pts) if v is not None] or valid
        valid.sort()
        ys = [col_pts[i] for i in valid]
        xs = valid
        
        half = 3
        filtered = list(ys)
        for i in range(len(ys)):
            start = max(0, i - half)
            end = min(len(ys), i + half + 1)
            window_vals = sorted(ys[start:end])
            filtered[i] = window_vals[len(window_vals) // 2]
        ys = filtered
        
        if len(ys) > target_points:
            indices = [int(i * (len(ys) - 1) / (target_points - 1)) for i in range(target_points)]
            ys = [ys[i] for i in indices]
            xs = [xs[i] for i in indices]
        
        min_y, max_y = min(ys), max(ys)
        y_range = max_y - min_y if max_y != min_y else 1
        min_sx, max_sx = min(xs), max(xs)
        x_range = max_sx - min_sx if max_sx != min_sx else 1
        margin = 2
        def nx(sx): return margin + (sx - min_sx) / x_range * (80 - 2 * margin)
        def ny(sy): return -4 + (sy - min_y) / y_range * 32
        
        path = 'M{:.1f},{:.1f}'.format(nx(xs[0]), ny(ys[0]))
        for sxi, syi in zip(xs[1:], ys[1:]):
            _y_clamped = max(-4.0, min(28.0, ny(syi)))
            path += ' L{:.1f},{:.1f}'.format(nx(sxi), _y_clamped)
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
                        if key == 'VIX':
                            # VIX uses K-line chart with specialized canvas extraction
                            spark_path, n_kline = _extract_kline_closes(page)
                        else:
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
            sp = v.get('spark_path', '')
            sp_pts = len(sp.split(' ')) if sp else 0
            print("    " + k + ": " + str(v.get('price','?')) + "  " + str(v.get('change','?')) + "  " + v.get('status','')[:10] + "  spark=" + str(sp_pts) + "pts", file=sys.stderr)


if __name__ == '__main__':
    run()
