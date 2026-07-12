"""How to manage many long-lived sessions when the library doesn't.

clearancekit deliberately omits SessionPool — this is how you do it
yourself in ~30 lines.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import clearancekit as ck
from clearancekit.transports.nodriver import NodriverDriver


class SessionRegistry:
    def __init__(self) -> None:
        self._cache: dict[str, ck.Session] = {}

    async def get(self, key: str) -> ck.Session:
        s = self._cache.get(key)
        if s is None:
            s = await ck.Session.create(**self._spec(key))
            self._cache[key] = s
        return s

    async def evict(self, key: str) -> None:
        s = self._cache.pop(key, None)
        if s is not None:
            await s.close()

    async def close_all(self) -> None:
        for s in self._cache.values():
            await s.close()
        self._cache.clear()

    def _spec(self, key: str) -> dict[str, Any]:
        return {
            "browser": NodriverDriver(profile_dir=Path(f"/tmp/ck-{key}")),
            "warmup_url": f"https://{key}.example.com/",
        }


async def fetch_endpoint(reg: SessionRegistry, key: str, path: str) -> str:
    url = f"https://{key}.example.com{path}"

    async def _attempt() -> str:
        s = await reg.get(key)
        return (await s.fetch(url)).body

    try:
        return await _attempt()
    except ck.CFCookieExpired:
        s = await reg.get(key)
        await s.refresh_cf()
        return (await s.fetch(url)).body
    except ck.CFSessionDead:
        await reg.evict(key)
        return await _attempt()


async def main() -> None:
    reg = SessionRegistry()
    try:
        body = await fetch_endpoint(reg, "myapp", "/api/data")
        print(body[:200])
    finally:
        await reg.close_all()


if __name__ == "__main__":
    asyncio.run(main())
