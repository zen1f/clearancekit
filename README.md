# clearancekit

[中文文档](README.zh-CN.md)

> **EXPERIMENTAL** — Personal experiment, shared as-is.
> No support, no roadmap, no guarantees. For learning / personal use only.
> Respect target sites' Terms of Service.

In-process Cloudflare bypass via real Chromium (powered by [nodriver]),
with a pluggable challenge pipeline and automatic Turnstile solving.

**Supports both Cloudflare challenge types:**
- **Passive** ("Just a moment..." 5s wait) — auto-detected and waited through
- **Interactive** (Turnstile checkbox / managed challenge) — auto-detected and clicked via OS-level xdotool

[nodriver]: https://github.com/ultrafunkamsterdam/nodriver

## Features

- **Pass Turnstile interactive challenges** — OS-level click via xdotool,
  no CAPTCHA API needed, no token injection
- Pass Cloudflare passive challenges (auto-wait)
- Same-origin HTTP requests from inside the bypassed browser tab
- Persistent Chrome profile — `cf_clearance` cookie carries across requests
- Pluggable detect → aggregate → solve pipeline with fallback chain
- Virtual display management via `XvfbBackend` (only needed for `OSClickSolver`)

## Install

### Python

```bash
pip install git+https://github.com/zen1f/clearancekit
```

The only required Python dependency is `nodriver`.

### System deps (OSClickSolver requires Linux + X11)

```bash
sudo apt update
sudo apt install -y chromium-browser xdotool x11-utils xvfb
```

### macOS / Windows

Use a Linux container for `OSClickSolver`:

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium xdotool x11-utils xvfb \
    && rm -rf /var/lib/apt/lists/*
RUN pip install git+https://github.com/zen1f/clearancekit
CMD ["python", "-m", "clearancekit", "selftest"]
```

## Quick start

```python
import asyncio
from pathlib import Path

import clearancekit as ck
from clearancekit.transports.nodriver import NodriverDriver

async def main():
    async with ck.session(
        display=ck.XvfbBackend(display_num=89),
        browser=NodriverDriver(profile_dir=Path("/tmp/ck-demo")),
        warmup_url="https://nowsecure.nl",
    ) as s:
        r = await s.fetch("https://nowsecure.nl/")
        print(r.status, r.body[:200])

asyncio.run(main())
```

### Custom pipeline

```python
pipeline = ck.ChallengePipeline(
    solvers=[
        ck.PassiveWaitSolver(),
        ck.OSClickSolver(max_attempts=5),
    ],
    max_wait_seconds=90,
)

async with ck.session(
    display=ck.XvfbBackend(display_num=89),
    browser=NodriverDriver(profile_dir=Path("/tmp/ck-custom")),
    pipeline=pipeline,
    warmup_url="https://example.com",
) as s:
    ...
```

### Silence nodriver logs

```python
import logging

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(message)s")
for name in ("nodriver", "websockets", "uc"):
    logging.getLogger(name).setLevel(logging.WARNING)
```

## Architecture

```
Session
├── BrowserDriver (nodriver)    — Chrome lifecycle, evaluate, fetch, cookies
├── ChallengePipeline           — detect → aggregate → solve loop
│   ├── Detectors               — DOMDetector (OOPIF iframe text + DOM signals)
│   │   └── Voting              — MAJORITY / ANY / WEIGHTED + CF_BLOCKED veto
│   └── Solvers                 — PassiveWaitSolver, OSClickSolver
│       └── Fallback chain      — try all matching solvers until one succeeds
└── DisplayBackend (XvfbBackend) — virtual X display for headless Linux
```

- **Session** = one Chrome process + one `ChallengePipeline`. Tab is internal;
  recreated transparently if closed.
- **Pipeline** runs `Detector` → `Solver` cycles. Solvers are tried in order
  until one returns `success=True` (fallback chain). `CF_BLOCKED` from any
  detector vetoes all other votes.
- **Transport** layer talks to Chrome via nodriver CDP. Only `tab.evaluate()`
  is used during the pipeline (safe under heavy Target event traffic).
  `tab.send()` (generic CDP) is reserved for user-facing APIs outside the
  pipeline.

## Extending

### Custom solver

Implement the `ChallengeSolver` Protocol and add it to the solver list.
Solvers are tried in order — put cheap ones first:

```python
class MyPaidSolver:
    name = "paid_api"
    handles = {ck.ChallengeKind.CF_INTERACTIVE}

    async def solve(self, driver, kind, *, display=None):
        # call your paid CAPTCHA API here
        return ck.SolveResult(success=True, solver_name=self.name, elapsed_s=3.0)

pipeline = ck.ChallengePipeline(
    solvers=[
        ck.PassiveWaitSolver(),
        ck.OSClickSolver(),
        MyPaidSolver(),  # fallback: only called if OS click fails
    ],
)
```

See `examples/custom_solver.py`.

### Custom detector

Implement `ChallengeDetector` Protocol. Raise a `CFError` subclass for
site-specific blockers (e.g. login wall) — this aborts the pipeline cleanly.

### Custom display backend

Implement the `DisplayBackend` protocol
(`start()` / `stop()` / `display_id()` / `screen_size()`) and pass as
`display=` to `session()` or `Session.create()`.

## Multi-session pattern

clearancekit does not provide a session pool — you manage your own.
See `examples/caller_managed_pool.py` for a ~30-line registry with EAFP
self-healing (`CFCookieExpired` → refresh, `CFSessionDead` → recreate).

## Solvers

| Solver | Method | OS deps | Headless |
|--------|--------|---------|----------|
| `PassiveWaitSolver` | Waits for passive challenge to resolve | None | Yes |
| `OSClickSolver` | Locates CF iframe via OOPIF target, clicks via xdotool | Linux + X11 + xdotool | No |

Default solver chain: `PassiveWaitSolver` → `OSClickSolver`.

## Limitations

1. **`OSClickSolver` requires Linux + X11.** Mac/Win → Linux container.
2. **`headless=False` required.** CF anti-detection incompatible with headless.
3. **`fetch()` is text + same-origin.** No binary / cross-origin.
4. **IP-banned sessions are unrecoverable.** No IP rotation.
5. **No session pool.** Caller manages lifecycle.
6. **No state-query API.** Pure EAFP — try and catch.

## License

AGPL-3.0-or-later.

## Acknowledgements

- [nodriver](https://github.com/ultrafunkamsterdam/nodriver) — anti-detection Chromium driver
- [xdotool](https://www.semicomplete.com/projects/xdotool/) — X11 input automation (OSClickSolver only)
