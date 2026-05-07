#!/usr/bin/env python3
"""
A股全量数据定时发送脚本 (OAuth2版)
自动获取最新行情 + 生成Excel + 发送到QQ邮箱
使用Microsoft OAuth2 (XOAUTH2) 认证
"""

import smtplib
import ssl
import json
import os
import sys
import base64
import time
import subprocess
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "email_config.json")
TOKEN_FILE = os.path.join(SCRIPT_DIR, "outlook_token.json")

# MSAL config
MSAL_CLIENT_ID = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'
MSAL_AUTHORITY = 'https://login.microsoftonline.com/consumers'
MSAL_SCOPE = ['https://outlook.office365.com/SMTP.Send', 'offline_access']


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_valid_token():
    """Get a valid OAuth2 token (refresh if needed)"""
    if not os.path.exists(TOKEN_FILE):
        print("[ERROR] Token file not found. Run device_code_auth.py first.")
        return None
    
    with open(TOKEN_FILE, "r") as f:
        token_data = json.load(f)
    
    # Check if token is still valid (>5 min buffer)
    if 'expires_at' in token_data and token_data['expires_at'] > time.time() + 300:
        return token_data['access_token']
    
    # Try to refresh
    if 'refresh_token' in token_data:
        print("Refreshing token...")
        import msal
        app = msal.PublicClientApplication(MSAL_CLIENT_ID, authority=MSAL_AUTHORITY)
        
        result = app.acquire_token_by_refresh_token(
            token_data['refresh_token'],
            scopes=MSAL_SCOPE
        )
        
        if 'access_token' in result:
            # Save updated token
            result['expires_at'] = time.time() + result.get('expires_in', 3600)
            with open(TOKEN_FILE, "w") as f:
                json.dump(result, f)
            print("Token refreshed successfully")
            return result['access_token']
        else:
            print(f"[ERROR] Token refresh failed: {result.get('error')}")
            return None
    
    print("[ERROR] No refresh token available")
    return None


def generate_report():
    """Run the stock fetch script"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 抓取A股数据...")
    
    script = os.path.join(SCRIPT_DIR, "fetch_all_stocks_v2.py")
    if not os.path.exists(script):
        print(f"[ERROR] Script not found: {script}")
        return None
    
    result = subprocess.run(
        ["python3", script],
        capture_output=True, text=True, cwd=SCRIPT_DIR, timeout=360
    )
    
    if result.returncode != 0:
        print(f"[ERROR] Fetch failed: {result.stderr[-500:]}")
        return None
    
    # Check for xlsx or csv
    for ext in [".xlsx", ".csv"]:
        path = os.path.join(SCRIPT_DIR, f"A股全量数据{ext}")
        if os.path.exists(path):
            return path
    return None


def send_email_xoauth2(file_path, token, config):
    """Send email via XOAUTH2 with OAuth2 token"""
    now = datetime.now().strftime("%Y-%m-%d")
    
    # Build email
    msg = MIMEMultipart()
    msg["From"] = config["sender_email"]
    msg["To"] = config["recipient_email"]
    msg["Subject"] = f"{config.get('subject_prefix', 'A股全量数据')} - {now}"
    
    body = f"""
A股全量数据报表 - {now}

数据来源：东方财富实时行情
行业分类：申万行业分类
含附件Excel
"""
    msg.attach(MIMEText(body.strip(), "plain", "utf-8"))
    
    # Attach file
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        attachment = MIMEBase("application", "octet-stream")
        attachment.set_payload(f.read())
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", f"attachment; filename={filename}")
    msg.attach(attachment)
    
    # SMTP with XOAUTH2
    print(f"Connecting to Outlook SMTP...")
    server = smtplib.SMTP(config.get("smtp_server", "smtp-mail.outlook.com"),
                          config.get("smtp_port", 587), timeout=30)
    server.ehlo()
    server.starttls(context=ssl.create_default_context())
    server.ehlo()
    
    # XOAUTH2
    auth_str = f'user={config["sender_email"]}\x01auth=Bearer {token}\x01\x01'
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    code, msg_resp = server.docmd('AUTH XOAUTH2', auth_b64)
    
    if code != 235:
        print(f"[ERROR] XOAUTH2 failed: {code} {msg_resp}")
        server.quit()
        return False
    
    print(f"Sending email to {config['recipient_email']}...")
    server.sendmail(config["sender_email"], [config["recipient_email"]], msg.as_string())
    server.quit()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 邮件发送成功 ✅")
    return True


def main():
    config = load_config()
    
    print(f"=== A股全量数据自动发送 ===")
    print(f"目标: {config['recipient_email']}")
    print(f"发件: {config['sender_email']}")
    print()
    
    # Get token
    token = get_valid_token()
    if not token:
        print("[ERROR] 没有有效令牌，运行 device_code_auth.py 先获取授权")
        sys.exit(1)
    
    # Generate report
    file_path = generate_report()
    if not file_path:
        print("[ERROR] 报告生成失败")
        sys.exit(1)
    
    size_kb = os.path.getsize(file_path) / 1024
    print(f"报告: {os.path.basename(file_path)} ({size_kb:.0f} KB)")
    
    # Send email
    success = send_email_xoauth2(file_path, token, config)
    
    if success:
        # Cleanup old files
        import glob
        for f in sorted(glob.glob(os.path.join(SCRIPT_DIR, "A股全量数据.*")), 
                        key=os.path.getmtime, reverse=True)[2:]:
            os.remove(f)
        print("Done.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
