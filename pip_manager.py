#!/usr/bin/env python3
"""
pip-manager — Reclaim disk space from pip without touching your Python install.

Lets you:
  * List installed packages sorted by real disk usage.
  * Uninstall packages safely (pip / setuptools / wheel are protected).
  * Inspect and clean pip's cache (HTTP download cache + locally built wheels).
  * See exactly which folders on disk everything lives in.

Author : Its-Xths
License: MIT
Repo   : https://github.com/Its-Xths/pip-manager
"""

from __future__ import annotations

import argparse
import itertools
import os
import re
import shutil
import site
import subprocess
import sys
import sysconfig
import threading
import time
from datetime import datetime
from importlib import metadata
from pathlib import Path

try:
    from packaging.version import parse as parse_version
except ImportError:
    print("Missing dependency. Install it with:\n    pip install packaging")
    sys.exit(1)


__version__ = "1.0.0"
__author__ = "Its-Xths"
__repo__ = "https://github.com/its-xths/pip-manager"

LOG_FILE = Path(__file__).resolve().parent / "Xths_PiP_Logs_.log"
PROTECTED_PACKAGES = {"pip", "setuptools", "wheel"}

class C:
    _enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    RESET = "\033[0m" if _enabled else ""
    BOLD = "\033[1m" if _enabled else ""
    DIM = "\033[2m" if _enabled else ""
    RED = "\033[31m" if _enabled else ""
    GREEN = "\033[32m" if _enabled else ""
    YELLOW = "\033[33m" if _enabled else ""
    BLUE = "\033[34m" if _enabled else ""
    MAGENTA = "\033[35m" if _enabled else ""
    CYAN = "\033[36m" if _enabled else ""


def banner():
    print(f"""{C.CYAN}{C.BOLD}
  ____  ____   __  __
 |  _ \\|  _ \\ |  \\/  | __ _ _ __   __ _  __ _  ___ _ __
 | |_) | |_) || |\\/| |/ _` | '_ \\ / _` |/ _` |/ _ \\ '__|
 |  __/|  __/ | |  | | (_| | | | | (_| | (_| |  __/ |
 |_|   |_|    |_|  |_|\\__,_|_| |_|\\__,_|\\__, |\\___|_| . XTHS (v.01)
                                        |___/
{C.RESET}{C.DIM} pip-manager v{__version__}  ·  by {__author__}  ·  {__repo__}{C.RESET}
""")


def log_action(message: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")

class Spinner:
    """Indeterminate spinner for operations of unknown duration (pip calls)."""
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str):
        self.message = message
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop_event.is_set():
                break
            sys.stdout.write(f"\r{C.CYAN}{frame}{C.RESET} {self.message}")
            sys.stdout.flush()
            time.sleep(0.08)

    def __enter__(self):
        if sys.stdout.isatty():
            self._thread.start()
        else:
            print(self.message)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join()
        sys.stdout.write("\r" + " " * (len(self.message) + 4) + "\r")
        sys.stdout.flush()


def progress_bar(current: int, total: int, prefix: str = "", width: int = 30):
    """Determinate progress bar for loops with a known length (scanning packages)."""
    if total == 0:
        return
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = 100 * current / total
    end = "\n" if current == total else ""
    sys.stdout.write(f"\r{prefix} {C.CYAN}[{bar}]{C.RESET} {pct:5.1f}% ({current}/{total}){end}")
    sys.stdout.flush()

# func_helpers -----

def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


def run_pip(args, capture=True):
    """Always run pip through the *current* interpreter, so this script
    manages the exact environment it's running in (venv, conda, system…)."""
    cmd = [sys.executable, "-m", "pip"] + args
    return subprocess.run(cmd, capture_output=capture, text=True)


def pip_cache_dir() -> str:
    result = run_pip(["cache", "dir"])
    return result.stdout.strip()


def dir_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            fp = os.path.join(root, name)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


# path + env  -----

