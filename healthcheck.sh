#!/usr/bin/env bash
# 全局自检脚本 - 每10分钟由 cron 触发
# 职责：检查所有端口/服务 → 发现问题逐级修复 → 记录日志
set -euo pipefail

LOG=/tmp/healthcheck.log
NOW=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "[$NOW] $*" >> "$LOG"; }
fail() { log "❌ $*"; return 1; }
ok()   { log "✅ $*"; }

# ============================================================
# 1. 端口存活检查
# ============================================================
STATUS=0

check_port() {
    local label=$1 port=$2
    if ss -tlnp | grep -q ":$port "; then
        ok "$label ($port) 监听中"
        return 0
    else
        fail "$label ($port) 未监听"
        return 1
    fi
}

# 2. Gateway HTTP 响应检查（关键）
check_gateway() {
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 5 http://127.0.0.1:31222/7ce8fe15ad775ae9f2d04bce/ 2>/dev/null) || true
    if [[ "$code" == "200" ]]; then
        ok "Gateway HTTP 响应 200"
        return 0
    else
        fail "Gateway HTTP 响应异常 (code=$code)"
        return 1
    fi
}

# 3. nginx 静态文件服务检查
check_nginx() {
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 5 http://127.0.0.1/static/ 2>/dev/null || true)
    if [[ "$code" != "000" ]]; then
        ok "nginx HTTP 响应 $code"
        return 0
    fi
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 5 http://127.0.0.1/ 2>/dev/null || true)
    if [[ "$code" != "000" ]]; then
        ok "nginx HTTP 响应 $code"
        return 0
    fi
    fail "nginx 无响应"
    return 1
}

# 4. Chrome 浏览器检查（browser automation）
check_chrome() {
    if ss -tlnp | grep -q ":9222 "; then
        local code
        code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 5 http://127.0.0.1:9222/json/version 2>/dev/null || true)
        if [[ "$code" == "200" ]]; then
            ok "Chrome DevTools 响应 200"
            return 0
        else
            fail "Chrome DevTools 异常 (code=$code)"
            return 1
        fi
    else
        fail "Chrome 9222 未监听"
        return 1
    fi
}

