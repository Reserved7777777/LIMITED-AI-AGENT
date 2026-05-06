"""Debug script: analyze VXMAIN canvas, extract K-line close prices, generate SVG."""
from playwright.sync_api import sync_playwright
from PIL import Image
from io import BytesIO
import time, json, re

def extract_kline_close(img, crop=(0.06, 0.88, 0.15, 0.60)):
    """
    Extract closing prices from a K-line chart canvas.
    Strategy: for each column, find the bottom of the highest-density colored region
    (candle body bottom = closing price for down candles).
    """
    w, h = img.size
    pixels = list(img.getdata())
    
    l_crop = int(w * crop[0])
    r_crop = int(w * crop[1])
    t_crop = int(h * crop[2])
    b_crop = int(h * crop[3])
    
    chart_w = r_crop - l_crop
    chart_h = b_crop - t_crop
    
    # For each column, find Y position of closing price
    # Method: find the LOWEST colored pixel that is part of a HORIZONTAL group
    # K-line candles: body is a thick vertical bar, close is at body end
    # For down candles (likely): close = bottom of body
    
    col_closes = []
    for col in range(l_crop, r_crop):
        # Scan the column for colored pixels
        # Group adjacent colored pixels into segments
        segments = []  # list of (start_y, end_y, green_score, density)
        in_seg = False
        seg_start = 0
        seg_green = []
        
        for row in range(t_crop, b_crop):
            r, g, b = pixels[row * w + col][:3]
            is_bright = (r > 235 and g > 235 and b > 235)
            is_dark = (r < 25 and g < 25 and b < 25)
            is_gray = max(r,g,b)-min(r,g,b) < 15
            
            colored = not (is_bright or is_dark or is_gray)
            green_score = g - max(r, b)
            
            if colored:
                if not in_seg:
                    seg_start = row
                    seg_green = [green_score]
                    in_seg = True
                else:
                    seg_green.append(green_score)
            else:
                if in_seg:
                    seg_end = row - 1
                    density = len(seg_green)
                    avg_green = sum(seg_green) / len(seg_green) if seg_green else 0
                    segments.append((seg_start, seg_end, avg_green, density))
                    in_seg = False
        
        if in_seg:
            seg_end = b_crop - 1
            density = len(seg_green)
            avg_green = sum(seg_green) / len(seg_green) if seg_green else 0
            segments.append((seg_start, seg_end, avg_green, density))
        
        if not segments:
            col_closes.append(None)
            continue
        
        # Find the best segment: prefer green, high density (body), bottom edge = close
        # Longer segments with high density = candle body
        segments.sort(key=lambda s: -s[3])  # sort by density desc
        best = segments[0]  # highest density = most likely candle body
        
        # But if it's short (wick), use the longest segment instead
        if best[3] < 3 and len(segments) > 1:
            segments.sort(key=lambda s: -(s[1]-s[0]))
            best = segments[0]
        
        close_y = best[1]  # bottom of best segment = close (for down candles)
        col_closes.append(close_y)
    
    return col_closes, chart_w, chart_h, l_crop, r_crop, t_crop