def show_environment_info():
    print(f"\n{C.BOLD}Environment & storage locations{C.RESET}")
    print("-" * 64)
    print(f"{'Python executable:':<28}{sys.executable}")
    print(f"{'Python version:':<28}{sys.version.split()[0]}")

    try:
        site_packages = site.getsitepackages()
    except AttributeError:
        site_packages = [sysconfig.get_paths().get("purelib", "unknown")]
    for i, sp in enumerate(site_packages):
        label = "Site-packages:" if i == 0 else ""
        size = dir_size(sp) if os.path.isdir(sp) else 0
        print(f"{label:<28}{sp}  {C.DIM}({human_size(size)}){C.RESET}")

    cache_dir = pip_cache_dir()
    cache_size = dir_size(cache_dir) if os.path.isdir(cache_dir) else 0
    print(f"{'pip cache directory:':<28}{cache_dir}  {C.DIM}({human_size(cache_size)}){C.RESET}")
    print(f"{'Log file:':<28}{LOG_FILE}")
    print("-" * 64)


# sizes + unin -----

def get_installed_package_sizes():
    """Return {name: (size_bytes, version, location)} using each package's
    own file manifest, so only files that belong to it are counted."""
    dists = list(metadata.distributions())
    sizes = {}
    for i, dist in enumerate(dists, start=1):
        progress_bar(i, len(dists), prefix="Scanning installed packages")
        name = dist.metadata.get("Name") or "unknown"
        version = dist.version
        location = str(dist.locate_file("")) if dist.files else "unknown"
        total = 0
        for f in dist.files or []:
            try:
                path = dist.locate_file(f)
                if path and os.path.isfile(path):
                    total += os.path.getsize(path)
            except (OSError, ValueError):
                continue
        if name not in sizes or total > sizes[name][0]:
            sizes[name] = (total, version, location)
    return sizes


def list_packages(sort_desc=True):
    sizes = get_installed_package_sizes()
    return sorted(sizes.items(), key=lambda kv: kv[1][0], reverse=sort_desc)


def print_package_table(ordered):
    print(f"\n{'#':<4}{'Package':<32}{'Version':<15}{'Size':>10}")
    print("-" * 64)
    for i, (name, (size, version, _)) in enumerate(ordered, start=1):
        print(f"{i:<4}{name:<32}{version:<15}{human_size(size):>10}")
    total = sum(size for _, (size, _, _) in ordered)
    print("-" * 64)
    print(f"{C.BOLD}{'Total':<51}{human_size(total):>10}{C.RESET}\n")


