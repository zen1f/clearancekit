"""Minimal example: one-shot fetch."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import clearancekit as ck
from clearancekit import XvfbBackend
from clearancekit.transports.nodriver import NodriverDriver

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(message)s")


async def main() -> None:
    logging.getLogger("uc").setLevel(logging.WARNING)
    logging.getLogger("nodriver").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    dp = XvfbBackend(display_num=89)
    pipeline = ck.ChallengePipeline(
        solvers=[
            ck.PassiveWaitSolver(),
            ck.OSClickSolver(max_attempts=20),
        ],
        max_wait_seconds=90,
    )
    async with ck.session(
        display=dp,
        browser=NodriverDriver(profile_dir=Path("/tmp/ck-basic")),
        pipeline=pipeline,
        warmup_url="https://nowsecure.nl",
    ) as s:
        print("================================================")
        r = await s.fetch("https://nowsecure.nl/")
        print(f"status={r.status} elapsed_ms={r.elapsed_ms}")
        print(r.body)


if __name__ == "__main__":
    asyncio.run(main())
