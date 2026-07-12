"""Command-line interface: ``python -m clearancekit ...``.

Subcommands:
  - ``selftest``: probe runtime dependencies (chromium, xdotool, X server).
  - ``test URL``: spawn a session, pass CF on URL, print fetch result.
  - ``shell``: interactive IPython-like REPL with a live session in ``s``.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

from clearancekit import (
    Session,
    __version__,
)
from clearancekit.transports.nodriver import NodriverDriver


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser with subcommands."""
    p = argparse.ArgumentParser(
        prog="clearancekit", description=f"clearancekit {__version__}"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("selftest", help="Probe runtime deps")

    pt = sub.add_parser("test", help="One-shot: open URL through CF, print result")
    pt.add_argument("url")
    pt.add_argument("--warmup", default=None, help="Warmup URL (defaults to URL)")
    pt.add_argument("--profile-dir", default=None)

    ps = sub.add_parser("shell", help="Interactive REPL with live session")
    ps.add_argument("--warmup", required=True)
    ps.add_argument("--profile-dir", default=None)

    return p


def cmd_selftest(args: argparse.Namespace) -> int:
    """Check runtime deps, print a report, return 0 if all OK."""
    import subprocess as sp

    checks: list[tuple[str, bool, str]] = []
    for binary in ("chromium", "google-chrome", "xdotool", "xdpyinfo", "Xvfb"):
        path = shutil.which(binary)
        checks.append((binary, path is not None, path or "MISSING"))

    try:
        r = sp.run(
            ["xdpyinfo"],
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
            timeout=2.0,
            check=False,
        )
        x_alive = r.returncode == 0
    except (FileNotFoundError, sp.TimeoutExpired):
        x_alive = False
    checks.append(("X server reachable", x_alive, str(x_alive)))

    ok = all(c[1] for c in checks)
    print(f"clearancekit {__version__} selftest")
    print("=" * 40)
    for name, good, detail in checks:
        mark = "OK " if good else "!! "
        print(f"{mark}{name:25} {detail}")
    print("=" * 40)
    print("READY" if ok else "NOT READY — install missing deps and ensure X server")
    return 0 if ok else 1


async def _run_test(args: argparse.Namespace) -> int:
    pd = Path(args.profile_dir) if args.profile_dir else Path("/tmp/clearancekit-test")
    pd.mkdir(parents=True, exist_ok=True)
    warmup = args.warmup or args.url
    s = await Session.create(
        browser=NodriverDriver(profile_dir=pd),
        warmup_url=warmup,
    )
    try:
        r = await s.fetch(args.url)
        print(f"status={r.status}  elapsed_ms={r.elapsed_ms}")
        print(f"final_url={r.final_url}")
        print("-- body (first 500 chars) --")
        print(r.body[:500])
        return 0
    finally:
        await s.close()


def cmd_test(args: argparse.Namespace) -> int:
    """Subcommand: ``test URL`` — one-shot CF bypass + fetch + print."""
    return asyncio.run(_run_test(args))


async def _run_shell(args: argparse.Namespace) -> int:
    pd = Path(args.profile_dir) if args.profile_dir else Path("/tmp/clearancekit-shell")
    pd.mkdir(parents=True, exist_ok=True)
    s = await Session.create(
        browser=NodriverDriver(profile_dir=pd),
        warmup_url=args.warmup,
    )
    try:
        try:
            from IPython import embed  # type: ignore[import-not-found]

            print("Live session bound to `s`. Try: await s.fetch('...')")
            embed(using="asyncio")
        except ImportError:
            import code

            print("IPython not installed; falling back to vanilla REPL.")
            print("Note: vanilla REPL cannot `await` directly. Use asyncio.run(...).")
            code.interact(local={"s": s, "asyncio": asyncio})
        return 0
    finally:
        await s.close()


def cmd_shell(args: argparse.Namespace) -> int:
    """Subcommand: ``shell`` — start a live session and drop into REPL."""
    return asyncio.run(_run_shell(args))


def main(argv: list[str] | None = None) -> int:
    """CLI entry — dispatch ``args.command`` to the matching ``cmd_*``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "selftest":
        return cmd_selftest(args)
    if args.command == "test":
        return cmd_test(args)
    if args.command == "shell":
        return cmd_shell(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
