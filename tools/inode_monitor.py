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

import configparser
import logging
import os
import signal
import smtplib
import socket
import ssl
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from typing import List


def load_config(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read_files = cfg.read(path)
    if not read_files:
        raise FileNotFoundError(f"Config file not found: {path}")
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
    msg.set_content(body)

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


def check_tcp(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
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

    logging.basicConfig(level=level, handlers=handlers, format="%(asctime)s %(levelname)s %(message)s")


def main(config_path: str) -> int:
    cfg = load_config(config_path)
    setup_logging(cfg)

    check_cfg = cfg["check"]
    host = check_cfg.get("host")
    port = check_cfg.getint("port")
    interval = check_cfg.getfloat("interval", fallback=30.0)
    timeout = check_cfg.getfloat("connect_timeout", fallback=5.0)
    failure_threshold = check_cfg.getint("failure_threshold", fallback=3)
    notify_recovery = check_cfg.getboolean("notify_recovery", fallback=True)

    if not host or not port:
        logging.error("check.host and check.port must be configured in the check section")
        return 2

    subject_prefix = cfg["email"].get("subject_prefix", fallback="[iNode Monitor]")

    consecutive_failures = 0
    notified = False

    running = True

    def _signal_handler(signum, frame):
        nonlocal running
        logging.info("Received signal %s, shutting down...", signum)
        running = False

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logging.info("Starting iNode TCP monitor: %s:%s, interval=%ss, threshold=%s", host, port, interval, failure_threshold)

    while running:
        now = datetime.utcnow().isoformat() + "Z"
        ok = check_tcp(host, port, timeout)
        if ok:
            if consecutive_failures > 0:
                logging.info("Connection restored to %s:%s (previous failures=%s)", host, port, consecutive_failures)
            consecutive_failures = 0
            if notified and notify_recovery:
                subject = f"{subject_prefix} iNode client recovered: {host}:{port}"
                body = f"iNode client at {host}:{port} is reachable again as of {now}."
                send_email(cfg, subject, body)
                notified = False
        else:
            consecutive_failures += 1
            logging.warning("Connection check failed for %s:%s (consecutive=%s)", host, port, consecutive_failures)
            if consecutive_failures >= failure_threshold and not notified:
                subject = f"{subject_prefix} iNode client unreachable: {host}:{port}"
                body = (
                    f"iNode client at {host}:{port} has been unreachable for {consecutive_failures} checks.\n"
                    f"Last checked: {now}\n"
                    f"Check interval: {interval}s; connect timeout: {timeout}s; failure threshold: {failure_threshold}\n"
                )
                send_email(cfg, subject, body)
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