#!/bin/bash
# 启用A股定时发送 - 选择频率后执行
# 用法: bash enable_cron.sh [daily|weekly|workday|disable]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CMD="cd ${SCRIPT_DIR} && python3 send_stock_report.py"

case "${1}" in
  daily)
    (crontab -l 2>/dev/null | grep -v send_stock_report; echo "0 8 * * * ${CMD}") | crontab -
    echo "已设置：每天 08:00 发送"
    ;;
  weekly)
    (crontab -l 2>/dev/null | grep -v send_stock_report; echo "0 8 * * 1 ${CMD}") | crontab -
    echo "已设置：每周一 08:00 发送"
    ;;
  workday)
    (crontab -l 2>/dev/null | grep -v send_stock_report; echo "0 8 * * 1-5 ${CMD}") | crontab -
    echo "已设置：工作日（周一至五）08:00 发送"
    ;;
  disable)
    (crontab -l 2>/dev/null | grep -v send_stock_report) | crontab -
    echo "已取消定时发送"
    ;;
  *)
    echo "用法: bash enable_cron.sh [daily|weekly|workday|disable]"
    echo ""
    echo "选项说明:"
    echo "  daily   - 每天 08:00 发送"
    echo "  weekly  - 每周一 08:00 发送"
    echo "  workday - 交易日（周一至五）08:00 发送"
    echo "  disable - 取消定时发送"
    echo ""
    echo "当前定时任务:"
    crontab -l 2>/dev/null | grep send_stock_report || echo "  （无）"
    ;;
esac
