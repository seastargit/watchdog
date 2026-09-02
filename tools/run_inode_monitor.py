#!/usr/bin/env python3
"""Standalone runner for the iNode connection monitor."""

from __future__ import annotations

import argparse
import os
import sys

from inode_monitor import main


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the iNode TCP/HTTP monitor.")
    parser.add_argument(
        "--service",
        action="store_true",
        help="Run in Windows service-friendly mode. This keeps the process alive until it is stopped by the host runtime.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=os.path.join(os.path.dirname(__file__), "inode_monitor.ini"),
        help="Path to the monitor INI config file.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(args.config, service_mode=args.service))
