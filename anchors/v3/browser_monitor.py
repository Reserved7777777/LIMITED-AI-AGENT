#!/usr/bin/env python3
"""
browser_monitor.py — Monitor futunn index pages via Playwright + existing Chrome CDP.
Extracts real-time data + actual chart sparkline from canvas.
"""
import json, os, sys, re, time
from datetime import datetime

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
    # VIX spot override
    if 'VIX' in key:
        v = re.search(r'\.VIX\s*([\d.]+)\s*([+-][\d.]+)\s*([+-][\d.]+)%', text)
        if v and result.get('price'):
            spot_price = float(v.group(1))
            spot_change = float(v.group(2))
            spot_pct = float(v.group(3).replace('%',''))
            result['price'] = spot_price
            result['change'] = spot_change
            result['chg_pct'] = spot_pct
            result['source'] = 'futunn_browser_vix'
            if spot_pct != 0:
                result['prev_close'] = round(spot_price / (1 + spot_pct/100), 2)
            else:
                result['prev_close'] = round(spot_price - spot_change, 2)
    return result if result.get('price') else None


def extract_spark_from_canvas(page, target_points=40):
    """Extract chart line from futunn canvas as SVG sparkline path."""
    try:
        result_json = page.evaluate("""(targetPts) => {
            var c = document.querySelector('.stock-chart-box canvas') || document.querySelector('canvas');
            if (!c) return null;
            var ctx = c.getContext('2d');
            var w = c.width, h = c.height;
            var imgData = ctx.getImageData(0, 0, w, h);
            var px = imgData.data;
            var pts = [];
            for (var x = 0; x < w; x++) {
                var bestY = -1, bestScore = 0;
                for (var y = 0; y < h; y++) {
                    var i = (y * w + x) * 4;
                    var r = px[i], g = px[i+1], b = px[i+2], a = px[i+3];
                    if (a < 128) continue;
                    if (r > 235 && g > 235 && b > 235) continue;
                    if (Math.abs(r-g) < 20 && Math.abs(g-b) < 20 && r < 180) continue;
                    var score = Math.abs(r-g) + Math.abs(g-b);
                    if (score > 50 && score > bestScore) { bestScore = score; bestY = y; }
                }
                if (bestY >= 0) pts.push({x: x, y: bestY});
            }
            if (pts.length < 5) {
                for (var x = 0; x < w; x++) {
                    var bestY = -1, bestB = 0;
                    for (var y = 0; y < h; y++) {
                        var i = (y * w + x) * 4;
                        var r = px[i], g = px[i+1], b = px[i+2], a = px[i+3];
                        if (a < 128 || (r > 235 && g > 235 && b > 235)) continue;
                        var bri = r + g + b;
                        if (bri > 50 && bri < 700 && bri > bestB) { bestB = bri; bestY = y; }
                    }
                    if (bestY >= 0) pts.push({x: x, y: bestY});
                }
            }
            return JSON.stringify(pts);
        }""")
    except Exception:
        return None
    if not result_json:
        return None
    try:
        line_pts = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not line_pts or len(line_pts) < 5:
        return None
    # Group by x
    x_groups = {}
    for pt in line_pts:
        x, y = pt['x'], pt['y']
        if x not in x_groups:
            x_groups[x] = y
    xs = sorted(x_groups.keys())
    ys = [x_groups[x] for x in xs]
    # Downsample
    if len(ys) > target_points:
        indices = [int(i * (len(ys) - 1) / (target_points - 1)) for i in range(target_points)]
        sampled_ys = [ys[i] for i in indices]
        sampled_xs = [xs[i] for i in indices]
    else:
        sampled_ys, sampled_xs = ys, xs
    # Normalize to sparkline viewBox (80x28)
    min_y, max_y = min(sampled_ys), max(sampled_ys)
    y_range = max_y - min_y if max_y != min_y else 1
    min_sx, max_sx = min(sampled_xs), max(sampled_xs)
    x_range = max_sx - min_sx if max_sx != min_sx else 1
    margin = 2
    def nx(sx): return margin + (sx - min_sx) / x_range * (80 - 2 * margin)
    def ny(sy): return (sy - min_y) / y_range * 28
    path = 'M{:.1f},{:.1f}'.format(nx(sampled_xs[0]), ny(sampled_ys[0]))
    for sx, sy in zip(sampled_xs[1:], sampled_ys[1:]):
        path += ' L{:.1f},{:.1f}'.format(nx(sx), ny(sy))
    return path


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
