#!/usr/bin/env python3
"""
browser_monitor.py - Monitor all 8 index cards via Playwright canvas extraction.
Extracts exact chart sparklines from each page's canvas for pixel-perfect matching.

Key principle: For LINE charts (US indices/Tencent A-shares), the extraction looks for
the DOMINANT COLOR pixel per column:
  - UP day (change >= 0): red-dominant line (r - max(g,b) highest)
  - DOWN day (change < 0): green-dominant line (g - max(r,b) highest)

For K-line charts (VIX futures): crop chart body, LANCZOS resize to 80x32,
find lowest non-background pixel per column (bottom of green candle body = close).

Index pages:
  US: SPX/NDX/DJI → futunn.com/index (line chart)
  VIX → futunn.com/futures/VXMAIN-US (K-line chart)
  SH/SZ/CY/HK → gu.qq.com (line chart, mixed canvases)
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


# ── helpers ──────────────────────────────────────────────────────

def _interpolate(arr, valid_indices):
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
    result = list(data)
    half = window // 2
    for i in range(len(data)):
        s = max(0, i - half)
        e = min(len(data), i + half + 1)
        wv = sorted(data[s:e])
        result[i] = wv[len(wv)//2]
    return result


def _pts_to_svg_path(pts):
    """Convert [(x,y),...] to SVG path viewBox='0 -4 80 32'."""
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


def _color_score(r, g, b, is_up):
    """Score how much this pixel looks like the chart line.
    For UP: red-dominant (r >> g,b).  For DOWN: green-dominant (g >> r,b).
    """
    if is_up:
        return r - max(g, b)
    else:
        return g - max(r, b)


def _column_to_pts(pixels, w, h, l, r, t, b, is_up, bg_thresh=235):
    """Per-column dominant color extraction for a line chart.
    Returns list of y-positions (None = no line found in that column).
    """
    col_pts = []
    for col in range(l, r):
        best_y = -1
        best_score = 0
        for row in range(t, b):
            rv, gv, bv = pixels[row * w + col][:3]
            if rv > bg_thresh and gv > bg_thresh and bv > bg_thresh:
                continue
            score = _color_score(rv, gv, bv, is_up)
            if score > best_score:
                best_score = score
                best_y = row
        col_pts.append(best_y if best_y >= 0 else None)
    return col_pts


def _post_process(col_pts, h):
    """IQR filter, interpolate, median smooth, downsample to ~45pts, → SVG path."""
    valid = [i for i, v in enumerate(col_pts) if v is not None]
    if len(valid) < 5:
        return None
    _interpolate(col_pts, valid)
    valid = [i for i, v in enumerate(col_pts) if v is not None]
    if len(valid) < 5:
        return None

    # IQR outlier removal
    vals = [v for i, v in enumerate(col_pts) if v is not None]
    sv = sorted(vals)
    n = len(sv)
    q1 = sv[n // 4]
    q3 = sv[3 * n // 4]
    iqr = q3 - q1 if q3 > q1 else max(vals) - min(vals) * 0.3
    lower = max(q1 - 1.5 * iqr, 0)
    upper = min(q3 + 1.5 * iqr, h - 1)
    for i in range(len(col_pts)):
        if col_pts[i] is not None and (col_pts[i] < lower or col_pts[i] > upper):
            col_pts[i] = None
    valid = [i for i, v in enumerate(col_pts) if v is not None]
    if len(valid) < 5:
        return None
    _interpolate(col_pts, valid)
    valid.sort()

    med = _median_filter([col_pts[i] for i in valid], 5)
    xs, ys = list(valid), med
    if len(ys) > 45:
        idxs = [int(i * (len(ys) - 1) / 40) for i in range(41)]
        ys = [ys[i] for i in idxs]
        xs = [xs[i] for i in idxs]
    return _pts_to_svg_path(list(zip(xs, ys)))


# ── extractors ───────────────────────────────────────────────────

def _extract_line_spark_raw(page, is_up):
    """Line chart canvas: find dominant-color line per column."""
    if Image is None:
        return None
    try:
        el = page.query_selector('.stock-chart-box canvas')
        if not el:
            canvases = page.query_selector_all('canvas')
            if canvases:
                el = canvases[0]
            else:
                return None

        raw = el.screenshot()
        img = Image.open(BytesIO(raw)).convert('RGB')
        w, h = img.size
        if w < 50 or h < 50:
            return None
        pixels = list(img.getdata())

        l = int(w * 0.10)
        r = int(w * 0.87)
        t = int(h * 0.12)
        b = int(h * 0.85)

        col_pts = _column_to_pts(pixels, w, h, l, r, t, b, is_up)
        return _post_process(col_pts, h)
    except Exception as e:
        print("  WARN: line_spark %s" % e, file=sys.stderr)
        return None


def _extract_kline_spark_raw(page):
    """K-line chart: crop chart body, LANCZOS to 80x32, find candle bottoms."""
    if Image is None:
        return None
    try:
        el = page.query_selector('.stock-chart-box canvas')
        if not el:
            return None
        raw = el.screenshot()
        img = Image.open(BytesIO(raw)).convert('RGB')
        w, h = img.size
        if w < 100 or h < 50:
            return None

        chart = img.crop((int(w * 0.08), int(h * 0.22), int(w * 0.88), int(h * 0.50)))
        tiny = chart.resize((140, 48), Image.LANCZOS)
        tp = list(tiny.getdata())
        
        closes = []
        for cx in range(140):
            last = None
            for cy in range(48):
                r, g, b = tp[cy * 80 + cx][:3]
                if r > 210 and g > 210 and b > 210:
                    continue
                if abs(r - g) < 20 and abs(g - b) < 20 and abs(r - b) < 20:
                    continue
                last = cy
            closes.append(last)

        valid = [(i, c) for i, c in enumerate(closes) if c is not None]
        if len(valid) < 5:
            return None
        xs, ys = zip(*valid)
        ys = list(_median_filter(ys, 5))
        xs = list(xs)
        # Downsample to 41 points (consistent with other SVGs)
        if len(ys) > 45:
            idxs = [int(i * (len(ys) - 1) / 40) for i in range(41)]
            ys = [ys[i] for i in idxs]
            xs = [xs[i] for i in idxs]
        return _pts_to_svg_path(list(zip(xs, ys)))
    except Exception as e:
        print("  WARN: kline_spark %s" % e, file=sys.stderr)
        return None


def _extract_tencent_spark_raw(page, is_up):
    """Tencent gu.qq.com page: find chart canvas, extract line."""
    if Image is None:
        return None
    try:
        canvases = page.query_selector_all('canvas')
        if not canvases:
            return None

        # Find the main chart canvas (first large one)
        chart_el = None
        for c in canvases:
            box = c.bounding_box()
            if box and box['width'] > 300 and box['height'] > 200:
                chart_el = c
                break
        if not chart_el:
            chart_el = canvases[0]

        raw = chart_el.screenshot()
        img = Image.open(BytesIO(raw)).convert('RGB')
        w, h = img.size

        # Tencent canvas is smaller (~525x400), crop less aggressively
        l = int(w * 0.10)
        r = int(w * 0.90)
        t = int(h * 0.12)
        b = int(h * 0.88)

        pixels = list(img.getdata())
        col_pts = _column_to_pts(pixels, w, h, l, r, t, b, is_up, bg_thresh=240)
        return _post_process(col_pts, h)
    except Exception as e:
        print("  WARN: tencent_spark %s" % e, file=sys.stderr)
        return None


# ── price extraction from page text ──────────────────────────────

def extract_page_price(text):
    """Extract price, change, chg_pct from page innerText."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    price = change = chg_pct = status = None
    for i, line in enumerate(lines):
        n = parse_num(line)
        if n and n > 0 and price is None:
            price = n
            continue
        if price is not None:
            # +-12.34+-0.56%  or  +-12.34  +-0.56%
            m = re.search(r'^([+-]\d+\.?\d*)(?:([+-]\d+\.?\d*%))', line.replace(' ', ''))
            if m and change is None:
                change = float(m.group(1))
                chg_pct = float(m.group(2).rstrip('%'))
                continue
            m = re.search(r'^(?:[+-]\d+\.?\d*\s+)?([+-]\d+\.?\d*%)', line)
            if m and chg_pct is None:
                chg_pct = float(m.group(1).rstrip('%'))
                continue
        if '交易' in line or '收盘' in line or '休市' in line or '竞价' in line:
            status = line[:30]
    # For Tencent-style pages, change may not be in text; compute from chg_pct
    if price and change is None and chg_pct is not None:
        change = round(price * chg_pct / 100, 2)
    if price and change is not None:
        result = {'price': price, 'change': change, 'chg_pct': chg_pct or 0}
        if status: result['status'] = status
        if chg_pct and abs(chg_pct) > 0.001:
            result['prev_close'] = round(price / (1 + chg_pct / 100), 2)
        elif change:
            result['prev_close'] = round(price - change, 2)
        return result
    return {}


