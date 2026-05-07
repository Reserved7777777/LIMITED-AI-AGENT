#!/usr/bin/env python3
"""
DINGCLAW 邮件发送脚本
用法: python3 send_email.py [收件人] [主题] [正文] [--cc CC] [--attach FILE]

SMTP 配置从 .env.mail 读取:
  SMTP_HOST=smtp.example.com
  SMTP_PORT=587
  SMTP_USER=user@example.com
  SMTP_PASS=your_password
  MAIL_FROM=sender@example.com
  MAIL_FROM_NAME=DINGCLAW 办公助手
"""

import os, sys, argparse, json, ssl
from pathlib import Path

# Check script dir and agent dir for .env.mail
ENV_PATH = Path(__file__).parent / '.env.mail'
if not ENV_PATH.exists():
    ENV_PATH = Path('/root/.openclaw/agents/DINGCLAW') / '.env.mail'

def load_config():
    if not ENV_PATH.exists():
        print(json.dumps({'error': 'SMTP 未配置', 'code': 'NO_CONFIG',
            'msg': '请提供 SMTP 配置，执行: python3 send_email.py --setup'}))
        sys.exit(1)
    cfg = {}
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip()
    return cfg

def send_email(cfg, to, subject, body, cc=None, attach=None):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email import encoders
    from email.header import Header
    import email.utils

    msg = MIMEMultipart('alternative')
    from_name = str(Header(cfg.get('MAIL_FROM_NAME', ''), 'utf-8'))
    msg['From'] = email.utils.formataddr((from_name, cfg['MAIL_FROM']))
    msg['To'] = ', '.join(to) if isinstance(to, list) else to
    msg['Subject'] = str(Header(subject, 'utf-8'))
    msg['Message-ID'] = email.utils.make_msgid()
    msg['Date'] = email.utils.formatdate(localtime=True)
    if cc:
        msg['Cc'] = ', '.join(cc) if isinstance(cc, list) else cc

    # Plain text + HTML body
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    html_esc = body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    html = f'''<html><body style="font-family:'Microsoft YaHei',sans-serif;font-size:14px;line-height:1.6;">
<pre style="font-family:'Microsoft YaHei',sans-serif;font-size:14px;line-height:1.6;">{html_esc}</pre>
<p style="color:#999;font-size:12px;border-top:1px solid #ddd;padding-top:8px;">— DINGCLAW 办公助手自动发送</p>
</body></html>'''
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    # Attachment
    if attach:
        part = MIMEBase('application', 'octet-stream')
        with open(attach, 'rb') as f:
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(attach)}"')
        msg.attach(part)

    recipients = [to] if isinstance(to, str) else to
    if cc:
        recipients += [cc] if isinstance(cc, str) else cc

    use_tls = cfg.get('SMTP_PORT', '587') in ('587',)
    ctx = ssl.create_default_context() if use_tls else None

    with smtplib.SMTP(cfg['SMTP_HOST'], int(cfg.get('SMTP_PORT', 587)), timeout=15) as server:
        if use_tls:
            server.starttls(context=ctx)
        server.login(cfg['SMTP_USER'], cfg['SMTP_PASS'])
        server.sendmail(cfg['MAIL_FROM'], recipients, msg.as_string())

    return {'sent': True, 'to': msg['To'], 'subject': subject, 'recipients_count': len(recipients)}

def main():
    parser = argparse.ArgumentParser(description='DINGCLAW 邮件发送')
    parser.add_argument('to', nargs='?', help='收件人邮箱')
    parser.add_argument('subject', nargs='?', help='邮件主题')
    parser.add_argument('body', nargs='?', help='邮件正文')
    parser.add_argument('--cc', help='抄送')
    parser.add_argument('--attach', help='附件路径')
    parser.add_argument('--setup', action='store_true', help='首次配置 SMTP')
    args = parser.parse_args()

    if args.setup:
        print('''邮件发送配置指引：

1. 编辑文件 .env.mail（位于本脚本同目录）
2. 填入以下信息:

SMTP_HOST=smtp.qq.com       # SMTP 服务器
SMTP_PORT=587                # 端口 (465/587)
SMTP_USER=your@qq.com        # 邮箱账号
SMTP_PASS=your_smtp_code     # SMTP 授权码（非登录密码）
MAIL_FROM=your@qq.com        # 发件人地址
MAIL_FROM_NAME=DINGCLAW 办公助手  # 发件人显示名称

QQ邮箱 SMTP 授权码获取: 设置 → 账户 → POP3/IMAP/SMTP服务 → 生成授权码
        ''')
        return

    cfg = load_config()
    if not args.to or not args.subject or not args.body:
        parser.print_help()
        print("\n用法: python3 send_email.py 收件人 主题 正文 [--cc CC] [--attach FILE]")
        print("或:   python3 send_email.py --setup")
        sys.exit(1)

    result = send_email(cfg, args.to, args.subject, args.body, args.cc, args.attach)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
