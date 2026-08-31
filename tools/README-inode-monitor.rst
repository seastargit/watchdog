iNode TCP Monitor
==================

A small script to actively monitor whether an iNode client is reachable via TCP or HTTP and send alerts when it becomes unreachable.

The monitor supports multiple notification channels:

- SMTP email
- DingTalk webhook robot
- WeCom group robot
- Email + DingTalk + WeCom together (``channel = email,dingtalk,wecom`` or ``channel = all``)

Files added:

- tools/inode_monitor.py
- tools/inode_monitor.ini (sample config)
- tools/README-inode-monitor.rst (this file)

Quick start:

1. Edit tools/inode_monitor.ini and set the check.host and check.port or http_url.
2. Set ``[check] mode`` to either ``tcp`` or ``http``.
3. Set the notification channel in ``[notification]`` to ``email``, ``dingtalk``, ``wecom``, ``all``, or a comma-separated list like ``email,dingtalk,wecom``.
4. Fill in the corresponding settings in ``[email]``, ``[dingtalk]``, and/or ``[wecom]``.
5. Run the monitor via the dedicated runner:

   python tools\run_inode_monitor.py tools\inode_monitor.ini

Example config:

- For email alerts:

  [notification]
  channel = email

  [email]
  smtp_host = smtp.example.com
  smtp_port = 587
  from = monitor@example.com
  to = ops@example.com

- For email + DingTalk + WeCom at the same time:

  [notification]
  channel = email,dingtalk,wecom

  [dingtalk]
  webhook_url = https://oapi.dingtalk.com/robot/send?access_token=xxxxx
  secret = your_secret
  at_mobiles = 13800138000

  [wecom]
  webhook_url = https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx
  mentioned_mobiles = 13800138000

- For HTTP health check:

  [check]
  mode = http
  http_url = http://127.0.0.1:8080/health

Notes:

- The script uses only Python standard library modules: socket, smtplib, urllib, hmac, hashlib, json, configparser.
- It performs TCP connect attempts; if you need ICMP ping or HTTP health-check, the script can be extended.
- For production use, run the script under a process supervisor (systemd, supervisor, or a container).
