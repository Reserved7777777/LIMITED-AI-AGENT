#!/usr/bin/env python3
"""
涨跌色自检脚本 — 验证已生成的 HTML 报告中所有指数卡和个股的涨跌色是否正确。
用法: python3 check_report_colors.py [--report /var/www/openclaw/report-YYYY-MM-DD.html]
无参数时自动检查最新报告。
"""

import re, json, sys, os, glob
from datetime import datetime

REPORT_DIR = '/var/www/openclaw'

def latest_report():
    """Find the most recent report file."""
    files = sorted(glob.glob(os.path.join(REPORT_DIR, 'report-*.html')))
    return files[-1] if files else None

def fmt_price(v):
    if v >= 10000:
        return f"{v:,.2f}"
    return f"{v:.2f}"

def check_report(path):
    print(f"📋 自检报告: {path}")
    try:
        with open(path) as f:
            html = f.read()
    except FileNotFoundError:
        print(f"❌ 文件不存在: {path}")
        return False
    
    errors = []
    total_checks = 0
    
    # 1. 指数卡检查
    print("\n🔍 一、指数卡涨跌色")
    
    # US indices: up=green(down class), down=red(up class)
    # A-share/HK: up=red(up class), down=green(down class)
    us_idx = {'S&P 500', 'NASDAQ', '道琼斯', 'VIX'}
    idx_names = ['S&P 500', 'NASDAQ', '道琼斯', 'VIX', '上证指数', '深证成指', '创业板指', '恒生科技']
    
    for name in idx_names:
        total_checks += 1
        pos = html.find(f'>{name}</span>')
        if pos < 0:
            errors.append(f'[指数] {name}: 未找到')
            continue
        
        chunk = html[pos:pos+400]
        pc = re.search(r'price (up|down)">([^<]+)', chunk)
        cc = re.search(r'change (up|down)">([^<]+)', chunk)
        
        if not pc or not cc:
            errors.append(f'[指数] {name}: 无法提取class')
            continue
        
        p_cls, price_str = pc.group(1), pc.group(2)
        c_cls = cc.group(1)
        cv = cc.group(2).strip() if cc.group(2) else ''
        is_up = cv.startswith('+')
        
        if name in us_idx:
            expected = 'down' if is_up else 'up'
        else:
            expected = 'up' if is_up else 'up' if is_up else 'down'
            expected = 'up' if is_up else 'down'
        
        if p_cls != expected or c_cls != expected:
            errors.append(f'[指数] {name}: class=p={p_cls} c={c_cls} → 应是 {expected} (涨跌={cv})')
        else:
            print(f"  ✅ {name}: {price_str} {cv} → {'green↓' if name in us_idx and is_up else 'red↑' if is_up else 'green↓'} class={p_cls}")
    
    # 2. 个股检查（所有tier）
    print("\n🔍 二、个股涨跌色")
    
    # Match all stock rows
    stock_rows = re.findall(
        r'<span class="s-sym col-sym">([^<]+)</span>\s*'
        r'<span class="s-name col-name">([^<]+)</span>\s*'
        r'<span class="s-last col-last (up|down)">([^<]+)</span>\s*'
        r'<span class="col-chg (up|down)">([^<]+)</span>\s*'
        r'<span class="col-chgp (up|down)">([^<]+)</span>',
        html
    )
    
    tier_labels = ['🔥 高位动量', '📊 中位动量', '🌱 低位价值']
    tier_idx = 0
    tier_count = 0
    
    for sym, name, p_cls, price_str, c_cls, change_str, cp_cls, chgp_str in stock_rows:
        total_checks += 1
        is_us = not sym.isdigit()
        is_up = chgp_str.startswith('+') or (not chgp_str.startswith('-') and float(chgp_str) >= 0)
        
        if is_us:
            expected = 'down' if is_up else 'up'
        else:
            expected = 'up' if is_up else 'down'
        
        if p_cls != expected or c_cls != expected or cp_cls != expected:
            errors.append(f'[个股] {sym} {name}: class=p={p_cls} c={c_cls} cp={cp_cls} → 应是 {expected}')
        
        tier_count += 1
        if tier_count <= 10:
            tag = '🇺🇸' if is_us else '🇨🇳'
            print(f"  {tag} [{sym}] {name}: {price_str} {chgp_str} → {'✅' if p_cls == expected else '❌'}")
    
    print(f"\n📊 总计检查: {total_checks} 项")
    
    if errors:
        print(f"\n❌ 发现 {len(errors)} 处错误:")
        for e in errors:
            print(f"  {e}")
        return False
    else:
        print(f"\n✅ 全部涨跌色正确")
        return True

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', '-r', help='指定报告文件路径')
    parser.add_argument('--json', action='store_true', help='JSON 格式输出')
    parser.add_argument('--cron', action='store_true', help='cron 模式（安静输出，仅异常时打印）')
    args = parser.parse_args()
    
    path = args.report or latest_report()
    if not path:
        print("❌ 未找到报告文件")
        sys.exit(1)
    
    ok = check_report(path)
    sys.exit(0 if ok else 1)
