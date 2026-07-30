# Python Installs Pkgs Manager

Reclaim disk space from pip — without touching your Python installation.

`pip-manager` is a single-file, dependency-light CLI that shows you exactly
which installed packages and cache files are eating your disk, and lets you
clean them up safely.

**Author:** [Its-Xths](https://github.com/Its-Xths)

## Features

- 📦 **List installed packages by real disk usage** — sizes are computed from
  each package's own file manifest, not a guess.
- 🗑️ **Uninstall packages interactively** — pick by number, confirm once.
  `pip`, `setuptools`, and `wheel` are protected so you can't accidentally
  break pip itself.
- 🧹 **Clean pip's cache** — purge it entirely, or keep only the newest
  cached wheel per package.
- 📁 **See exactly where things live** — Python executable, site-packages,
  and pip cache directory, with sizes.
- ⏳ **Progress animation** — a spinner for pip operations and a progress bar
  while scanning packages, so long-running steps don't look frozen.
- 📝 **Action log** — every uninstall/purge/clean is timestamped in
  `pip_manager.log` for an audit trail.
- 🎯 **Zero risk to your Python install** — this only ever calls
  `python -m pip ...` on third-party packages and pip's own cache; it never
  touches the interpreter or standard library.

## S.S.
<img width="726" height="681" alt="image" src="https://github.com/user-attachments/assets/bfcbc00e-0d49-4af1-afcf-d818a58ab04e" />


## Install

```bash
git clone https://github.com/Its-Xths/pip-manager.git
cd pip-manager
pip install -r requirements.txt
```

Only dependency is [`packaging`](https://pypi.org/project/packaging/), used
for correct version comparison.

## Usage

Interactive menu:

```bash
python pip_manager.py
```

```
=== pip-manager ===
1) List installed packages by size
2) Uninstall packages (reclaim disk space)
3) Show pip cache info
4) Purge entire pip cache
5) Clean cache: keep only latest built wheel per package
6) Show environment & storage paths
7) Exit
```

Non-interactive flags for scripting:

```bash
python pip_manager.py --list          # print installed packages by size
python pip_manager.py --purge-cache   # purge the entire pip cache, no prompt
python pip_manager.py --paths         # print environment/storage paths
python pip_manager.py --version
```

> `pip-manager` always runs `pip` through the same interpreter that's running
> the script (`sys.executable -m pip`), so it manages whatever environment
> you launched it in — a virtualenv, conda env, or your system Python.

## Why not just parse `pip cache list`?

On modern pip (20.1+), `pip cache list` only reports **locally built**
wheels — the ones pip builds itself from a source distribution. Most
installs are pre-built wheels that pip just downloads, and those live in a
separate HTTP cache that isn't exposed as a list of filenames. A script that
only looks at `pip cache list` text will often find nothing to clean, even
on a multi-GB cache.

`pip-manager` handles both cases:
- For the **HTTP download cache** (usually the bulk of the space), it uses
  `pip cache purge`, the only supported way to clear it.
- For the **locally built wheel cache**, it uses
  `pip cache list --format=abspath` to get real file paths, then keeps only
  the newest version of each package.

## License

MIT — see [LICENSE](LICENSE).