# 5. 卡死会话检查（只查最近 10 分钟的日志）
check_stuck_sessions() {
    local now_hour now_min ten_min_ago_hour ten_min_ago_min
    now_hour=$(date '+%H')
    now_min=$(date '+%M')
    
    # 计算10分钟前的时间
    local total_min=$((10#${now_hour} * 60 + 10#${now_min} - 10))
    if [[ "$total_min" -lt 0 ]]; then total_min=0; fi
    ten_min_ago_hour=$((total_min / 60))
    ten_min_ago_min=$((total_min % 60))
    local since_fmt
    since_fmt=$(printf "T%02d:%02d" "$ten_min_ago_hour" "$ten_min_ago_min")
    
    # 找到 10 分钟内最严重的 stuck session
    local stuck
    stuck=$(grep "stuck session" /tmp/openclaw/openclaw-*.log 2>/dev/null | grep -F "$since_fmt" | grep "age=[5-9][0-9][0-9]s" | tail -1 || true)
    if [[ -n "$stuck" ]]; then
        local age
        age=$(echo "$stuck" | grep -oP 'age=\K[0-9]+')
        if [[ -n "$age" && "$age" -ge 300 ]]; then
            fail "发现卡死会话 (age=${age}s): $(echo "$stuck" | grep -oP 'sessionKey=\S+' | head -1)"
            local session_id
            session_id=$(echo "$stuck" | grep -oP 'sessionId=\K\w+')
            if [[ -n "$session_id" ]]; then
                log "  尝试 kill session: $session_id"
                openclaw sessions kill "$session_id" 2>/dev/null && log "  ✅ session $session_id 已终止" || log "  ⚠️  session kill 失败(可能已结束)"
            fi
            return 1
        fi
    fi
    
    # 统计 10 分钟内 stuck 总数（age>=120s）
    local stuck_count
    stuck_count=$(grep "stuck session" /tmp/openclaw/openclaw-*.log 2>/dev/null | grep -F "$since_fmt" | grep -oP 'age=\K[0-9]+' | awk '$1>=120' | wc -l || true)
    if [[ "$stuck_count" -ge 10 ]]; then
        fail "最近10分钟大量卡死: $stuck_count 条 stuck 日志"
        return 1
    fi
    ok "无卡死会话"
    return 0
}

# 6. 系统资源检查
check_resources() {
    local mem_avail mem_total
    mem_avail=$(free -m | awk '/Mem:/{print $7}')
    mem_total=$(free -m | awk '/Mem:/{print $2}')
    local mem_pct=$(( (mem_total - mem_avail) * 100 / mem_total ))
    
    local disk_pct
    disk_pct=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
    
    local load load_raw cpus
    load=$(cat /proc/loadavg)
    load_raw=$(awk '{print int($1)}' /proc/loadavg)
    cpus=$(nproc)
    
    local issues=""
    if [[ "$mem_pct" -ge 90 ]]; then issues+="内存${mem_pct}% "; fi
    if [[ "$disk_pct" -ge 90 ]]; then issues+="磁盘${disk_pct}% "; fi
    if [[ "$load_raw" -ge $((cpus * 3)) ]]; then issues+="负载($load) "; fi
    
    if [[ -n "$issues" ]]; then
        fail "资源告警: $issues"
        return 1
    fi
    ok "资源正常 (mem=${mem_pct}% disk=${disk_pct}% load=$(awk '{print $1" "$2" "$3}' /proc/loadavg))"
    return 0
}

# ============================================================
# 修复逻辑（逐级升级）
# ============================================================
fix_gateway() {
    log "🔄 修复: 重启 Gateway..."
    openclaw gateway restart 2>&1 >> "$LOG"
    sleep 5
    if check_gateway; then
        log "✅ Gateway 重启成功"
        return 0
    else
        log "❌ Gateway 重启失败，准备服务器重启..."
        return 1
    fi
}

fix_chrome() {
    log "🔄 修复: 重启 Chrome..."
    pkill -f "chrome.*remote-debugging-port=9222" 2>/dev/null || true
    sleep 2
    # Start new chrome in background
    cd /tmp
    nohup /root/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome \
        --no-sandbox --remote-debugging-port=9222 --ozone-platform=headless --disable-gpu \
        --user-data-dir=/root/.openclaw/browser-existing-session \
        > /dev/null 2>&1 &
    local pid=$!
    sleep 3
    if kill -0 "$pid" 2>/dev/null; then
        log "✅ Chrome 已重启 (PID $pid)"
        return 0
    fi
    log "❌ Chrome 重启失败"
    return 1
}

fix_nginx() {
    log "🔄 修复: 重启 nginx..."
    systemctl restart nginx 2>&1 >> "$LOG" || true
    sleep 2
    if systemctl is-active --quiet nginx; then
        log "✅ nginx 已重启"
        return 0
    fi
    log "❌ nginx 重启失败"
    return 1
}

force_reboot() {
    log "💀 严重异常，执行服务器重启..."
    sync
    reboot
}

# ============================================================
# 主流程
# ============================================================
{
    echo "========== 自检开始 [$NOW] =========="
} >> "$LOG"

gateway_ok=true; nginx_ok=true; chrome_ok=true

check_port "Gateway" 31222 || gateway_ok=false
check_port "Gateway(内部)" 31224 || true
check_port "nginx(HTTP)" 80 || nginx_ok=false
check_port "nginx(HTTPS)" 443 || nginx_ok=false
check_port "Chrome" 9222 || chrome_ok=false
check_gateway || gateway_ok=false
check_nginx || nginx_ok=false
check_chrome || chrome_ok=false
check_resources || true
check_stuck_sessions || true

# 修复逻辑
NEEDS_REBOOT=false

if ! $gateway_ok; then
    if ! fix_gateway; then
        NEEDS_REBOOT=true
    fi
fi

if ! $nginx_ok; then
    fix_nginx || true
fi

if ! $chrome_ok; then
    fix_chrome || true
fi

if $NEEDS_REBOOT; then
    force_reboot
fi

{
    echo "========== 自检完成 =========="
    echo ""
} >> "$LOG"

# 保留日志最后 200 行
tail -n 200 "$LOG" > /tmp/healthcheck.tmp && mv /tmp/healthcheck.tmp "$LOG"

exit $STATUS