def closes_to_svg(closes, l_crop, chart_w, target_pts=40):
    """Convert per-column closes to SVG path."""
    # Remove None
    valid = [(i, c) for i, c in enumerate(closes) if c is not None]
    if len(valid) < 5:
        return None, 0
    
    # Group into buckets
    xs, ys_raw = zip(*valid)
    n_buckets = target_pts
    bucket_size = max(1, len(valid) // n_buckets)
    
    sampled = []
    for bi in range(n_buckets):
        start = bi * bucket_size
        end = min((bi + 1) * bucket_size, len(valid))
        bucket = valid[start:end]
        if not bucket:
            continue
        bucket_ys = [b[1] for b in bucket]
        bucket_ys.sort()
        median_y = bucket_ys[len(bucket_ys)//2]
        median_x = bucket[len(bucket)//2][0]
        sampled.append((median_x, median_y))
    
    # Map to SVG viewBox
    raw_xs = [p[0] for p in sampled]
    raw_ys = [p[1] for p in sampled]
    min_y, max_y = min(raw_ys), max(raw_ys)
    y_range = max_y - min_y if max_y != min_y else 1
    min_x, max_x = min(raw_xs), max(raw_xs)
    x_range = max_x - min_x if max_x != min_x else 1
    
    def nx(sx): return 2 + (sx - min_x) / x_range * 76
    def ny(sy): return 26 - (sy - min_y) / y_range * 26  # y: 0-26
    
    path = 'M%.1f,%.1f' % (nx(sampled[0][0]), ny(sampled[0][1]))
    for col, row in sampled[1:]:
        yv = ny(row)
        if yv < -3.5: yv = -3.5
        if yv > 27.5: yv = 27.5
        path += ' L%.1f,%.1f' % (nx(col), yv)
    
    coords = re.findall(r'([\d.]+),([\d.\-]+)', path)
    ys = [float(c[1]) for c in coords]
    
    return path, len(sampled), (min(ys), max(ys)), (min_y, max_y)


# ===== MAIN =====
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp('http://localhost:9222')
    context = browser.contexts[0]
    page = context.new_page()
    page.goto('https://www.futunn.com/futures/VXMAIN-US', wait_until='domcontentloaded', timeout=15000)
    time.sleep(4)
    
    el = page.query_selector('.stock-chart-box canvas')
    raw = el.screenshot()
    img = Image.open(BytesIO(raw))
    w, h = img.size
    
    # Method 2: direct bottom-of-highest-green-region
    # Skip the complex segment analysis, just look for the LOWEST green-ish pixel
    # in each column that has significant horizontal width
    
    # Simpler approach: for each column, find the LOWEST pixel that:
    # 1. Is NOT background (bright gray/dark)
    # 2. Has more green than red (g - r > 30)
    # Only look in chart area: y = 80-240, x = 5%-85%
    l_crop = int(w * 0.05)
    r_crop = int(w * 0.85)
    t_crop = int(h * 0.15)
    b_crop = int(h * 0.55)  # stop before volume bars
    
    pixels_rgb = list(img.getdata())
    
    # VIX is DOWN → candles are GREEN → close = bottom of green body
    # Close is at the LOWEST point where g-r > 30 and not a thin line
    
    # For robustness: scan for green-ish pixels, use the LOWEST green pixel per column
    # as a proxy for close. Skip columns where no green pixels found.
    
    closes = []
    for col in range(l_crop, r_crop):
        lowest_green = None
        for row in range(t_crop, b_crop):
            r, g, b = pixels_rgb[row * w + col][:3]
            is_bright = (r > 235 and g > 235 and b > 235)
            is_dark = (r < 30 and g < 30 and b < 30)
            green_score = g - max(r, b)
            if not (is_bright or is_dark) and green_score > 20:
                lowest_green = row  # overwrite as we go down
        closes.append(lowest_green)
    
    valid = [(i, c) for i, c in enumerate(closes) if c is not None]
    print('Method A (lowest green pixel per column): %d valid columns' % len(valid))
    
    if valid:
        raw_ys = [v[1] for v in valid]
        print('  Raw Y range: %d to %d' % (min(raw_ys), max(raw_ys)))
        path, npts, y_range_svg, y_raw_range = closes_to_svg(closes, l_crop, r_crop-l_crop, target_pts=73)
        if path:
            coords = re.findall(r'([\d.]+),([\d.\-]+)', path)
            ys = [float(c[1]) for c in coords]
            print('  SVG: %d pts, Y=[%.1f,%.1f], edge=%d' % (
                npts, min(ys), max(ys), sum(1 for y in ys if y <= -3.5 or y >= 27.5)))
            print('  Path: %s...' % path[:150])
    
    # Also try Tencent spot VIX for comparison
    import urllib.request
    try:
        resp = urllib.request.urlopen(
            urllib.request.Request('http://qt.gtimg.cn/q=usVIX',
                headers={'User-Agent': 'Mozilla/5.0'}), timeout=5)
        text = resp.read().decode('gbk', errors='replace')
        print('\nTencent VIX spot for comparison: %s' % text[:200])
    except Exception as e:
        print('Tencent VIX error: %s' % e)
    
    page.close()
