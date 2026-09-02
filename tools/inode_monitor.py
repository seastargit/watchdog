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
import csv
import hashlib
import hmac
import json
import logging
import os
import platform
import signal
import smtplib
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo
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


def cleanup_logs(cfg: configparser.ConfigParser) -> None:
    """Remove log files older than configured days in the configured directory.

    Config section: [log_cleanup]
      directory = /var/log/inode_monitor
      pattern = *.log        (glob pattern)
      keep_days = 7
      interval_hours = 24    (how often cleanup runs)
    """
    if not cfg.has_section("log_cleanup"):
        return
    sec = cfg["log_cleanup"]
    directory = sec.get("directory", fallback=None)
    if not directory:
        logging.debug("log_cleanup configured but no directory set; skipping cleanup")
        return
    pattern = sec.get("pattern", fallback="*.log")
    keep_days = sec.getint("keep_days", fallback=7)

    try:
        p = Path(directory)
        if not p.exists() or not p.is_dir():
            logging.warning("Log cleanup directory does not exist: %s", directory)
            return
        cutoff = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=keep_days)
        removed = 0
        # allow multiple patterns separated by comma or semicolon
        pat_value = pattern.replace(";", ",")
        patterns = [pat.strip() for pat in pat_value.split(",") if pat.strip()]
        if not patterns:
            patterns = ["*.log"]
        for pat in patterns:
            # rglob to recurse into subdirectories
            for f in p.rglob(pat):
                try:
                    if f.is_file():
                        mtime = datetime.fromtimestamp(f.stat().st_mtime, ZoneInfo("Asia/Shanghai"))
                        if mtime < cutoff:
                            f.unlink()
                            removed += 1
                            logging.info("Removed old log file: %s", str(f))
                except Exception:
                    logging.exception("Failed to consider/remove log file: %s", f)
        logging.info("Log cleanup completed in %s: removed %d files older than %d days", directory, removed, keep_days)
    except Exception:
        logging.exception("Error while performing log cleanup")


def find_pids_by_name(proc_name: str) -> List[int]:
    """Find PIDs matching proc_name. On Windows, match image name or base name. On Unix, use pgrep -f."""
    pids: List[int] = []
    try:
        if platform.system().lower() == "windows":
            out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], stderr=subprocess.DEVNULL, text=True)
            for row in csv.reader(out.splitlines()):
                if not row:
                    continue
                image = row[0].strip('"')
                pid_str = row[1].strip('"') if len(row) > 1 else ""
                try:
                    pid = int(pid_str)
                except Exception:
                    continue
                image_lower = image.lower()
                proc_lower = proc_name.lower()
                image_base = os.path.splitext(image_lower)[0]
                if proc_lower == image_lower or proc_lower == image_base or proc_lower in image_lower:
                    pids.append(pid)
        else:
            out = subprocess.check_output(["pgrep", "-f", proc_name], stderr=subprocess.DEVNULL, text=True)
            for line in out.splitlines():
                try:
                    pids.append(int(line.strip()))
                except Exception:
                    continue
    except subprocess.CalledProcessError:
        # pgrep returns non-zero when no process found; tasklist may still succeed
        pass
    except Exception:
        logging.exception("Failed to find PIDs for %s", proc_name)
    return pids


def is_process_running(proc_name: str) -> bool:
    """Return True if any PID matches the given proc_name."""
    return len(find_pids_by_name(proc_name)) > 0


def start_process(start_cmd: str) -> None:
    """Start a process using the configured command. Runs asynchronously (detached).

    On Windows open a new console window for console programs. On Unix use start_new_session to detach.
    """
    try:
        if platform.system().lower() == "windows":
            # CREATE_NEW_CONSOLE opens a new console window for the child process
            creationflags = 0
            try:
                creationflags = subprocess.CREATE_NEW_CONSOLE
            except Exception:
                creationflags = 0
            # Use shell=False to allow complex commands and ensure new console
            subprocess.Popen(start_cmd, shell=False, creationflags=creationflags)
        else:
            # start_new_session detaches the child process on Unix-like systems
            subprocess.Popen(start_cmd, shell=False, start_new_session=True)
        logging.info("Started process with command: %s", start_cmd)
    except Exception:
        logging.exception("Failed to start process: %s", start_cmd)


def stop_processes_by_name(proc_name: str) -> int:
    """Stop all processes matching proc_name. Returns the number of processes terminated."""
    terminated = 0
    pids = find_pids_by_name(proc_name)
    for pid in pids:
        try:
            if platform.system().lower() == "windows":
                subprocess.check_call(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, 15)
            terminated += 1
            logging.info("Terminated process %s (pid=%s)", proc_name, pid)
        except Exception:
            logging.exception("Failed to terminate pid %s for %s", pid, proc_name)
    return terminated


def start_processes_by_name(proc_name: str, start_cmds: str) -> int:
    """Start processes corresponding to proc_name using a list of start commands.
    start_cmds may be a single command or multiple commands separated by ';;' or ';' or '||'.
    Returns the number of commands started.
    """
    if not start_cmds:
        return 0
    # split by common separators ; or || or ;; while preserving commands that may contain semicolons
    parts = []
    if '||' in start_cmds:
        parts = [p.strip() for p in start_cmds.split('||') if p.strip()]
    else:
        parts = [p.strip() for p in start_cmds.split(';') if p.strip()]
    started = 0
    for cmd in parts:
        start_process(cmd)
        started += 1
    return started


