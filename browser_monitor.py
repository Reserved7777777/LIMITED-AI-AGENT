#!/usr/bin/env python3
"""
browser_monitor.py — Monitor all 8 index cards via Playwright canvas extraction.
Extracts exact chart sparklines from each page's canvas for pixel-perfect matching.

Index pages:
  US: SPX/NDX/DJI → futunn.com/index (line chart, 1 canvas)
  VIX → futunn.com/futures/VXMAIN-US (K-line chart, 1 canvas)
  SH/SZ/CY/HK → gu.qq.com (mixed canvases, different layout)
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

# 8 index cards with their page URLs
INDEX_PAGES = [
    ('SPX', 'https://www.futunn.com/index/.SPX-US', 'line'),
    ('NDX', 'https://www.futunn.com/index/.IXIC-US', 'line'),
    ('DJI', 'https://www.futunn.com/index/.DJI-US', 'line'),
    ('VIX', 'https://www.futunn.com/futures/VXMAIN-US', 'kline'),
    ('SH', 'https://gu.qq.com/sh000001', 'tencent'),
    ('SZ', 'https://gu.qq.com/sz399001', 'tencent'),
    ('CY', 'https://gu.qq.com/sz399006', 'tencent'),
    ('HK', 'https://gu.qq.com/hkHSTECH', 'tencent'),
]


def parse_num(s):
    try: return float(s.strip().replace(',', ''))
    except: return None


def _extract_line_spark_raw(page, chart_pct=(0.13, 0.90, 0.10, 0.85)):
    """Extract sparkline from a LINE chart canvas.
    
    Uses max-saturation per column (line chart = single colored line on background).
    Crops to chart area, applies IQR filtering, returns SVG path.
    """
    if Image is None:
        return None
    try:
        el = page.query_selector('.stock-chart-box canvas')
        if not el:
            # Try any canvas on the page
            canvases = page.query_selector_all('canvas')
            if not canvases:
                return None
            el = canvases[0]
        
        raw = el.screenshot()
        img = Image.open(BytesIO(raw))
        if img.mode != 'RGB': img = img.convert('RGB')
        w, h = img.size
        if w < 50 or h < 50: return None
        
        pixels = list(img.getdata())
        
        # Crop to chart area
        l = int(w * chart_pct[0])
        r = int(w * chart_pct[1])
        t = int(h * chart_pct[2])
        b = int(h * chart_pct[3])
        
        # Per-column: find most saturated non-white, non-black pixel (chart line)
        col_pts = []
        for col in range(l, r):
            best_y = -1
            best_score = 0
            for row in range(t, b):
                rv, gv, bv = pixels[row * w + col][:3]
                if rv > 240 and gv > 240 and bv > 240: continue
                if rv < 25 and gv < 25 and bv < 25: continue
                sat = max(rv, gv, bv) - min(rv, gv, bv)
                if sat > 15:
                    brightness = (rv + gv + bv) / 3.0
                    score = sat * (brightness / 255.0)
                    if score > best_score:
                        best_score = score
                        best_y = row
            col_pts.append(best_y if best_y >= 0 else None)
        
        # IQR filter + interpolation
        valid = [i for i, v in enumerate(col_pts) if v is not None]
        if len(valid) < 5: return None
        _interpolate(col_pts, valid)
        
        _y_vals = [v for v in col_pts if v is not None]
        if _y_vals:
            _y_sorted = sorted(_y_vals)
            _n = len(_y_sorted)
            _q1 = _y_sorted[_n // 4]
            _q3 = _y_sorted[3 * _n // 4]
            _iqr = _q3 - _q1 if _q3 > _q1 else max(_y_sorted) - min(_y_sorted) * 0.3
            _lower = max(_q1 - 1.5 * _iqr, 0)
            _upper = min(_q3 + 1.5 * _iqr, h - 1)
            for i in range(len(col_pts)):
                if col_pts[i] is not None and (col_pts[i] < _lower or col_pts[i] > _upper):
                    col_pts[i] = None
            valid = [i for i, v in enumerate(col_pts) if v is not None]
            if len(valid) < 5: return None
            _interpolate(col_pts, valid)
        
        valid = [i for i, v in enumerate(col_pts) if v is not None]
        valid.sort()
        
        # Median + downsample to ~45 points
        med_data = _median_filter([col_pts[i] for i in valid], 5)
        xs, ys = list(valid), med_data
        if len(ys) > 45:
            idxs = [int(i * (len(ys)-1) / 44) for i in range(45)]
            ys = [ys[i] for i in idxs]
            xs = [xs[i] for i in idxs]
        
        return _pts_to_svg_path(list(zip(xs, ys)))
    except Exception as e:
        print("  WARN: line_spark error: " + str(e), file=sys.stderr)
        return None


def _extract_kline_spark_raw(page):
    """Extract sparkline from a K-line (candlestick) chart canvas.
    
    Crops chart body area, resizes to 80x32 (LANCZOS averages out thin elements),
    finds lowest non-background pixel per column = closing price for down candles.
    """
    if Image is None: return None
    try:
        el = page.query_selector('.stock-chart-box canvas')
        if not el: return None
        raw = el.screenshot()
        img = Image.open(BytesIO(raw)).convert('RGB')
        w, h = img.size
        if w < 100 or h < 50: return None
        
        # Crop to chart body (excludes axis labels, volume bars, gaps)
        chart = img.crop((int(w*0.10), int(h*0.25), int(w*0.87), int(h*0.48)))
        # Resize to 80x32 LANCZOS - thin elements average to bg, bodies survive
        tiny = chart.resize((80, 32), Image.LANCZOS)
        tp = list(tiny.getdata())
        
        closes = []
        for cx in range(80):
            last = None
            for cy in range(32):
                r, g, b = tp[cy * 80 + cx][:3]
                if r > 210 and g > 210 and b > 210: continue
                if abs(r-g) < 20 and abs(g-b) < 20 and abs(r-b) < 20: continue
                last = cy
            closes.append(last)
        
        valid = [(i, c) for i, c in enumerate(closes) if c is not None]
        if len(valid) < 5: return None
        xs, ys = zip(*valid)
        ys = list(_median_filter(ys, 3))
        return _pts_to_svg_path(list(zip(xs, ys)))
    except Exception as e:
        print("  WARN: kline_spark error: " + str(e), file=sys.stderr)
        return None


def _extract_tencent_spark_raw(page):
    """Extract sparkline from Tencent gu.qq.com page.
    These pages have 5 canvases. The intraday chart is typically the first
    stock-chart canvas. Use max-saturation line extraction.
    """
    if Image is None: return None
    try:
        canvases = page.query_selector_all('canvas')
        if not canvases:
            return None
        
        # On Tencent pages, the main chart is usually the first large canvas
        chart_canvas = None
        for c in canvases:
            box = c.bounding_box()
            if box and box['width'] > 300 and box['height'] > 200:
                chart_canvas = c
                break
        if not chart_canvas:
            chart_canvas = canvases[0]
        
        raw = chart_canvas.screenshot()
        img = Image.open(BytesIO(raw)).convert('RGB')
        w, h = img.size
        
        # Line chart in a smaller canvas: crop less aggressively
        pixels = list(img.getdata())
        l = int(w * 0.08)
        r = int(w * 0.92)
        t = int(h * 0.08)
        b = int(h * 0.90)
        
        col_pts = []
        for col in range(l, r):
            best_y = -1
            best_score = 0
            for row in range(t, b):
                rv, gv, bv = pixels[row * w + col][:3]
                if rv > 235 and gv > 235 and bv > 235: continue
                if rv < 20 and gv < 20 and bv < 20: continue
                sat = max(rv, gv, bv) - min(rv, gv, bv)
                if sat > 25:
                    score = sat * ((rv+gv+bv)/3.0 / 255.0)
                    if score > best_score:
                        best_score = score
                        best_y = row
            col_pts.append(best_y if best_y >= 0 else None)
        
        valid = [i for i, v in enumerate(col_pts) if v is not None]
        if len(valid) < 5: return None
        _interpolate(col_pts, valid)
        
        valid = [i for i, v in enumerate(col_pts) if v is not None]
        valid.sort()
        med_data = _median_filter([col_pts[i] for i in valid], 5)
        xs, ys = list(valid), med_data
        if len(ys) > 45:
            idxs = [int(i * (len(ys)-1) / 44) for i in range(45)]
            ys = [ys[i] for i in idxs]
            xs = [xs[i] for i in idxs]
        return _pts_to_svg_path(list(zip(xs, ys)))
    except Exception as e:
        print("  WARN: tencent_spark error: " + str(e), file=sys.stderr)
        return None


def _interpolate(arr, valid_indices):
    """Fill None gaps in array by linear interpolation."""
    if not valid_indices: return
    for i in range(len(arr)):
        if arr[i] is None:
            before = [j for j in valid_indices if j < i]
            after = [j for j in valid_indices if j > i]
            if before and after:
                b, a = before[-1], after[0]
                arr[i] = int(arr[b] + (arr[a] - arr[b]) * (i - b) / (a - b))
            elif before:
                arr[i] = arr[before[-1]]
            elif after:
                arr[i] = arr[after[0]]


def _median_filter(data, window=3):
    """Apply median filter."""
    result = list(data)
    half = window // 2
    for i in range(len(data)):
        s = max(0, i-half)
        e = min(len(data), i+half+1)
        wv = sorted(data[s:e])
        result[i] = wv[len(wv)//2]
    return result


def _pts_to_svg_path(pts):
    """Convert [(x,y),...] to SVG path mapping to viewBox='0 -4 80 32'."""
    xs, ys = zip(*pts)
    min_y, max_y = min(ys), max(ys)
    yr = max_y - min_y if max_y != min_y else 1
    min_x, max_x = min(xs), max(xs)
    xr = max_x - min_x if max_x != min_x else 1
    def nx(sx): return 2 + (sx - min_x) / xr * 76
    def ny(sy): return -2 + ((sy - min_y) / yr) * 24
    
    path = 'M%.1f,%.1f' % (nx(xs[0]), ny(ys[0]))
    for xi, yi in zip(xs[1:], ys[1:]):
        yv = ny(yi)
        if yv < -3.5: yv = -3.5
        if yv > 27.5: yv = 27.5
        path += ' L%.1f,%.1f' % (nx(xi), yv)
    return path


def extract_page_price(text, key):
    """Extract price, change, chg_pct from page innerText."""
    result = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    price = change = chg_pct = status = None
    for i, line in enumerate(lines):
        n = parse_num(line)
        if n and n > 0 and price is None:
            price = n
            continue
        if price is not None:
            m = re.search(r'^([+-]\d+\.?\d*)([+-]\d+\.?\d*%)', line)
            if m and change is None:
                change = float(m.group(1))
                chg_pct = float(m.group(2).rstrip('%'))
                continue
            m = re.search(r'^([+-]\d+\.?\d*)([+-]?\d+\.?\d*%)$', line.replace(' ', ''))
            if m and change is None:
                change = float(m.group(1))
                chg_pct = float(m.group(2).rstrip('%'))
                continue
            m = re.match(r'^[+-]\d+\.?\d*%$', line)
            if m and chg_pct is None:
                chg_pct = float(m.group().rstrip('%'))
                continue
        if re.search(r'交易|收盘|休市|竞价', line):
            status = line
    if price and change is not None:
        result.update({'price': price, 'change': change, 'chg_pct': chg_pct or 0})
        if status: result['status'] = status
        if chg_pct and abs(chg_pct) > 0.001:
            result['prev_close'] = round(price / (1 + chg_pct/100), 2)
        elif change:
            result['prev_close'] = round(price - change, 2)
        result['source'] = 'browser'
    return result


EXTRACTORS = {
    'line': _extract_line_spark_raw,
    'kline': _extract_kline_spark_raw,
    'tencent': _extract_tencent_spark_raw,
}


def run():
    from playwright.sync_api import sync_playwright
    print("\n" + "=" * 50, file=sys.stderr)
    print("  Browser Monitor - All Indices", file=sys.stderr)
    print("  " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'), file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    
    indices = {}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://localhost:9222')
        context = browser.contexts[0]
        
        for name, url, chart_type in INDEX_PAGES:
            page = context.new_page()
            try:
                print("  [%s]: %s" % (name, url), file=sys.stderr)
                page.goto(url, wait_until='domcontentloaded', timeout=15000)
                time.sleep(3)
                
                text = page.evaluate('() => document.body.innerText')
                if not text or len(text) < 50:
                    print("  WARN: %s page too short (%dch)" % (name, len(text or '')), file=sys.stderr)
                    page.close()
                    continue
                
                data = extract_page_price(text, name)
                if data:
                    # Extract sparkline using chart-type-specific extractor
                    extractor = EXTRACTORS.get(chart_type)
                    if extractor:
                        try:
                            spark_path = extractor(page)
                            if spark_path:
                                data['spark_path'] = spark_path
                        except Exception as e:
                            print("  WARN: %s sparkline error: %s" % (name, e), file=sys.stderr)
                    
                    indices[name] = data
                    sp_pts = len(data.get('spark_path', '').split(' ')) if data.get('spark_path') else 0
                    print("  OK %s: %s %s [%s] spark=%d" % (
                        name, data.get('price','?'), data.get('change','?'),
                        'T' if '交易' in data.get('status','') else 'C', sp_pts), file=sys.stderr)
                else:
                    print("  WARN: %s extract failed" % name, file=sys.stderr)
            except Exception as e:
                print("  FAIL: %s %s" % (name, str(e)[:60]), file=sys.stderr)
            page.close()
    
    if indices:
        snapshot = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'indices': indices,
        }
        path = os.path.join(ARCHIVE_DIR, 'browser_snapshot.json')
        with open(path, 'w') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        print("\n  Saved: %s (%d indices)" % (path, len(indices)), file=sys.stderr)
        for k, v in indices.items():
            sp = v.get('spark_path', '')
            sp_pts = len(sp.split(' ')) if sp else 0
            print("    %s: %s %s spark=%dpts" % (
                k, v.get('price','?'), v.get('change','?'), sp_pts), file=sys.stderr)
    else:
        print("  FAIL: no indices collected", file=sys.stderr)


if __name__ == '__main__':
    run()
