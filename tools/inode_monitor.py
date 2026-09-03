"""
inode_monitor.py

Simple monitor for an iNode client with active reachability checks.
Reads configuration from an INI file (default: tools/inode_monitor.ini).
When the monitored host:port or URL is unreachable for N consecutive checks,
sends notifications through the configured channels.

Usage:
  python tools\inode_monitor.py [path/to/config.ini]

This script uses only Python standard library modules.
"""
from __future__ import annotations

import base64
import configparser
import threading
import csv
import hashlib
import hmac
import json
import logging
import os
import platform
import shutil
import signal
import smtplib
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import List

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 compatibility
    ZoneInfo = None

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai") if ZoneInfo is not None else timezone(timedelta(hours=8))


def now_in_china() -> datetime:
    return datetime.now(SHANGHAI_TZ)


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
    return [p.strip() for p in (value or "").split(",") if p.strip()]


class NotificationService:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg

    def send_email(self, subject: str, body: str) -> None:
        if not self.cfg.has_section("email"):
            logging.error("Email not sent: email configuration section is missing")
            return

        email_cfg = self.cfg["email"]
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

    def send_dingtalk(self, subject: str, body: str) -> None:
        if not self.cfg.has_section("dingtalk"):
            logging.error("DingTalk not sent: dingtalk configuration section is missing")
            return

        dingtalk_cfg = self.cfg["dingtalk"]
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
            "at": {"atMobiles": at_mobiles, "isAtAll": is_at_all},
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
            req = urllib.request.Request(
                request_url,
                data=data,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                response_body = resp.read().decode("utf-8")
                logging.info("DingTalk notification sent: %s", response_body)
        except Exception as exc:
            logging.exception("Failed to send DingTalk notification: %s", exc)

    def send_wecom(self, subject: str, body: str) -> None:
        if not self.cfg.has_section("wecom"):
            logging.error("WeCom not sent: wecom configuration section is missing")
            return

        wecom_cfg = self.cfg["wecom"]
        webhook_url = wecom_cfg.get("webhook_url")
        mentioned_mobiles = parse_list(wecom_cfg.get("mentioned_mobiles", fallback=""))
        mentioned_all = wecom_cfg.getboolean("mentioned_all", fallback=False)

        if not webhook_url:
            logging.error("WeCom not sent: webhook_url must be configured in the wecom section")
            return

        content = f"**{subject}**\n{body}"
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        if mentioned_mobiles:
            payload["mentioned_mobile_list"] = mentioned_mobiles
        if mentioned_all:
            payload["mentioned_list"] = ["@all"]
            payload["mentioned_mobile_list"] = ["@all"]

        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                response_body = resp.read().decode("utf-8")
                logging.info("WeCom notification sent: %s", response_body)
        except Exception as exc:
            logging.exception("Failed to send WeCom notification: %s", exc)

    def send_notification(self, subject: str, body: str) -> None:
        if self.cfg.has_section("notification"):
            channel_value = self.cfg.get("notification", "channel", fallback="email")
        else:
            channel_value = "email"

        channels = [part.strip().lower() for part in channel_value.split(",") if part.strip()]
        if not channels:
            channels = ["email"]
        if "all" in channels:
            channels = ["email", "dingtalk", "wecom"]

        for channel in channels:
            if channel == "dingtalk":
                self.send_dingtalk(subject, body)
            elif channel == "wecom":
                self.send_wecom(subject, body)
            elif channel == "email":
                self.send_email(subject, body)
            else:
                logging.warning("Unknown notification channel '%s', defaulting to email", channel)
                self.send_email(subject, body)


class LogCleaner:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg

    def cleanup_logs(self) -> None:
        if not self.cfg.has_section("log_cleanup"):
            return

        sec = self.cfg["log_cleanup"]
        directory = sec.get("directory", fallback=None)
        if not directory:
            logging.debug("log_cleanup configured but no directory set; skipping cleanup")
            return

        pattern = sec.get("pattern", fallback="*.log")
        keep_days = sec.getint("keep_days", fallback=7)

        try:
            root = Path(directory)
            if not root.exists() or not root.is_dir():
                logging.warning("Log cleanup directory does not exist: %s", directory)
                return

            cutoff = now_in_china() - timedelta(days=keep_days)
            removed = 0
            pat_value = pattern.replace(";", ",")
            patterns = [pat.strip() for pat in pat_value.split(",") if pat.strip()]
            if not patterns:
                patterns = ["*.log"]

            for pat in patterns:
                for f in root.rglob(pat):
                    try:
                        if f.is_file():
                            mtime = datetime.fromtimestamp(f.stat().st_mtime, SHANGHAI_TZ)
                            if mtime < cutoff:
                                f.unlink()
                                removed += 1
                                logging.info("Removed old log file: %s", str(f))
                    except Exception:
                        logging.exception("Failed to consider/remove log file: %s", f)

            logging.info("Log cleanup completed in %s: removed %d files older than %d days", directory, removed, keep_days)
        except Exception:
            logging.exception("Error while performing log cleanup")


class ProcessManager:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg

    def find_pids_by_name(self, proc_name: str) -> List[int]:
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
            pass
        except Exception:
            logging.exception("Failed to find PIDs for %s", proc_name)
        return pids

    def is_process_running(self, proc_name: str) -> bool:
        return len(self.find_pids_by_name(proc_name)) > 0

    def start_process(self, start_cmd: str) -> None:
        try:
            if platform.system().lower() == "windows":
                creationflags = 0
                try:
                    creationflags = subprocess.CREATE_NEW_CONSOLE
                except Exception:
                    creationflags = 0
                subprocess.Popen(start_cmd, shell=False, creationflags=creationflags)
            else:
                subprocess.Popen(start_cmd, shell=False, start_new_session=True)
            logging.info("Started process with command: %s", start_cmd)
        except Exception:
            logging.exception("Failed to start process: %s", start_cmd)

    def stop_processes_by_name(self, proc_name: str) -> int:
        terminated = 0
        pids = self.find_pids_by_name(proc_name)
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

    def start_processes_by_name(self, proc_name: str, start_cmds: str) -> int:
        if not start_cmds:
            return 0

        if "||" in start_cmds:
            parts = [p.strip() for p in start_cmds.split("||") if p.strip()]
        else:
            parts = [p.strip() for p in start_cmds.split(";") if p.strip()]

        started = 0
        for cmd in parts:
            self.start_process(cmd)
            started += 1
        return started

    def rename_file(self, src: str, dst: str, overwrite: bool = False) -> bool:
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
                shutil.copy2(str(src_path), str(dst_path))
                src_path.unlink()
            logging.info("Renamed %s -> %s", src, dst)
            return True
        except Exception:
            logging.exception("Failed to rename %s -> %s", src, dst)
            return False

    def monitor_processes(self) -> None:
        if not self.cfg.has_section("processes"):
            return

        sec = self.cfg["processes"]
        for proc_name, start_cmd in sec.items():
            proc_name = proc_name.strip()
            start_cmd = start_cmd.strip()
            if not proc_name or not start_cmd:
                continue

            try:
                if not self.is_process_running(proc_name):
                    logging.warning("Process '%s' not running; attempting restart via: %s", proc_name, start_cmd)
                    self.start_processes_by_name(proc_name, start_cmd)
                else:
                    logging.debug("Process '%s' is running", proc_name)
            except Exception:
                logging.exception("Error while monitoring process %s", proc_name)


class ConnectionChecker:
    @staticmethod
    def check_tcp(host: str, port: int, timeout: float) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    @staticmethod
    def check_http(url: str, timeout: float) -> bool:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return 200 <= response.status < 400
        except Exception:
            return False


def setup_logging(cfg: configparser.ConfigParser) -> None:
    if cfg.has_section("logging"):
        log_section = cfg["logging"]
        level_name = log_section.get("level", "INFO")
        logfile = log_section.get("file")
    else:
        level_name = "INFO"
        logfile = None

    level = getattr(logging, level_name.upper(), logging.INFO)
    handlers = [logging.StreamHandler(sys.stdout)]
    if logfile:
        handlers.append(logging.FileHandler(logfile))

    logging.basicConfig(level=level, handlers=handlers, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    logging.Formatter.converter = lambda *args: now_in_china().timetuple()


class MonitorController:
    def __init__(self, config_path: str):
        self.cfg = load_config(config_path)
        self.service_mode = False
        self.stop_event = threading.Event()
        setup_logging(self.cfg)

        self.check_cfg = self.cfg["check"]
        self.mode = self.check_cfg.get("mode", fallback="tcp").lower()
        self.host = self.check_cfg.get("host")
        self.port = self.check_cfg.getint("port", fallback=0)
        self.http_url = self.check_cfg.get("http_url", fallback=None)
        self.interval = self.check_cfg.getfloat("interval", fallback=30.0)
        self.timeout = self.check_cfg.getfloat("connect_timeout", fallback=5.0)
        self.failure_threshold = self.check_cfg.getint("failure_threshold", fallback=3)
        self.notify_recovery = self.check_cfg.getboolean("notify_recovery", fallback=True)

        if self.mode == "http":
            if not self.http_url:
                raise ValueError("check.http_url must be configured when mode = http")
        else:
            if not self.host or not self.port:
                raise ValueError("check.host and check.port must be configured in the check section")

        if self.cfg.has_section("notification"):
            self.subject_prefix = self.cfg.get("notification", "subject_prefix", fallback="[iNode Monitor]")
        elif self.cfg.has_section("email"):
            self.subject_prefix = self.cfg.get("email", "subject_prefix", fallback="[iNode Monitor]")
        else:
            self.subject_prefix = "[iNode Monitor]"

        self.notification_service = NotificationService(self.cfg)
        self.log_cleaner = LogCleaner(self.cfg)
        self.process_manager = ProcessManager(self.cfg)
        self.connection_checker = ConnectionChecker()

        self.consecutive_failures = 0
        self.notified = False
        self.running = True

        self.last_cleanup = now_in_china() - timedelta(days=1)
        self.cleanup_interval_hours = self.cfg.get("log_cleanup", "interval_hours", fallback=None) if self.cfg.has_section("log_cleanup") else None
        if self.cleanup_interval_hours is not None:
            try:
                self.cleanup_interval_hours = int(self.cleanup_interval_hours)
            except Exception:
                self.cleanup_interval_hours = 24

        proc_check_interval = self.cfg.get("process_monitor", "check_interval_seconds", fallback=None) if self.cfg.has_section("process_monitor") else None
        if proc_check_interval is not None:
            try:
                self.proc_check_interval = int(proc_check_interval)
            except Exception:
                self.proc_check_interval = 30
        else:
            self.proc_check_interval = 30
        if self.proc_check_interval <= 0:
            self.proc_check_interval = 30

        self.next_proc_check = now_in_china()
        self.next_conn_check = now_in_china()
        self.target_desc = f"{self.host}:{self.port}" if self.mode != "http" else self.http_url

    def _handle_signal(self, signum, frame):
        logging.info("Received signal %s, shutting down...", signum)
        self.running = False
        self.stop_event.set()

    def _check_once(self, now: str) -> None:
        if self.mode == "http":
            ok = self.connection_checker.check_http(self.http_url, self.timeout)
            target_label = self.http_url
        else:
            ok = self.connection_checker.check_tcp(self.host, self.port, self.timeout)
            target_label = f"{self.host}:{self.port}"
        check_status = "连接成功(恢复)" if ok else "连接断开（或异常）"
        logging.info("Connection check for %s: %s", target_label, check_status)
        if ok:
            if self.consecutive_failures > 0:
                logging.info("Connection restored to %s (previous failures=%s)", target_label, self.consecutive_failures)
            self.consecutive_failures = 0
            if self.notified and self.notify_recovery:
                subject = f"{self.subject_prefix}{check_status}，iNode client recovered: {target_label}"
                body = f"iNode client at {target_label} is reachable again as of {now}."
                self.notification_service.send_notification(subject, body)
                self.notified = False
            return

        self.consecutive_failures += 1
        logging.warning("Connection check failed for %s (consecutive=%s)", target_label, self.consecutive_failures)
        if self.consecutive_failures >= self.failure_threshold and not self.notified:
            subject = f"{self.subject_prefix}{check_status}，iNode client unreachable: {target_label}"
            body = (
                f"iNode client at {target_label} has been unreachable for {self.consecutive_failures} checks.\n"
                f"Last checked: {now}\n"
                f"Check interval: {self.interval}s; connect timeout: {self.timeout}s; failure threshold: {self.failure_threshold}\n"
            )
            self.notification_service.send_notification(subject, body)
            self.notified = True

    def run(self) -> int:
        if self.service_mode and platform.system().lower() == "windows":
            logging.info("Service mode enabled; monitoring loop will keep running as a Windows service-friendly process.")
        else:
            try:
                signal.signal(signal.SIGINT, self._handle_signal)
                signal.signal(signal.SIGTERM, self._handle_signal)
            except (AttributeError, ValueError):
                logging.debug("Signal handlers are unavailable in this runtime; continuing without them.")

        logging.info(
            "Starting iNode monitor in %s mode: %s, interval=%ss, threshold=%s",
            self.mode,
            self.target_desc,
            self.interval,
            self.failure_threshold,
        )

        while self.running:
            now_dt = now_in_china()
            now_ts = now_dt.strftime("%Y-%m-%d %H:%M:%S %z")

            try:
                if self.cleanup_interval_hours:
                    elapsed_hours = (now_dt - self.last_cleanup).total_seconds() / 3600.0
                    if elapsed_hours >= self.cleanup_interval_hours:
                        self.log_cleaner.cleanup_logs()
                        self.last_cleanup = now_dt
            except Exception:
                logging.exception("Error during scheduled log cleanup")

            try:
                if now_dt >= self.next_proc_check:
                    self.process_manager.monitor_processes()
                    while self.next_proc_check <= now_dt:
                        self.next_proc_check += timedelta(seconds=self.proc_check_interval)
            except Exception:
                logging.exception("Error during process monitoring")

            if now_dt >= self.next_conn_check:
                self._check_once(now_ts)
                while self.next_conn_check <= now_dt:
                    self.next_conn_check += timedelta(seconds=self.interval)

            next_event = min(self.next_proc_check, self.next_conn_check)
            sleep_for = max(0.2, (next_event - now_in_china()).total_seconds())
            if self.service_mode:
                self.stop_event.wait(timeout=min(1.0, sleep_for if sleep_for > 0 else 1.0))
                if self.stop_event.is_set():
                    self.running = False
            else:
                time.sleep(sleep_for)

        logging.info("Monitor stopped")
        return 0


def main(config_path: str, service_mode: bool = False) -> int:
    try:
        controller = MonitorController(config_path)
        controller.service_mode = service_mode
        return controller.run()
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "inode_monitor.ini")
    raise SystemExit(main(cfg_path))