def rename_file(src: str, dst: str, overwrite: bool = False) -> bool:
    """Rename or move a file from src to dst.

    If overwrite is True and dst exists, it will be replaced.
    Returns True on success, False on failure.
    """
    try:
        src_path = Path(src)
        dst_path = Path(dst)
        if not src_path.exists():
            logging.warning("rename_file: source does not exist: %s", src)
            return False
        if dst_path.exists():
            if overwrite:
                if dst_path.is_file():
                    dst_path.unlink()
                else:
                    logging.warning("rename_file: destination exists and is not a file: %s", dst)
                    return False
            else:
                logging.warning("rename_file: destination exists and overwrite is False: %s", dst)
                return False
        try:
            src_path.replace(dst_path)
        except Exception:
            # fallback to copy+unlink for cross-filesystem moves
            import shutil
            shutil.copy2(str(src_path), str(dst_path))
            src_path.unlink()
        logging.info("Renamed %s -> %s", src, dst)
        return True
    except Exception:
        logging.exception("Failed to rename %s -> %s", src, dst)
        return False


def monitor_processes(cfg: configparser.ConfigParser) -> None:
    """Check configured processes and start them if they're not running.

    Config section: [processes]
      name1 = start command for name1
      name2 = start command for name2
    """
    if not cfg.has_section("processes"):
        return
    sec = cfg["processes"]
    for proc_name, start_cmd in sec.items():
        proc_name = proc_name.strip()
        start_cmd = start_cmd.strip()
        if not proc_name or not start_cmd:
            continue
        try:
            if not is_process_running(proc_name):
                logging.warning("Process '%s' not running; attempting restart via: %s", proc_name, start_cmd)
                start_process(start_cmd)
            else:
                logging.debug("Process '%s' is running", proc_name)
        except Exception:
            logging.exception("Error while monitoring process %s", proc_name)


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

    # Timers for periodic tasks
    running = True

    # last cleanup and process-check timestamps
    last_cleanup = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=1)
    cleanup_interval_hours = cfg.get("log_cleanup", "interval_hours", fallback=None) if cfg.has_section("log_cleanup") else None
    if cleanup_interval_hours is not None:
        try:
            cleanup_interval_hours = int(cleanup_interval_hours)
        except Exception:
            cleanup_interval_hours = 24

    proc_check_interval = cfg.get("process_monitor", "check_interval_seconds", fallback=None) if cfg.has_section("process_monitor") else None
    if proc_check_interval is not None:
        try:
            proc_check_interval = int(proc_check_interval)
        except Exception:
            proc_check_interval = 30
    else:
        proc_check_interval = 30
    if proc_check_interval <= 0:
        proc_check_interval = 30

    # Use separate deadlines so process monitoring is independent from the global monitor interval.
    next_proc_check = datetime.now(ZoneInfo("Asia/Shanghai"))
    next_conn_check = datetime.now(ZoneInfo("Asia/Shanghai"))

    def _signal_handler(signum, frame):
        nonlocal running
        logging.info("Received signal %s, shutting down...", signum)
        running = False

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    target_desc = f"{host}:{port}" if mode != "http" else http_url
    logging.info("Starting iNode monitor in %s mode: %s, interval=%ss, threshold=%s", mode, target_desc, interval, failure_threshold)

    while running:
        now_dt = datetime.now(ZoneInfo("Asia/Shanghai"))
        now = now_dt.strftime("%Y-%m-%d %H:%M:%S %z")

        # periodic cleanup
        try:
            if cleanup_interval_hours:
                elapsed = (now_dt - last_cleanup).total_seconds() / 3600.0
                if elapsed >= cleanup_interval_hours:
                    cleanup_logs(cfg)
                    last_cleanup = now_dt
        except Exception:
            logging.exception("Error during scheduled log cleanup")

        # periodic process monitor runs on its own interval and is not tied to the network check interval
        try:
            if now_dt >= next_proc_check:
                monitor_processes(cfg)
                while next_proc_check <= now_dt:
                    next_proc_check += timedelta(seconds=proc_check_interval)
        except Exception:
            logging.exception("Error during process monitoring")

        if now_dt >= next_conn_check:
            if mode == "http":
                ok = check_http(http_url, timeout)
                target_label = http_url
            else:
                ok = check_tcp(host, port, timeout)
                target_label = f"{host}:{port}"
            check_status = "连接成功(恢复)" if ok else "连接断开（或异常）"
            if ok:
                if consecutive_failures > 0:
                    logging.info("Connection restored to %s (previous failures=%s)", target_label, consecutive_failures)
                consecutive_failures = 0
                if notified and notify_recovery:
                    subject = f"{subject_prefix} {check_status}， iNode client recovered: {target_label}"
                    body = f"iNode client at {target_label} is reachable again as of {now}."
                    send_notification(cfg, subject, body)
                    notified = False
            else:
                consecutive_failures += 1
                logging.warning("Connection check failed for %s (consecutive=%s)", target_label, consecutive_failures)
                if consecutive_failures >= failure_threshold and not notified:
                    subject = f"{subject_prefix} {check_status}， iNode client unreachable: {target_label}"
                    body = (
                        f"iNode client at {target_label} has been unreachable for {consecutive_failures} checks.\n"
                        f"Last checked: {now}\n"
                        f"Check interval: {interval}s; connect timeout: {timeout}s; failure threshold: {failure_threshold}\n"
                    )
                    send_notification(cfg, subject, body)
                    notified = True
            while next_conn_check <= now_dt:
                next_conn_check += timedelta(seconds=interval)

        next_event = min(next_proc_check, next_conn_check)
        sleep_for = max(0.2, (next_event - datetime.now(ZoneInfo("Asia/Shanghai"))).total_seconds())
        time.sleep(sleep_for)

    logging.info("Monitor stopped")
    return 0


if __name__ == "__main__":
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "inode_monitor.ini")
    try:
        raise SystemExit(main(cfg_path))
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(2)