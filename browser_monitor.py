#!/usr/bin/env python3
"""
browser_monitor.py — Monitor VIX (VXMAIN futures) via Playwright (only index needing browser).
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
    # VIX: use the raw futures price (top value on page), NOT .VIX spot override
    # User explicitly requested: "不要用 .VIX的值用最上面的第一个值"
    # Update source label to indicate it's the futures contract
    return result if result.get('price') else None


def _extract_kline_closes(page):
    """
    Extract closing prices from a K-line (candlestick) chart canvas.
    
    For K-line charts (used by VXMAIN futures page), the chart shows
    candlesticks with bodies and wicks. For down candles, the closing
    price is at the BOTTOM of the candle body.
    
    Strategy:
    1. Crop to chart area (exclude Y-axis labels, volume bars)
    2. For each column, find the LOWEST green-ish pixel = close of down candle
    3. Map to SVG viewBox with correct orientation (higher price = higher on chart)
    
    Returns: (path_string, num_points) or (None, 0) on failure
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
        
        pixels = list(img.getdata())
        
        # Chart area crops - VXMAIN futures has Y-axis labels extending
        # into the chart area. Dynamic detection: find where green
        # pixel column variation exceeds 10px (chart starts).
        _tmp_l = int(w * 0.02)
        _tmp_r = int(w * 0.98)
        _tmp_t = int(h * 0.12)
        _tmp_b = int(h * 0.55)
        
        # Find chart start column by detecting close value variation
        _chart_start = _tmp_r
        for _col in range(_tmp_l, _tmp_r):
            _lowest = None
            for _row in range(_tmp_t, _tmp_b):
                _r, _g, _b = pixels[_row * w + _col][:3]
                if _r > 230 and _g > 230 and _b > 230: continue
                if _r < 25 and _g < 25 and _b < 25: continue
                _gs = _g - max(_r, _b)
                if _gs > 15:
                    _lowest = _row
            if _lowest is not None:
                _prev_lowest = None
                for _pcol in range(max(_tmp_l, _col - 15), _col):
                    for _prow in range(_tmp_t, _tmp_b):
                        _pr, _pg, _pb = pixels[_prow * w + _pcol][:3]
                        if _pr > 230 and _pg > 230 and _pb > 230: continue
                        if _pr < 25 and _pg < 25 and _pb < 25: continue
                        _gs2 = _pg - max(_pr, _pb)
                        if _gs2 > 15:
                            _prev_lowest = _prow
                            break
                    if _prev_lowest is not None:
                        break
                if _prev_lowest is not None and abs(_lowest - _prev_lowest) > 8:
                    _chart_start = _col
                    break
        
        # Safeguard: ensure chart area is at least 30% of canvas width
        _min_l = int(w * 0.25)
        l_crop = max(_chart_start, _min_l)
        
        # Right crop: chart ends when green pixels drop near zero
        _chart_end = _tmp_l
        _count_10 = 0
        for _col in range(_tmp_r - 1, _tmp_l, -1):
            _has_green = False
            for _row in range(_tmp_t, _tmp_b):
                _r, _g, _b = pixels[_row * w + _col][:3]
                if _r > 230 and _g > 230 and _b > 230: continue
                if _r < 25 and _g < 25 and _b < 25: continue
                if _g - max(_r, _b) > 15:
                    _has_green = True
                    _count_10 = 15
                    _chart_end = _col
                    break
            if not _has_green:
                _count_10 -= 1
                if _count_10 <= 0 and _chart_end == _tmp_l:
                    _chart_end = _col
                    break
        
        _min_r = int(w * 0.75)
        r_crop = max(_chart_end, _min_r)
        t_crop = _tmp_t
        b_crop = _tmp_b
        
        # Scan each column for the lowest green-ish pixel
        # This represents the close of a down candle in a K-line chart
        closes = []
        for col in range(l_crop, r_crop):
            lowest_green = None
            for row in range(t_crop, b_crop):
                r, g, b = pixels[row * w + col][:3]
                # Skip background (bright gray) and grid (dark)
                if r > 235 and g > 235 and b > 235:
                    continue
                if r < 30 and g < 30 and b < 30:
                    continue
                # For VIX (down), look for green-ish pixels (g > max(r,b))
                green_score = g - max(r, b)
                if green_score > 15:
                    lowest_green = row  # track the last one (bottom)
            closes.append(lowest_green)
        
        # Remove None columns
        valid = [(i, c) for i, c in enumerate(closes) if c is not None]
        if len(valid) < 5:
            return None, 0
        
        # Bucket into target_points (~40)
        target_pts = 40
        xs_raw, ys_raw = zip(*valid)
        n_valid = len(valid)
        bucket_size = max(1, n_valid // target_pts)
        
        sampled = []
        for bi in range(target_pts):
            start = bi * bucket_size
            end = min((bi + 1) * bucket_size, n_valid)
            bucket = valid[start:end]
            if not bucket:
                continue
            bucket_ys = [b[1] for b in bucket]
            bucket_ys.sort()
            median_y = bucket_ys[len(bucket_ys)//2]
            median_x = bucket[len(bucket)//2][0]
            sampled.append((median_x, median_y))
        
        # Map to SVG viewBox: 0 -4 80 32 (y: -4=top, 28=bottom)
        # Image y (increasing downward) must map to SVG y correctly
        # Higher price = lower image y = lower SVG y = top of chart
        # Lower price = higher image y = higher SVG y = bottom of chart
        min_img_y = min(p[1] for p in sampled)
        max_img_y = max(p[1] for p in sampled)
        img_range = max_img_y - min_img_y if max_img_y != min_img_y else 1
        min_x = min(p[0] for p in sampled)
        max_x = max(p[0] for p in sampled)
        x_range = max_x - min_x if max_x != min_x else 1
        
        def nx(sx): return 2 + (sx - min_x) / x_range * 76
        # SVG y = lower y for higher price (invert image y mapping)
        # Higher price (small img y) → small SVG y (top)
        def ny(sy): return -2 + ((sy - min_img_y) / img_range) * 24
        
        path = 'M%.1f,%.1f' % (nx(sampled[0][0]), ny(sampled[0][1]))
        for col, row in sampled[1:]:
            yv = ny(row)
            if yv < -3.5: yv = -3.5
            if yv > 27.5: yv = 27.5
            path += ' L%.1f,%.1f' % (nx(col), yv)
        
        return path, len(sampled)
        
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
        
        # Column-major pixel arrays
        pixel_data = list(img.getdata())
        col_pixels = [[] for _ in range(w)]
        for i, rgb in enumerate(pixel_data):
            col_pixels[i % w].append(rgb)
        
        # CROP EDGE COLUMNS (Y-axis labels/shadows at left 10% and right 10%)
        _crop_left = int(w * 0.10)
        _crop_right = int(w * 0.90)
        
        # For each column, find the chart line position via max saturation
        col_pts = []
        for col in range(w):
            if col < _crop_left or col > _crop_right:
                col_pts.append(None)
                continue
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
        
        # IQR-based outlier removal
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
            # Re-interpolate
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
        
        # Median filter window=7
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
        
        # Map to viewBox="0 -4 80 32"
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
                        # VIX uses a K-line (candlestick) chart, not a line chart.
                        # Specialized K-line extraction finds candle body bottoms
                        # as close prices, removing Y-axis shadow artifacts.
                        if key == 'VIX':
                            spark_path, _ = _extract_kline_closes(page)
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
            s = v.get('status', '?')[:16] if v.get('status') else '?'
            sp = v.get('spark_path', '')
            sp_info = ' spark=' + str(len(sp.split('L'))) + 'pts' if sp else ''
            print("    " + k + ": " + str(v['price']) + "  " + str(v.get('change','?')) + "  " + s + sp_info, file=sys.stderr)
    else:
        print("\n  No data captured", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    run()
