iNode TCP Monitor
==================

A small script to actively monitor whether an iNode client is reachable via TCP and send email alerts when it becomes unreachable.

Files added:

- tools/inode_monitor.py
- tools/inode_monitor.ini (sample config)
- tools/README-inode-monitor.rst (this file)

Quick start:

1. Edit tools/inode_monitor.ini and set the check.host, check.port, and email SMTP settings.
2. Run the monitor:

   python tools\inode_monitor.py tools\inode_monitor.ini

Notes:

- The script uses Python's smtplib and configparser from the standard library.
- It performs TCP connect attempts; if you need ICMP ping or HTTP health-check, the script can be extended.
- For production use, run the script under a process supervisor (systemd, supervisor, or a container).
