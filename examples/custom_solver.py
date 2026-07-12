"""Custom solver demo: fallback chain ending in a (mock) paid API."""

from __future__ import annotations

import asyncio
from pathlib import Path

import clearancekit as ck
from clearancekit.transports.nodriver import NodriverDriver


class MockPaidCaptchaSolver:
    """Stand-in for a real paid CAPTCHA-solving API."""

    name = "mock_paid_captcha"
    handles = {ck.ChallengeKind.CF_INTERACTIVE}

    async def solve(
        self,
        driver: ck.BrowserDriver,
        kind: ck.ChallengeKind,
        *,
        display: str | None = None,
    ) -> ck.SolveResult:
        print(f"[mock_paid_captcha] would solve {kind.value} via paid API")
        return ck.SolveResult(success=False, solver_name=self.name, elapsed_s=0.0)


async def main() -> None:
    pipeline = ck.ChallengePipeline(
        solvers=[
            ck.PassiveWaitSolver(),
            MockPaidCaptchaSolver(),
        ],
    )
    async with ck.session(
        browser=NodriverDriver(profile_dir=Path("/tmp/ck-custom")),
        pipeline=pipeline,
        warmup_url="https://nowsecure.nl",
    ) as s:
        r = await s.fetch("https://nowsecure.nl/")
        print(r.status)


if __name__ == "__main__":
    asyncio.run(main())
