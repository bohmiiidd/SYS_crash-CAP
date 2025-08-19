#!/usr/bin/env python3
"""
Project runner.

Usage examples:
  python run.py
  python run.py --config config.json --debug
  python run.py pid
  python run.py swap status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

# ---------- Paths & Import Setup ----------
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DEFAULT_CONFIG = ROOT / "config.json"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))  # allow `import main`, `import runtime_pid`, etc.


# ---------- Logging ----------
LOG = logging.getLogger("runner")


def setup_logging(debug: bool = False, quiet: bool = False) -> None:
    level = logging.INFO
    if debug:
        level = logging.DEBUG
    if quiet:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    if debug:
        LOG.debug("Debug logging enabled")


# ---------- Signal Handling ----------
def _signal_handler(signum, frame) -> None:  # type: ignore[no-untyped-def]
    names = {signal.SIGINT: "SIGINT", signal.SIGTERM: "SIGTERM"}
    LOG.info("Received %s, shutting down gracefully...", names.get(signum, str(signum)))
    # If you have cleanup hooks, call them here.
    sys.exit(0)


def register_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


# ---------- Config ----------
def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Top-level config must be a JSON object")

    return data


def summarize_config(cfg: dict[str, Any]) -> str:
    # small, privacy-safe summary
    keys = list(cfg.keys())
    preview = {k: cfg[k] for k in keys[:5]}  # avoid dumping everything
    more = "…" if len(keys) > 5 else ""
    return f"keys={keys[:5]}{more}, preview={preview}"


# ---------- Dynamic Main Resolver ----------
def resolve_main_callable() -> Tuple[Optional[Callable[..., Any]], str]:
    try:
        import main  # import src/main.py
        LOG.debug("Imported main.py successfully")
        # Try finding callable first
        for name in ["main", "run", "app"]:
            fn = getattr(main, name, None)
            if callable(fn):
                return fn, f"{name}(config)"
        # fallback: execute main.py as script
        def exec_main(cfg=None):
            ns = {"__name__": "__main__", "config": cfg or {}}
            with open(main.__file__, "r", encoding="utf-8") as f:
                code = f.read()
            exec(code, ns)
        return exec_main, "exec(main.py)"
    except Exception as e:
        LOG.error("Failed to import main: %s", e)
        return None, ""


# ---------- Optional Modules ----------
def try_runtime_pid(config: dict[str, Any]) -> None:
    """
    If src/runtime_pid.py exists and exposes `register_pid(path: Optional[str]) -> str`
    or `show_pid(path: Optional[str]) -> str`, use it. Otherwise, fall back.
    """
    try:
        import runtime_pid  # type: ignore
    except Exception as e:
        LOG.warning("runtime_pid module not available: %s", e)
        print(os.getpid())
        return

    path = config.get("pidfile") or None
    if hasattr(runtime_pid, "register_pid"):
        try:
            out = runtime_pid.register_pid(path)  # type: ignore[attr-defined]
            print(out if out is not None else os.getpid())
            return
        except Exception as e:
            LOG.error("runtime_pid.register_pid failed: %s", e)

    if hasattr(runtime_pid, "show_pid"):
        try:
            out = runtime_pid.show_pid(path)  # type: ignore[attr-defined]
            print(out if out is not None else os.getpid())
            return
        except Exception as e:
            LOG.error("runtime_pid.show_pid failed: %s", e)

    # Fallback: just print current PID
    print(os.getpid())


def try_swap_manager(action: str) -> int:
    """
    If src/swap_manager.py exists and exposes functions:
      - enable() / disable() / status()
    call them; otherwise, explain gracefully.
    """
    try:
        import swap_manager  # type: ignore
    except Exception as e:
        LOG.warning("swap_manager module not available: %s", e)
        print("swap_manager is not available in src/.")
        return 1

    actions = {
        "on": "enable",
        "off": "disable",
        "status": "status",
    }
    func_name = actions[action]
    fn = getattr(swap_manager, func_name, None)
    if not callable(fn):
        LOG.error("swap_manager.%s() is not implemented.", func_name)
        print(f"swap_manager.{func_name}() not implemented.")
        return 1

    try:
        result = fn()
        if result is not None:
            print(result)
        return 0
    except Exception as e:
        LOG.exception("swap_manager.%s() raised an exception", func_name)
        print(f"Error: {e}")
        return 1


# ---------- Command Handlers ----------
def cmd_run(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve() if args.config else DEFAULT_CONFIG
    try:
        cfg = load_config(config_path)
        LOG.info("Loaded config from %s (%s)", config_path, summarize_config(cfg))
    except Exception as e:
        if args.require_config:
            LOG.error("Failed to load required config: %s", e)
            return 2
        LOG.warning("Continuing without config: %s", e)
        cfg = {}

    fn, hint = resolve_main_callable()
    if not fn:
        return 3

    # Try calling with the right signature.
    try:
        if hint == "main()":
            fn()  # type: ignore[misc]
        else:
            fn(cfg)  # type: ignore[misc]
    except TypeError as te:
        # In case the callable uses a different signature, try both ways.
        LOG.debug("Callable signature mismatch (%s). Attempting fallback calls.", te)
        try:
            fn()  # type: ignore[misc]
        except Exception:
            fn(cfg)  # type: ignore[misc]
    except SystemExit as se:
        # Bubble up exit codes from main if they call sys.exit
        return int(getattr(se, "code", 0) or 0)
    except Exception as e:
        LOG.exception("Unhandled exception in main callable")
        print(f"Unhandled error: {e}")
        return 1

    return 0


def cmd_pid(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve() if args.config else DEFAULT_CONFIG
    cfg = {}
    try:
        cfg = load_config(config_path)
    except Exception:
        pass
    try_runtime_pid(cfg)
    return 0


def cmd_swap(args: argparse.Namespace) -> int:
    return try_swap_manager(args.action)


# ---------- CLI ----------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run.py",
        description="Project runner and utility CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config", help="Path to config.json", default=str(DEFAULT_CONFIG))
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--debug", action="store_true", help="Enable debug logging")
    grp.add_argument("--quiet", action="store_true", help="Reduce log output")
    p.add_argument(
        "--require-config",
        action="store_true",
        help="Exit if config fails to load",
    )

    sub = p.add_subparsers(dest="command")

    # run (default)
    sp_run = sub.add_parser("run", help="Run the main application")
    sp_run.set_defaults(func=cmd_run)

    # pid helper
    sp_pid = sub.add_parser("pid", help="Show/register a runtime PID (if supported)")
    sp_pid.set_defaults(func=cmd_pid)

    # swap manager helper
    sp_swap = sub.add_parser("swap", help="Control swap manager (if supported)")
    sp_swap.add_argument("action", choices=["on", "off", "status"], help="Action")
    sp_swap.set_defaults(func=cmd_swap)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(debug=args.debug, quiet=args.quiet)
    register_signal_handlers()

    # Default command is `run`
    if not args.command:
        args.command = "run"
        args.func = cmd_run  # type: ignore[attr-defined]

    return int(args.func(args))  # type: ignore[misc]


if __name__ == "__main__":
    raise SystemExit(main())
