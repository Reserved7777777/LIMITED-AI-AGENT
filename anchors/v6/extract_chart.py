#!/usr/bin/env python3
"""
Extract sparkline path from futunn canvas chart pixels.
"""
import json, sys, base64, io, struct, math

def extract_spark_from_pixels(w, h, pixels, target_points=40):
    """
    Extract the chart line from canvas pixel data.
    pixels: flat list of [r,g,b,a, r,g,b,a,...]
    Returns SVG path string for a sparkline.
    """
    # Find the actual chart area (skip borders/grid labels)
    # Scan columns for colored pixels (not white, not gray grid)
    col_points = []
    for x in range(w):
        best_y = -1
        best_score = 0
        for y in range(h):
            idx = (y * w + x) * 4
            if idx + 3 >= len(pixels):
                continue
            r = pixels[idx]
            g = pixels[idx+1]
            b = pixels[idx+2]
            a = pixels[idx+3]
            if a < 128:
                continue
            # Skip white background
            if r > 240 and g > 240 and b > 240:
                continue
            # Skip dark gray grid lines
            is_grid = abs(r-g) < 20 and abs(g-b) < 20 and r < 180
            if is_grid:
                continue
            # Skip very dark pixels (chart border/labels)
            if r < 30 and g < 30 and b < 30:
                continue
            # Calculate color intensity (how "colored" is this pixel)
            color_intensity = abs(r - g) + abs(g - b) + abs(r - b)
            if color_intensity > 40:
                if color_intensity > best_score:
                    best_score = color_intensity
                    best_y = y
    
        if best_y >= 0:
            col_points.append((x, best_y, best_score))
    
    if len(col_points) < 5:
        # Fallback: try including gray-ish pixels
        for x in range(w):
            best_y = -1
            best_score = 0
            for y in range(h):
                idx = (y * w + x) * 4
                if idx + 3 >= len(pixels):
                    continue
                r = pixels[idx]
                g = pixels[idx+1]
                b = pixels[idx+2]
                a = pixels[idx+3]
                if a < 128:
                    continue
                if r > 240 and g > 240 and b > 240:
                    continue
                brightness = r + g + b
                if 50 < brightness < 700 and not (abs(r-g) < 10 and abs(g-b) < 10 and r > 100):
                    if brightness > best_score:
                        best_score = brightness
                        best_y = y
            if best_y >= 0:
                col_points.append((x, best_y, best_score))
    
    if len(col_points) < 5:
        return None
    
    # Group by x, take the best score at each x
    x_groups = {}
    for x, y, score in col_points:
        if x not in x_groups or score > x_groups[x][1]:
            x_groups[x] = (y, score)
    
    sorted_x = sorted(x_groups.keys())
    ys = [x_groups[x][0] for x in sorted_x]
    xs = list(sorted_x)
    
    # Downsample to target_points
    if len(ys) > target_points:
        indices = [int(i * (len(ys) - 1) / (target_points - 1)) for i in range(target_points)]
        sampled_ys = [ys[i] for i in indices]
        sampled_xs = [xs[i] for i in indices]
    else:
        sampled_ys = ys
        sampled_xs = xs
    
    # Normalize to SVG sparkline viewBox (0-80 x, 0-28 y, inverted)
    min_y = min(sampled_ys)
    max_y = max(sampled_ys)
    y_range = max_y - min_y if max_y != min_y else 1
    
    spark_width = 80
    spark_height = 28
    margin_x = 2  # 2px margin on each side
    
    # Map x: (x - min_sampled_x) / (max_sampled_x - min_sampled_x) * (spark_width - 2*margin_x) + margin_x
    min_sx = min(sampled_xs)
    max_sx = max(sampled_xs)
    x_range = max_sx - min_sx if max_sx != min_sx else 1
    
    points = []
    for i, (sx, sy) in enumerate(zip(sampled_xs, sampled_ys)):
        nx = margin_x + (sx - min_sx) / x_range * (spark_width - 2 * margin_x)
        # Invert Y: canvas y=0 is top, spark y=0 is top too (we keep same orientation)
        ny = (sy - min_y) / y_range * spark_height
        points.append((nx, ny))
    
    # Build SVG path
    path_parts = [f'M{points[0][0]:.1f},{points[0][1]:.1f}']
    for p in points[1:]:
        path_parts.append(f'L{p[0]:.1f},{p[1]:.1f}')
    
    return ' '.join(path_parts)


def extract_canvas_path(base64_png, target_points=40):
    """Extract sparkline path from a base64-encoded canvas PNG."""
    # Decode PNG
    png_data = base64.b64decode(base64_png)
    
    # Use PIL if available
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png_data))
        w, h = img.size
        pixels = list(img.getdata())
        # Flatten RGBA
        flat_pixels = []
        for px in pixels:
            if len(px) == 4:
                flat_pixels.extend(px)
            elif len(px) == 3:
                flat_pixels.extend([px[0], px[1], px[2], 255])
        return extract_spark_from_pixels(w, h, flat_pixels, target_points)
    except ImportError:
        pass
    
    # Manual PNG parse fallback for basic cases
    # (simplified - just use the raw pixel data structure)
    return None


if __name__ == '__main__':
    # Test with a sample
    import re
    with open(sys.argv[1]) as f:
        data = json.load(f)
    px = data.get('pixels', [])
    w = data.get('w', 0)
    h = data.get('h', 0)
    path = extract_spark_from_pixels(w, h, px, 40)
    if path:
        print(path)
    else:
        print('FAILED')
        sys.exit(1)