def uninstall_packages(names):
    to_remove, skipped = [], []
    for n in names:
        (skipped if n.lower() in PROTECTED_PACKAGES else to_remove).append(n)

    for n in skipped:
        print(f"{C.YELLOW}Skipping '{n}': removing it can break pip itself.{C.RESET}")

    if not to_remove:
        print("Nothing to uninstall.")
        return

    print(f"\nAbout to uninstall: {C.BOLD}{', '.join(to_remove)}{C.RESET}")
    confirm = input("Type 'yes' to confirm: ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    with Spinner(f"Uninstalling {len(to_remove)} package(s)..."):
        result = run_pip(["uninstall", "-y", *to_remove])

    if result.returncode == 0:
        print(f"{C.GREEN}Done.{C.RESET}")
        log_action(f"Uninstalled: {', '.join(to_remove)}")
    else:
        print(f"{C.RED}pip reported an error:{C.RESET}\n{result.stderr}")
        log_action(f"FAILED uninstall: {', '.join(to_remove)} — {result.stderr.strip()}")


def interactive_uninstall():
    ordered = list_packages()
    if not ordered:
        print("No installed packages found.")
        return
    print_package_table(ordered)
    choice = input(
        "Enter numbers to uninstall (comma-separated, e.g. 1,3,5), "
        "or press Enter to cancel: "
    ).strip()
    if not choice:
        print("Cancelled.")
        return
    try:
        idxs = [int(x.strip()) for x in choice.split(",") if x.strip()]
    except ValueError:
        print("Couldn't parse that input, cancelling.")
        return
    names = []
    for i in idxs:
        if 1 <= i <= len(ordered):
            names.append(ordered[i - 1][0])
        else:
            print(f"Ignoring out-of-range number: {i}")
    uninstall_packages(names)


# cache manager -----

def get_cache_info() -> str:
    return run_pip(["cache", "info"]).stdout


def purge_cache(confirm=True):
    if confirm:
        print(get_cache_info())
        ans = input("Purge the ENTIRE pip cache shown above? [y/N]: ").strip().lower()
        if ans != "y":
            print("Cancelled.")
            return
    with Spinner("Purging pip cache..."):
        result = run_pip(["cache", "purge"])
    print(result.stdout.strip() or f"{C.GREEN}Cache purged.{C.RESET}")
    log_action("Purged entire pip cache")


def clean_built_wheel_cache_keep_latest():
    """Among *locally built* wheels only (pip cache list can't see the
    HTTP download cache), keep the newest version of each package and
    delete older cached wheel files. Uses --format=abspath for real,
    reliable file paths instead of parsing human-readable text."""
    with Spinner("Scanning built-wheel cache..."):
        result = run_pip(["cache", "list", "--format=abspath"])
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    if not paths:
        print(
            "No locally built wheels in the cache (nothing to clean here).\n"
            f"{C.DIM}Most of your pip cache is probably the HTTP download "
            "cache — use 'Purge entire cache' to reclaim that.{C.RESET}"
        )
        return

    pattern = re.compile(r"([\w.\-]+?)-([\d][\w.\-]*?)(?:-py\d|-cp\d|\.tar\.gz|\.whl)")
    latest = {}
    for path in paths:
        match = pattern.match(os.path.basename(path))
        if not match:
            continue
        pkg_name, pkg_version = match.groups()
        try:
            v = parse_version(pkg_version)
        except Exception:
            continue
        if pkg_name not in latest or v > latest[pkg_name][1]:
            latest[pkg_name] = (path, v)

    keep_paths = {p for p, _ in latest.values()}
    to_delete = [p for p in paths if p not in keep_paths]

    if not to_delete:
        print(f"{C.GREEN}Already only keeping the latest version of each cached wheel.{C.RESET}")
        return

    freed = sum(os.path.getsize(p) for p in to_delete if os.path.isfile(p))
    print(f"\nWill delete {len(to_delete)} older cached wheel file(s), "
          f"freeing about {C.BOLD}{human_size(freed)}{C.RESET}:")
    for p in to_delete:
        print(f"  - {os.path.basename(p)}")
    ans = input("Proceed? [y/N]: ").strip().lower()
    if ans != "y":
        print("Cancelled.")
        return

    deleted = 0
    for i, p in enumerate(to_delete, start=1):
        try:
            os.remove(p)
            deleted += 1
        except OSError as e:
            print(f"{C.RED}Could not delete {p}: {e}{C.RESET}")
        progress_bar(i, len(to_delete), prefix="Deleting old wheels")

    print(f"{C.GREEN}Freed {human_size(freed)} across {deleted} file(s).{C.RESET}")
    log_action(f"Removed {deleted} old cached wheel(s), freed {human_size(freed)}")



# menu -----

def main_menu():
    banner()
    while True:
        print(
            f"{C.BOLD}=== pip-manager ==={C.RESET}\n"
            "1) List installed packages by size\n"
            "2) Uninstall packages (reclaim disk space)\n"
            "3) Show pip cache info\n"
            "4) Purge entire pip cache\n"
            "5) Clean cache: keep only latest built wheel per package\n"
            "6) Show environment & storage paths\n"
            "7) Exit"
        )
        choice = input("Choose an option: ").strip()
        if choice == "1":
            print_package_table(list_packages())
        elif choice == "2":
            interactive_uninstall()
        elif choice == "3":
            print(get_cache_info())
        elif choice == "4":
            purge_cache()
        elif choice == "5":
            clean_built_wheel_cache_keep_latest()
        elif choice == "6":
            show_environment_info()
        elif choice == "7":
            print("Made By Harshit Sharma {XTHS}, See ya.")
            break
        else:
            print(f"{C.YELLOW}Not a valid option.{C.RESET}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="List installed packages by size and exit")
    parser.add_argument("--purge-cache", action="store_true", help="Purge entire pip cache without prompting")
    parser.add_argument("--paths", action="store_true", help="Show environment/storage paths and exit")
    parser.add_argument("--version", action="version", version=f"pip-manager {__version__} — by {__author__}")
    args = parser.parse_args()

    if args.list:
        print_package_table(list_packages())
    elif args.purge_cache:
        purge_cache(confirm=False)
    elif args.paths:
        show_environment_info()
    else:
        main_menu()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}Interrupted. Bye.{C.RESET}")
        sys.exit(130)
