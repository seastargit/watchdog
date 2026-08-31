"""
inode_monitor.py

Simple TCP-based active connection monitor for an iNode client.
Reads configuration from an INI file (default: tools/inode_monitor.ini).
When the monitored host:port is unreachable for N consecutive checks, sends an email alert to configured recipients.

Usage:
  python tools\inode_monitor.py [path/to/config.ini]

This script uses only Python standard library modules (no extra dependencies).
"""
from __future__ import annotations

import base64
import configparser
import hashlib
import hmac
import json
import logging
import os
import signal
import smtplib
import socket
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from typing import List
from zoneinfo import ZoneInfo


def load_config(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    try:
        with open(path, "r", encoding="utf-8-sig") as fp:
            cfg.read_file(fp)
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to read config {path!r}: {exc}") from exc
    return cfg


def parse_list(value: str) -> List[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def send_email(cfg: configparser.ConfigParser, subject: str, body: str) -> None:
    email_cfg = cfg["email"]
    smtp_host = email_cfg.get("smtp_host")
    smtp_port = email_cfg.getint("smtp_port", fallback=25)
    username = email_cfg.get("username", fallback=None)
    password = email_cfg.get("password", fallback=None)
    use_tls = email_cfg.getboolean("use_tls", fallback=False)
    use_ssl = email_cfg.getboolean("use_ssl", fallback=False)
    from_addr = email_cfg.get("from")
    to_addrs = parse_list(email_cfg.get("to"))

    if not smtp_host or not from_addr or not to_addrs:
        logging.error("Email not sent: smtp_host/from/to must be configured in the email section")
        return

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.set_charset("utf-8")
    msg.set_payload(body, charset="utf-8")

    try:
        if use_ssl:
            logging.debug("Connecting using SMTP_SSL to %s:%s", smtp_host, smtp_port)
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
        else:
            logging.debug("Connecting using SMTP to %s:%s", smtp_host, smtp_port)
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
        with server:
            server.set_debuglevel(0)
            if use_tls and not use_ssl:
                context = ssl.create_default_context()
                server.starttls(context=context)
            if username:
                server.login(username, password or "")
            server.send_message(msg)
        logging.info("Alert email sent to %s", to_addrs)
    except Exception as exc:
        logging.exception("Failed to send email: %s", exc)


def send_dingtalk(cfg: configparser.ConfigParser, subject: str, body: str) -> None:
    dingtalk_cfg = cfg["dingtalk"]
    webhook_url = dingtalk_cfg.get("webhook_url")
    secret = dingtalk_cfg.get("secret", fallback="")
    at_mobiles = parse_list(dingtalk_cfg.get("at_mobiles", fallback=""))
    is_at_all = dingtalk_cfg.getboolean("is_at_all", fallback=False)

    if not webhook_url:
        logging.error("DingTalk not sent: webhook_url must be configured in the dingtalk section")
        return

    content = f"{subject}\n{body}"
    payload = {
        "msgtype": "text",
        "text": {"content": content},
        "at": {
            "atMobiles": at_mobiles,
            "isAtAll": is_at_all,
        },
    }

    request_url = webhook_url
    if secret:
        timestamp = str(int(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode("utf-8"))
        request_url = f"{webhook_url}&timestamp={timestamp}&sign={sign}"

    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(request_url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_body = resp.read().decode("utf-8")
            logging.info("DingTalk notification sent: %s", response_body)
    except Exception as exc:
        logging.exception("Failed to send DingTalk notification: %s", exc)


def send_wecom(cfg: configparser.ConfigParser, subject: str, body: str) -> None:
    wecom_cfg = cfg["wecom"]
    webhook_url = wecom_cfg.get("webhook_url")
    mentioned_mobiles = parse_list(wecom_cfg.get("mentioned_mobiles", fallback=""))
    mentioned_all = wecom_cfg.getboolean("mentioned_all", fallback=False)

    if not webhook_url:
        logging.error("WeCom not sent: webhook_url must be configured in the wecom section")
        return

    content = f"**{subject}**\n{body}"
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }
    if mentioned_mobiles:
        payload["mentioned_mobile_list"] = mentioned_mobiles
    if mentioned_all:
        payload["mentioned_list"] = ["@all"]

    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_body = resp.read().decode("utf-8")
            logging.info("WeCom notification sent: %s", response_body)
    except Exception as exc:
        logging.exception("Failed to send WeCom notification: %s", exc)


def send_notification(cfg: configparser.ConfigParser, subject: str, body: str) -> None:
    if cfg.has_section("notification"):
        channel_value = cfg.get("notification", "channel", fallback="email")
    else:
        channel_value = "email"
    channels = [part.strip().lower() for part in channel_value.split(",") if part.strip()]
    if not channels:
        channels = ["email"]
    if "all" in channels:
        channels = ["email", "dingtalk", "wecom"]

    for channel in channels:
        if channel == "dingtalk":
            send_dingtalk(cfg, subject, body)
            continue
        if channel == "wecom":
            send_wecom(cfg, subject, body)
            continue
        if channel == "email":
            send_email(cfg, subject, body)
            continue
        logging.warning("Unknown notification channel '%s', defaulting to email", channel)
        send_email(cfg, subject, body)


def check_tcp(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def check_http(url: str, timeout: float) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return 200 <= response.status < 400
    except Exception:
        return False


def setup_logging(cfg: configparser.ConfigParser) -> None:
    log_section = cfg["logging"] if cfg.has_section("logging") else {}
    if isinstance(log_section, dict):
        level_name = log_section.get("level", "INFO")
        logfile = log_section.get("file")
    else:
        level_name = cfg.get("logging", "level", fallback="INFO")
        logfile = cfg.get("logging", "file", fallback=None)

    level = getattr(logging, level_name.upper(), logging.INFO)
    handlers = [logging.StreamHandler(sys.stdout)]
    if logfile:
        handlers.append(logging.FileHandler(logfile))

    logging.basicConfig(level=level, handlers=handlers, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    logging.Formatter.converter = lambda *args: datetime.now(ZoneInfo("Asia/Shanghai")).timetuple()


def main(config_path: str) -> int:
    cfg = load_config(config_path)
    setup_logging(cfg)

    check_cfg = cfg["check"]
    mode = check_cfg.get("mode", fallback="tcp").lower()
    host = check_cfg.get("host")
    port = check_cfg.getint("port", fallback=0)
    http_url = check_cfg.get("http_url", fallback=None)
    interval = check_cfg.getfloat("interval", fallback=30.0)
    timeout = check_cfg.getfloat("connect_timeout", fallback=5.0)
    failure_threshold = check_cfg.getint("failure_threshold", fallback=3)
    notify_recovery = check_cfg.getboolean("notify_recovery", fallback=True)

    if mode == "http":
        if not http_url:
            logging.error("check.http_url must be configured when mode = http")
            return 2
    else:
        if not host or not port:
            logging.error("check.host and check.port must be configured in the check section")
            return 2

    if cfg.has_section("notification"):
        subject_prefix = cfg.get("notification", "subject_prefix", fallback="[iNode Monitor]")
    elif cfg.has_section("email"):
        subject_prefix = cfg.get("email", "subject_prefix", fallback="[iNode Monitor]")
    else:
        subject_prefix = "[iNode Monitor]"

    consecutive_failures = 0
    notified = False

    running = True

    def _signal_handler(signum, frame):
        nonlocal running
        logging.info("Received signal %s, shutting down...", signum)
        running = False

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    target_desc = f"{host}:{port}" if mode != "http" else http_url
    logging.info("Starting iNode monitor in %s mode: %s, interval=%ss, threshold=%s", mode, target_desc, interval, failure_threshold)

    while running:
        now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %z")
        if mode == "http":
            ok = check_http(http_url, timeout)
            target_label = http_url
        else:
            ok = check_tcp(host, port, timeout)
            target_label = f"{host}:{port}"

        if ok:
            if consecutive_failures > 0:
                logging.info("Connection restored to %s (previous failures=%s)", target_label, consecutive_failures)
            consecutive_failures = 0
            if notified and notify_recovery:
                subject = f"{subject_prefix} iNode client recovered: {target_label}"
                body = f"iNode client at {target_label} is reachable again as of {now}."
                send_notification(cfg, subject, body)
                notified = False
        else:
            consecutive_failures += 1
            logging.warning("Connection check failed for %s (consecutive=%s)", target_label, consecutive_failures)
            if consecutive_failures >= failure_threshold and not notified:
                subject = f"{subject_prefix} iNode client unreachable: {target_label}"
                body = (
                    f"iNode client at {target_label} has been unreachable for {consecutive_failures} checks.\n"
                    f"Last checked: {now}\n"
                    f"Check interval: {interval}s; connect timeout: {timeout}s; failure threshold: {failure_threshold}\n"
                )
                send_notification(cfg, subject, body)
                notified = True

        # Sleep with interruption support
        slept = 0.0
        while running and slept < interval:
            step = min(1.0, interval - slept)
            time.sleep(step)
            slept += step

    logging.info("Monitor stopped")
    return 0


if __name__ == "__main__":
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "inode_monitor.ini")
    try:
        raise SystemExit(main(cfg_path))
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(2)