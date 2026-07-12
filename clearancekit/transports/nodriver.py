"""nodriver-backed BrowserDriver implementation.

This is the only module that imports ``nodriver``. Everything else in
clearancekit talks to the abstract ``BrowserDriver`` Protocol.

Session boundary semantics (Chrome process-level):
  - ``self._browser.stopped`` True → all ops raise ``CFSessionDead``.
    ``_get_tab`` is the single enforcement point.
  - Tab closed → transparently recreated. Browser stays.
  - Browser dead → ``CFSessionDead`` (terminal; create a new Session).

Concurrency: all CDP operations are sequential (nodriver's transaction
  system cannot tolerate cancellation or concurrent requests on the same
  connection). ``self._tab_lock`` guards ``self._tab`` field assignment
  during transparent tab recreate.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from clearancekit._compat import nodriver as _compat
from clearancekit.display.backend import DisplayBackend
from clearancekit.errors import CFFetchFailed, CFSessionDead
from clearancekit.transports.base import (
    Cookie,
    FetchOptions,
    FetchResult,
    IframeInfo,
    NavigateResult,
    ViewportRect,
)

log = logging.getLogger(__name__)

# After ``tab.get()`` returns, the main-document ``responseReceived`` event may
# not have been dispatched yet (Chrome may resolve ``Page.navigate`` before the
# event is delivered). Bounded wait to let it settle; returns early once seen.
_NAV_HEADER_SETTLE_SEC = 2.0

# For a normal page, how long to wait for ``Page.loadEventFired`` so navigate()
# returns only after the document has finished loading. Bounded so a slow/hung
# page cannot block forever; returns early once the load event is seen.
_NAV_LOAD_TIMEOUT_SEC = 30.0

# After loadEventFired, CF scripts may still be loading asynchronously.
# Wait for networkIdle (all network requests settled) so the first detection
# cycle sees the fully-rendered challenge page.
_NAV_NETWORK_IDLE_SEC = 10.0

# When a navigation turns into a download, how long to wait for the file to
# finish writing to disk before giving up.
_NAV_DOWNLOAD_TIMEOUT_SEC = 30.0

_FETCH_JS = """
(async () => {
  const url = %(url)s;
  const opts = %(opts)s;
  const t0 = performance.now();
  let body, status, finalUrl, headers = {};
  try {
    const init = {
      method: opts.method,
      redirect: opts.follow_redirects ? "follow" : "manual",
    };
    if (opts.headers) init.headers = opts.headers;
    if (opts.form) {
      const fd = new URLSearchParams();
      for (const [k, v] of Object.entries(opts.form)) fd.append(k, v);
      init.body = fd.toString();
      init.headers = {
        ...(init.headers || {}),
        "Content-Type": "application/x-www-form-urlencoded",
      };
    } else if (opts.body !== null && opts.body !== undefined) {
      init.body = opts.body;
    }
    const ctrl = new AbortController();
    const timer = opts.timeout != null
      ? setTimeout(() => ctrl.abort(), opts.timeout * 1000)
      : null;
    init.signal = ctrl.signal;
    const r = await fetch(url, init);
    if (timer != null) clearTimeout(timer);
    body = await r.text();
    status = r.status;
    finalUrl = r.url;
    r.headers.forEach((v, k) => { headers[k] = v; });
    return JSON.stringify({
      status, final_url: finalUrl, headers, body,
      elapsed_ms: Math.round(performance.now() - t0),
    });
  } catch (e) {
    return JSON.stringify({ __error: String(e) });
  }
})()
""".strip()


class NodriverDriver:
    """BrowserDriver impl on top of nodriver."""

    def __init__(
        self,
        *,
        profile_dir: Path,
        lang: str = "en-US",
        headless: bool = False,
        executable_path: str | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        self._profile_dir = profile_dir
        self._lang = lang
        self._headless = headless
        self._executable_path = executable_path
        self._extra_args = extra_args or []
        self._browser: Any = None
        self._tab: Any = None
        self._tab_lock = asyncio.Lock()
        self._download_dir: Path | None = None
        # Persistent navigation tracking. A long-lived Network listener records
        # the latest main-frame document and any download; navigate() resets
        # these, response_meta()/content() read them back after the CF
        # pipeline. See :meth:`navigate`.
        self._nav_url: str = ""
        self._main_frame_id: Any = None
        self._last_doc: tuple[str, Any, dict[str, str]] | None = None
        self._download: dict[str, Any] = {}
        self._doc_seen = asyncio.Event()
        self._download_done = asyncio.Event()

    def is_started(self) -> bool:
        """Whether the browser process is running."""
        return self._browser is not None and not self._browser.stopped

    async def start(self, *, display: DisplayBackend | None = None) -> None:
        """Launch Chrome.

        Args:
            display: DisplayBackend instance. Extracts display_id for DISPLAY
                env and screen_size for --window-size. If None, uses env
                default and 1920x1080 fallback.

        Raises:
            RuntimeError: If Chrome binary not found.
        """
        import nodriver as uc

        _compat.apply()

        display_id = display.display_id() if display else None
        screen = display.screen_size() if display else None
        w, h = screen if screen else (1920, 1080)

        exe = (
            self._executable_path or shutil.which("chromium") or shutil.which("chrome")
        )
        kw: dict[str, Any] = {
            "user_data_dir": str(self._profile_dir),
            "lang": self._lang,
            "headless": self._headless,
        }
        if exe:
            kw["browser_executable_path"] = exe

        args = list(self._extra_args)
        if not any("--window-size" in a for a in args):
            args.append(f"--window-size={w},{h}")
        if args:
            kw["browser_args"] = args
        log.debug(
            "launching chrome: exe=%s, display=%s, window=%dx%d",
            exe,
            display_id,
            w,
            h,
        )
        saved_env: dict[str, str | None] = {}
        if display_id:
            saved_env["DISPLAY"] = os.environ.get("DISPLAY")
            os.environ["DISPLAY"] = display_id
        try:
            self._browser = await uc.start(**kw)  # type: ignore[attr-defined]
        finally:
            for key, old in saved_env.items():
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old
        self._browser._keep_user_data_dir = True
        self._tab = await self._browser.get("about:blank")
        await self._install_download_tracking()
        await self._enable_tab_tracking(self._tab)

    async def close(self) -> None:
        """Tear down the browser and all tabs."""
        with contextlib.suppress(Exception):
            if self._browser:
                self._browser.stop()
        self._browser = None
        self._tab = None

    async def navigate(
        self, url: str, *, headers: dict[str, str] | None = None,
    ) -> None:
        """Load ``url`` in the current tab.

        Returns once the document has finished loading (``Page.loadEventFired``,
        bounded by ``_NAV_LOAD_TIMEOUT_SEC``) — for a CF-challenged page this is
        the challenge document; the CF pipeline drives the subsequent reload(s).
        A navigation that becomes a download instead waits for the file.

        The result is read back via :meth:`response_meta` (final URL + headers)
        and :meth:`content` (body), which the caller invokes *after* the CF
        pipeline so they reflect the final page, not the challenge. Headers are
        read at the network layer (CDP), so non-CORS-safelisted headers such as
        ``subscription-userinfo`` are visible — unlike :meth:`fetch`.
        """
        from nodriver.cdp import network as cdp_net
        from nodriver.cdp import page as cdp_page

        tab = await self._get_tab()
        self._nav_url = url
        self._last_doc = None
        self._download = {}
        self._doc_seen = asyncio.Event()
        self._download_done = asyncio.Event()

        # Set or clear extra HTTP headers for this navigation. Headers persist
        # across the CF pipeline's reload(s) and are only replaced by the next
        # navigate() call, so Authorization etc. survive challenge redirects.
        await tab.send(cdp_net.set_extra_http_headers(
            headers=cdp_net.Headers(headers or {}),
        ))

        load_fired = asyncio.Event()
        network_idle = asyncio.Event()

        def _on_load(_ev: Any, *_: Any) -> None:
            load_fired.set()

        def _on_lifecycle(ev: Any, *_a: Any) -> None:
            if getattr(ev, "name", "") == "networkIdle":
                network_idle.set()

        tab.add_handler(cdp_page.LoadEventFired, _on_load)
        tab.add_handler(cdp_page.LifecycleEvent, _on_lifecycle)
        await tab.send(cdp_page.enable())
        await tab.send(cdp_page.set_lifecycle_events_enabled(enabled=True))
        try:
            # Use raw CDP Page.navigate instead of tab.get() — the latter
            # calls attach() which creates a NEW CDP session and silently
            # invalidates the Page/Network domains we already enabled,
            # causing LoadEventFired and ResponseReceived to stop flowing.
            try:
                result = await asyncio.wait_for(
                    tab.send(cdp_page.navigate(url=url)),
                    timeout=_NAV_LOAD_TIMEOUT_SEC,
                )
                error_text = result[2] if len(result) > 2 else None
                if error_text:
                    log.debug("Page.navigate error_text: %s", error_text)
            except Exception:
                log.debug("Page.navigate raised", exc_info=True)
            if not self._doc_seen.is_set():
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._doc_seen.wait(), timeout=_NAV_HEADER_SETTLE_SEC
                    )
            if self._download.get("guid"):
                if not self._download_done.is_set():
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(
                            self._download_done.wait(),
                            timeout=_NAV_DOWNLOAD_TIMEOUT_SEC,
                        )
                return
            if not load_fired.is_set():
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        load_fired.wait(), timeout=_NAV_LOAD_TIMEOUT_SEC
                    )
            if not network_idle.is_set():
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        network_idle.wait(),
                        timeout=_NAV_NETWORK_IDLE_SEC,
                    )
        finally:
            tab.remove_handler(cdp_page.LoadEventFired, _on_load)
            tab.remove_handler(
                cdp_page.LifecycleEvent, _on_lifecycle,
            )

    def response_meta(self) -> NavigateResult:
        """Final URL + response headers of the latest navigation.

        Read *after* the CF pipeline so they reflect the final
        main-frame document.
        """
        download = self._download
        if download.get("guid"):
            final_url = download.get("url") or self._nav_url
            last = self._last_doc
            headers = last[2] if last and last[0] == final_url else {}
            return NavigateResult(final_url=final_url, headers=headers)
        if self._last_doc is not None:
            return NavigateResult(
                final_url=self._last_doc[0], headers=self._last_doc[2]
            )
        return NavigateResult(final_url=self._nav_url, headers={})

    async def content(self) -> str | None:
        """Body of the latest navigation, on demand.

        For a download it is the captured file (read once, then deleted). For a
        normal page it is the main-frame document's raw response body (CDP
        ``Network.getResponseBody``), falling back to the rendered DOM text if
        the network cache no longer has it. ``None`` if nothing is available.
        """
        if self._download.get("guid"):
            return self._read_download(self._download)
        if self._last_doc is not None:
            tab = await self._get_tab()
            body = await self._get_response_body(tab, self._last_doc[1])
            if body is not None:
                return body
        with contextlib.suppress(Exception):
            return await asyncio.wait_for(
                self.evaluate("document.body.innerText"), timeout=5.0
            )
        return None

    async def evaluate(self, js: str, *, await_promise: bool = False) -> Any:
        """Run ``js`` in the current tab."""
        tab = await self._get_tab()
        return await tab.evaluate(js, await_promise=await_promise)

    async def fetch(self, url: str, *, opts: FetchOptions | None = None) -> FetchResult:
        """Run a same-origin XHR from inside the current tab.

        Raises:
            CFFetchFailed: JSON parse error, fetch() reject, or browser error.
            CFSessionDead: If the Chrome process is dead.
        """
        o = opts or FetchOptions()
        body_text = (
            o.body.decode("utf-8", errors="replace")
            if isinstance(o.body, bytes)
            else o.body
        )
        opts_payload = {
            "method": o.method,
            "headers": o.headers,
            "body": body_text,
            "form": o.form,
            "follow_redirects": o.follow_redirects,
            "timeout": o.timeout,
        }
        js = _FETCH_JS % {
            "url": json.dumps(url),
            "opts": json.dumps(opts_payload),
        }
        tab = await self._get_tab()
        raw = await tab.evaluate(js, await_promise=True)
        try:
            parsed: dict[str, Any] = json.loads(raw)
        except (TypeError, ValueError) as e:
            raise CFFetchFailed("fetch() returned non-JSON", raw=raw) from e
        if "__error" in parsed:
            raise CFFetchFailed(f"browser fetch threw: {parsed['__error']}", url=url)
        return FetchResult(
            status=parsed["status"],
            final_url=parsed["final_url"],
            headers=parsed["headers"],
            body=parsed["body"],
            elapsed_ms=parsed["elapsed_ms"],
        )

    async def get_cookies(self, *, host: str | None = None) -> list[Cookie]:
        """Return cookies; optionally filter to a single host (domain suffix match)."""
        from nodriver.cdp import network as cdp_net

        tab = await self._get_tab()
        raw = await tab.send(cdp_net.get_cookies())
        out: list[Cookie] = []
        for c in raw:
            domain = getattr(c, "domain", "") or ""
            if host and not (
                domain.lstrip(".") == host
                or domain.endswith("." + host)
                or domain == "." + host
            ):
                continue
            raw_same_site = getattr(c, "same_site", None)
            raw_expires = getattr(c, "expires", None)
            out.append(
                Cookie(
                    name=getattr(c, "name", ""),
                    value=getattr(c, "value", ""),
                    domain=domain,
                    path=getattr(c, "path", "/") or "/",
                    secure=bool(getattr(c, "secure", False)),
                    http_only=bool(getattr(c, "http_only", False)),
                    same_site=(
                        raw_same_site.value
                        if hasattr(raw_same_site, "value")
                        else raw_same_site
                    ),
                    expires=raw_expires if raw_expires and raw_expires != -1 else None,
                )
            )
        return out

    async def screenshot(self) -> bytes:
        """Capture current tab viewport, return PNG bytes."""
        tab = await self._get_tab()
        b64 = await tab.screenshot_b64()
        return base64.b64decode(b64)

    async def find_text_and_click(self, text: str, *, timeout: float = 10.0) -> bool:
        """Find element containing ``text`` across all frames, CDP-click it."""
        try:
            el = await self._tab.find(text, timeout=timeout)
            if el:
                await el.mouse_click()
                return True
        except Exception:
            pass
        return False

    async def _find_oopif_target(self, src_contains: str) -> Any | None:
        """Find an OOPIF target whose URL contains *src_contains*."""
        from nodriver.cdp import target as cdp_target

        targets = await self._tab.send(cdp_target.get_targets())
        for t in targets:
            url = getattr(t, "url", "") or ""
            if src_contains in url:
                return t
        return None

    async def find_iframe(self, src_contains: str) -> IframeInfo | None:
        """Discover OOPIF iframe: target → text + DOM walk → position."""
        from nodriver import cdp
        from nodriver.cdp import target as cdp_target

        session_id = None
        try:
            target_info = await self._find_oopif_target(src_contains)
            if target_info is None:
                return None
            src = getattr(target_info, "url", "")

            # Read text via OOPIF attachment
            text: str | None = None
            try:
                session_id = await self._tab.send(
                    cdp_target.attach_to_target(
                        target_id=target_info.target_id,
                        flatten=True,
                    )
                )
                oopif_doc = await self._tab.send(
                    cdp.dom.get_document(depth=-1, pierce=True),
                    sessionId=str(session_id),
                )
                texts: list[str] = []
                self._collect_text_nodes(oopif_doc, texts)
                text = " ".join(texts) or None
            except Exception:
                pass
            finally:
                if session_id is not None:
                    with contextlib.suppress(Exception):
                        await self._tab.send(
                            cdp_target.detach_from_target(
                                session_id=session_id
                            )
                        )
                    session_id = None

            # Get position via parent DOM walk
            doc = await self._tab.send(
                cdp.dom.get_document(depth=-1, pierce=True)
            )
            result = self._find_iframe_by_src(doc, src_contains)
            if result is None:
                return IframeInfo(
                    src=src,
                    rect=ViewportRect(
                        x=0, y=0, width=0, height=0,
                    ),
                    text=text,
                )
            node, _ = result

            remote_obj = await self._tab.send(
                cdp.dom.resolve_node(
                    backend_node_id=node.backend_node_id
                )
            )
            quads = await self._tab.send(
                cdp.dom.get_content_quads(
                    object_id=remote_obj.object_id
                )
            )
            if not quads:
                return IframeInfo(
                    src=src,
                    rect=ViewportRect(
                        x=0, y=0, width=0, height=0,
                    ),
                    text=text,
                )

            pts = list(quads[0])
            rect = ViewportRect(
                x=pts[0], y=pts[1],
                width=pts[2] - pts[0],
                height=pts[5] - pts[1],
            )
            return IframeInfo(src=src, rect=rect, text=text)
        except Exception:
            return None

    @staticmethod
    def _collect_text_nodes(
        node: object, out: list[str],
    ) -> None:
        """Walk a DOM tree collecting text node values."""
        if getattr(node, "node_type", 0) == 3:
            val = (
                getattr(node, "node_value", "") or ""
            ).strip()
            if val:
                out.append(val)
        for sr in getattr(node, "shadow_roots", None) or []:
            NodriverDriver._collect_text_nodes(sr, out)
        for child in (
            getattr(node, "children", None) or []
        ):
            NodriverDriver._collect_text_nodes(child, out)
        if getattr(node, "content_document", None):
            NodriverDriver._collect_text_nodes(
                node.content_document, out,
            )

    @staticmethod
    def _find_iframe_by_src(node, src_contains: str) -> tuple[Any, str] | None:  # noqa: ANN001
        """Recursively traverse DOM tree to find iframe by src.

        Returns ``(node, matched_src)`` or ``None``.
        Searches shadow roots and content documents.
        """
        if (node.node_name or "").upper() == "IFRAME":
            attrs = {}
            if node.attributes:
                it = iter(node.attributes)
                for k in it:
                    attrs[k] = next(it, "")
            src = attrs.get("src", "")
            if src_contains in src:
                return (node, src)

        for child in node.children or []:
            r = NodriverDriver._find_iframe_by_src(child, src_contains)
            if r:
                return r
        for child in node.shadow_roots or []:
            r = NodriverDriver._find_iframe_by_src(child, src_contains)
            if r:
                return r
        if node.content_document:
            r = NodriverDriver._find_iframe_by_src(node.content_document, src_contains)
            if r:
                return r
        return None

    async def _get_tab(self) -> Any:
        """Return a live tab. Recreate if previous closed. Raise if browser dead."""
        async with self._tab_lock:
            if not self._browser or self._browser.stopped:
                raise CFSessionDead("Chrome process is dead")
            if (
                self._tab is None
                or not self._tab.socket
                or bool(self._tab.socket.close_code)
            ):
                self._tab = await self._browser.get("about:blank")
                await self._enable_tab_tracking(self._tab)
            return self._tab

    async def _get_response_body(self, tab: Any, request_id: Any) -> str | None:
        """Read a response body from the network cache via CDP.

        Returns ``None`` on failure (e.g. evicted, or a response with
        no retrievable body such as 403 error pages).
        """
        from nodriver.cdp import network as cdp_net

        try:
            data, b64 = await asyncio.wait_for(
                tab.send(cdp_net.get_response_body(request_id)),
                timeout=5.0,
            )
        except Exception:
            log.debug("get_response_body unavailable (request_id=%s)", request_id)
            return None
        if b64:
            try:
                return base64.b64decode(data).decode("utf-8", errors="replace")
            except (ValueError, TypeError):
                log.warning("navigate: failed to decode base64 body", exc_info=True)
                return None
        return data

    async def _ensure_download_dir(self, conn: Any) -> None:
        """Point Chrome downloads at a controlled temp dir (idempotent)."""
        from nodriver.cdp import browser as cdp_browser

        if self._download_dir is None:
            self._download_dir = self._profile_dir / "_downloads"
        self._download_dir.mkdir(parents=True, exist_ok=True)
        await conn.send(
            cdp_browser.set_download_behavior(
                behavior="allowAndName",
                download_path=str(self._download_dir),
                events_enabled=True,
            )
        )

    def _read_download(self, download: dict[str, Any]) -> str | None:
        """Read the finished download file (named by guid), then delete it."""
        if download.get("canceled"):
            log.warning("navigate: download canceled (%s)", download.get("url"))
            return None
        path_str = download.get("file_path")
        path = Path(path_str) if path_str else None
        if (path is None or not path.exists()) and self._download_dir is not None:
            # ``allowAndName`` saves the file under the download guid.
            guid = download.get("guid")
            if guid:
                path = self._download_dir / guid
        if path is None or not path.exists():
            log.warning("navigate: download file not found (%s)", download.get("url"))
            return None
        try:
            data = path.read_bytes()
            return data.decode("utf-8", errors="replace")
        except OSError:
            log.warning("navigate: failed to read download %s", path, exc_info=True)
            return None
        finally:
            with contextlib.suppress(OSError):
                path.unlink()

    # A single long-lived Network listener (installed once per tab) records the
    # latest main-frame document and any download. This keeps navigate() a plain
    # one-shot load: the meaningful response (headers/body/final URL) belongs to
    # the *final* main-frame document, which only exists after Cloudflare's
    # reload(s), so the tracker is read back via response_meta()/content()
    # *after* the CF pipeline — no per-call listener juggling, no teardown.

    def _on_response(self, ev: Any, *_: Any) -> None:
        from nodriver.cdp import network as cdp_net

        if ev.type_ is not cdp_net.ResourceType.DOCUMENT or ev.response is None:
            return
        # Lock onto the first DOCUMENT's frame as the main frame, then follow
        # only that frame: subframe/iframe documents are ignored, while CF
        # reloads (same main frame) overwrite the challenge response.
        if self._main_frame_id is None:
            self._main_frame_id = ev.frame_id
        if ev.frame_id is not None and ev.frame_id != self._main_frame_id:
            return
        self._last_doc = (ev.response.url, ev.request_id, dict(ev.response.headers))
        self._doc_seen.set()

    def _on_download_begin(self, ev: Any, *_: Any) -> None:
        self._download.setdefault("guid", ev.guid)
        self._download.setdefault("url", ev.url)

    def _on_download_progress(self, ev: Any, *_: Any) -> None:
        if self._download.get("guid") != ev.guid:
            return
        if ev.state == "completed":
            self._download["file_path"] = ev.file_path
            self._download_done.set()
        elif ev.state == "canceled":
            self._download["canceled"] = True
            self._download_done.set()

    async def _install_download_tracking(self) -> None:
        """Attach browser-level download listeners + download dir (once)."""
        from nodriver.cdp import browser as cdp_browser

        # ``Browser`` subclasses ``Connection``; download events fire on it.
        self._browser.add_handler(
            cdp_browser.DownloadWillBegin, self._on_download_begin
        )
        self._browser.add_handler(
            cdp_browser.DownloadProgress, self._on_download_progress
        )
        await self._ensure_download_dir(self._browser)

    async def _enable_tab_tracking(self, tab: Any) -> None:
        """Enable Network and attach the response listener on ``tab``."""
        from nodriver.cdp import network as cdp_net

        self._main_frame_id = None  # new tab → relearn the main frame
        tab.add_handler(cdp_net.ResponseReceived, self._on_response)
        await tab.send(cdp_net.enable())