# ── main ─────────────────────────────────────────────────────────

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

        COMMODITY_PAGES = [
            ('gold',   'https://www.futunn.com/currency/XAUUSD-FX'),
            ('wti',    'https://www.futunn.com/futures/CLMAIN-US'),
            ('brent',  'https://www.futunn.com/futures/BZMAIN-US'),
            ('usdcny', 'https://www.futunn.com/currency/USDCNH-FX'),
        ]

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

                data = extract_page_price(text)
                if data and data.get('price'):
                    is_up = data.get('change', 0) >= 0

                    if chart_type == 'kline':
                        spark_path = _extract_kline_spark_raw(page)
                    elif chart_type == 'tencent':
                        spark_path = _extract_tencent_spark_raw(page, is_up)
                    else:  # line
                        spark_path = _extract_line_spark_raw(page, is_up)

                    if spark_path:
                        data['spark_path'] = spark_path

                    indices[name] = data
                    sp_pts = len(data.get('spark_path', '').split(' ')) if data.get('spark_path') else 0
                    print("  OK %s: %s %s [%s] spark=%d up=%s" % (
                        name, data.get('price', '?'), data.get('change', '?'),
                        'T' if '交易' in data.get('status', '') else 'C',
                        sp_pts, is_up), file=sys.stderr)
                else:
                    print("  WARN: %s extract failed" % name, file=sys.stderr)
            except Exception as e:
                print("  FAIL: %s %s" % (name, str(e)[:80]), file=sys.stderr)
            page.close()

        # ── Commodity pages ──
        commodities = {}
        for name, url in COMMODITY_PAGES:
            page = context.new_page()
            try:
                print("  [%s]: %s" % (name, url), file=sys.stderr)
                page.goto(url, wait_until='domcontentloaded', timeout=12000)
                time.sleep(3)
                text = page.evaluate('() => document.body.innerText')
                data = extract_page_price(text)
                if data and data.get('price'):
                    commodities[name] = data
                    print("  OK %s: %s %s [%s]" % (name, data['price'], data['change'],
                        'T' if '交易' in data.get('status', '') else 'C'), file=sys.stderr)
                else:
                    print("  WARN: %s no price" % name, file=sys.stderr)
            except Exception as e:
                print("  FAIL: %s %s" % (name, str(e)[:60]), file=sys.stderr)
            page.close()

    if indices or commodities:
        snapshot = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'indices': indices,
        }
        if commodities:
            snapshot['commodities'] = commodities
        path = os.path.join(ARCHIVE_DIR, 'browser_snapshot.json')
        with open(path, 'w') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        print("\n  Saved: %s (%d indices, %d commodities)" % (path, len(indices), len(commodities)), file=sys.stderr)
        for k, v in indices.items():
            sp = v.get('spark_path', '')
            sp_pts = len(sp.split(' ')) if sp else 0
            print("    %s: %s %s spark=%dpts" % (
                k, v.get('price', '?'), v.get('change', '?'), sp_pts), file=sys.stderr)
        for k, v in commodities.items():
            print("    %s: %s %s" % (k, v.get('price', '?'), v.get('change', '?')), file=sys.stderr)
    else:
        print("  FAIL: no data collected", file=sys.stderr)


if __name__ == '__main__':
    run()
