"""L3: integration tests for NodriverDriver against mocked nodriver."""

import base64
import contextlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nodriver.cdp import page as cdp_page

from clearancekit.errors import CFSessionDead
from clearancekit.transports.nodriver import NodriverDriver


@pytest.fixture
def driver(tmp_path: Path) -> NodriverDriver:
    return NodriverDriver(profile_dir=tmp_path / "profile")


@pytest.fixture
def mock_browser():
    b = MagicMock()
    b.stopped = False
    b.get = AsyncMock()
    b.stop = MagicMock()
    b.cookies = MagicMock()
    b.cookies.get_all = AsyncMock(return_value=[])
    b.send = AsyncMock()
    b.add_handler = MagicMock()
    b.remove_handler = MagicMock()
    return b


@pytest.fixture
def mock_tab():
    t = MagicMock()
    t.closed = False
    t.get = AsyncMock()
    t.send = AsyncMock()
    t.evaluate = AsyncMock(return_value=None)
    t.screenshot_b64 = AsyncMock(return_value="")
    # Track handlers so tests can fire CDP events (e.g. LoadEventFired).
    t._handlers: dict[type, list] = {}

    def _add_handler(event_type, callback):
        t._handlers.setdefault(event_type, []).append(callback)

    def _remove_handler(event_type, callback):
        cbs = t._handlers.get(event_type, [])
        with contextlib.suppress(ValueError):
            cbs.remove(callback)

    t.add_handler = MagicMock(side_effect=_add_handler)
    t.remove_handler = MagicMock(side_effect=_remove_handler)
    return t


def _fire_tab_event(mock_tab, event_type, ev=None):
    """Invoke all handlers registered for ``event_type`` on the mock tab."""
    if ev is None:
        ev = MagicMock()
    for cb in list(mock_tab._handlers.get(event_type, [])):
        cb(ev)


async def _start_driver(driver, mock_browser, mock_tab):
    """Helper to start a driver with mocked nodriver."""
    mock_browser.get.return_value = mock_tab
    with (
        patch("nodriver.start", AsyncMock(return_value=mock_browser)),
        patch("clearancekit._compat.nodriver.apply"),
    ):
        await driver.start()
    return driver


class TestStartAndClose:
    @pytest.mark.asyncio
    async def test_start_calls_uc_start_and_apply_compat(
        self, driver, mock_browser, mock_tab
    ):
        mock_browser.get.return_value = mock_tab
        with (
            patch("nodriver.start", AsyncMock(return_value=mock_browser)) as start,
            patch("clearancekit._compat.nodriver.apply") as compat,
        ):
            await driver.start()
            assert driver.is_started()
            compat.assert_called_once()
            start.assert_called_once()
            kw = start.call_args.kwargs
            assert "user_data_dir" in kw

    @pytest.mark.asyncio
    async def test_is_started_false_before_start(self, driver):
        assert not driver.is_started()

    @pytest.mark.asyncio
    async def test_close_stops_browser(self, driver, mock_browser, mock_tab):
        await _start_driver(driver, mock_browser, mock_tab)
        await driver.close()
        mock_browser.stop.assert_called_once()
        assert not driver.is_started()


class TestGetTab:
    @pytest.mark.asyncio
    async def test_raises_session_dead_when_browser_not_alive(
        self, driver, mock_browser, mock_tab
    ):
        await _start_driver(driver, mock_browser, mock_tab)
        mock_browser.stopped = True
        with pytest.raises(CFSessionDead):
            await driver._get_tab()

    @pytest.mark.asyncio
    async def test_recreates_tab_when_closed(self, driver, mock_browser, mock_tab):
        new_tab = MagicMock(closed=False)
        new_tab.send = AsyncMock()
        mock_browser.get.side_effect = [mock_tab, new_tab]
        with (
            patch("nodriver.start", AsyncMock(return_value=mock_browser)),
            patch("clearancekit._compat.nodriver.apply"),
        ):
            await driver.start()
        mock_tab.closed = True
        got = await driver._get_tab()
        assert got is new_tab


def _get_cdp_method(cdp_cmd):
    """Peek at a CDP command generator to extract the method name."""
    try:
        cmd_dict = next(cdp_cmd)
        return cmd_dict.get("method", "")
    except Exception:
        return ""


def _make_response_event(*, url, headers, frame_id="F-main", request_id="REQ-1"):
    """Build a fake Network.ResponseReceived event for a Document."""
    from nodriver.cdp import network as cdp_net

    ev = MagicMock()
    ev.type_ = cdp_net.ResourceType.DOCUMENT
    ev.frame_id = frame_id
    ev.request_id = request_id
    ev.response = MagicMock()
    ev.response.url = url
    ev.response.headers = headers
    return ev


class TestNavigate:
    @pytest.mark.asyncio
    async def test_navigate_captures_headers_and_content(
        self, driver, mock_browser, mock_tab
    ):
        await _start_driver(driver, mock_browser, mock_tab)

        async def fake_send(cdp_cmd, **kw):
            method = _get_cdp_method(cdp_cmd)
            if method == "Page.navigate":
                driver._on_response(
                    _make_response_event(
                        url="https://example.com/landed",
                        headers={"subscription-userinfo": "upload=1; download=2"},
                    )
                )
                _fire_tab_event(mock_tab, cdp_page.LoadEventFired)
                return ("F-main", None, None, None)
            return None

        mock_tab.send = AsyncMock(side_effect=fake_send)

        await driver.navigate("https://example.com")
        result = driver.response_meta()

        # Bypass the CDP generator issue with mock request_ids by
        # directly stubbing _get_response_body for the content() call.
        driver._get_response_body = AsyncMock(
            return_value="ss://node-1\nss://node-2\n"
        )
        body = await driver.content()

        assert result.final_url == "https://example.com/landed"
        assert result.headers["subscription-userinfo"] == "upload=1; download=2"
        assert body == "ss://node-1\nss://node-2\n"

    @pytest.mark.asyncio
    async def test_navigate_tracks_main_frame_ignoring_subframes(
        self, driver, mock_browser, mock_tab
    ):
        await _start_driver(driver, mock_browser, mock_tab)

        async def fake_send(cdp_cmd, **kw):
            method = _get_cdp_method(cdp_cmd)
            if method == "Page.navigate":
                driver._on_response(
                    _make_response_event(
                        url="https://example.com/main",
                        headers={"x-main": "1"},
                        frame_id="F-main",
                    )
                )
                driver._on_response(
                    _make_response_event(
                        url="https://ads.example/iframe",
                        headers={"x-iframe": "1"},
                        frame_id="F-iframe",
                    )
                )
                _fire_tab_event(mock_tab, cdp_page.LoadEventFired)
                return ("F-main", None, None, None)
            return None

        mock_tab.send = AsyncMock(side_effect=fake_send)

        await driver.navigate("https://example.com")
        result = driver.response_meta()

        assert result.final_url == "https://example.com/main"
        assert result.headers == {"x-main": "1"}
        driver._get_response_body = AsyncMock(return_value="MAIN-BODY")
        assert await driver.content() == "MAIN-BODY"

    @pytest.mark.asyncio
    async def test_navigate_follows_main_frame_reload(
        self, driver, mock_browser, mock_tab
    ):
        """A CF reload on the same main frame overwrites the challenge doc."""
        await _start_driver(driver, mock_browser, mock_tab)

        async def fake_send(cdp_cmd, **kw):
            method = _get_cdp_method(cdp_cmd)
            if method == "Page.navigate":
                driver._on_response(
                    _make_response_event(
                        url="https://example.com/cf",
                        headers={"x-stage": "challenge"},
                        frame_id="F-main",
                    )
                )
                driver._on_response(
                    _make_response_event(
                        url="https://example.com/real",
                        headers={"x-stage": "final"},
                        frame_id="F-main",
                    )
                )
                _fire_tab_event(mock_tab, cdp_page.LoadEventFired)
                return ("F-main", None, None, None)
            return None

        mock_tab.send = AsyncMock(side_effect=fake_send)

        await driver.navigate("https://example.com")
        result = driver.response_meta()

        assert result.final_url == "https://example.com/real"
        assert result.headers == {"x-stage": "final"}

    @pytest.mark.asyncio
    async def test_navigate_captures_download(
        self, driver, mock_browser, mock_tab, tmp_path
    ):
        await _start_driver(driver, mock_browser, mock_tab)

        dl_file = tmp_path / "download.txt"
        dl_file.write_text("ss://node-1\nss://node-2\n", encoding="utf-8")

        def _begin(guid, url):
            ev = MagicMock()
            ev.guid = guid
            ev.url = url
            return ev

        def _progress(guid, state, file_path):
            ev = MagicMock()
            ev.guid = guid
            ev.state = state
            ev.file_path = file_path
            return ev

        async def fake_send(cdp_cmd, **kw):
            method = _get_cdp_method(cdp_cmd)
            if method == "Page.navigate":
                driver._on_response(
                    _make_response_event(
                        url="https://example.com/sub",
                        headers={
                            "content-disposition": "attachment; filename=sub.txt",
                            "subscription-userinfo": "upload=1; download=2",
                        },
                    )
                )
                driver._on_download_begin(
                    _begin("dl-guid-1", "https://example.com/sub")
                )
                driver._on_download_progress(
                    _progress("dl-guid-1", "completed", str(dl_file))
                )
                return ("F-main", None, None, None)
            return None

        mock_tab.send = AsyncMock(side_effect=fake_send)

        await driver.navigate("https://example.com")
        result = driver.response_meta()
        body = await driver.content()

        assert result.final_url == "https://example.com/sub"
        assert result.headers["subscription-userinfo"] == "upload=1; download=2"
        assert body == "ss://node-1\nss://node-2\n"
        # the temp file is cleaned up after reading
        assert not dl_file.exists()

    @pytest.mark.asyncio
    async def test_navigate_without_document_falls_back(
        self, driver, mock_browser, mock_tab, monkeypatch
    ):
        await _start_driver(driver, mock_browser, mock_tab)
        monkeypatch.setattr(
            "clearancekit.transports.nodriver._NAV_HEADER_SETTLE_SEC", 0.01
        )
        monkeypatch.setattr(
            "clearancekit.transports.nodriver._NAV_LOAD_TIMEOUT_SEC", 0.01
        )

        async def fake_send(cdp_cmd, **kw):
            method = _get_cdp_method(cdp_cmd)
            if method == "Page.navigate":
                return ("F-main", None, None, None)
            return None

        mock_tab.send = AsyncMock(side_effect=fake_send)
        mock_tab.evaluate = AsyncMock(return_value="DOM-TEXT")

        await driver.navigate("https://example.com")
        result = driver.response_meta()

        assert result.final_url == "https://example.com"
        assert result.headers == {}
        assert await driver.content() == "DOM-TEXT"

    @pytest.mark.asyncio
    async def test_content_falls_back_to_dom_when_get_body_fails(
        self, driver, mock_browser, mock_tab
    ):
        await _start_driver(driver, mock_browser, mock_tab)
        driver._get_response_body = AsyncMock(return_value=None)
        mock_tab.evaluate = AsyncMock(return_value="DOM-FALLBACK")

        async def fake_send(cdp_cmd, **kw):
            method = _get_cdp_method(cdp_cmd)
            if method == "Page.navigate":
                driver._on_response(
                    _make_response_event(url="https://example.com/x", headers={})
                )
                _fire_tab_event(mock_tab, cdp_page.LoadEventFired)
                return ("F-main", None, None, None)
            return None

        mock_tab.send = AsyncMock(side_effect=fake_send)

        await driver.navigate("https://example.com")
        assert await driver.content() == "DOM-FALLBACK"


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_passes_args(self, driver, mock_browser, mock_tab):
        await _start_driver(driver, mock_browser, mock_tab)
        mock_tab.evaluate = AsyncMock(return_value="hello")
        r = await driver.evaluate("document.title", await_promise=True)
        assert r == "hello"
        mock_tab.evaluate.assert_called_once()
        kw = mock_tab.evaluate.call_args.kwargs
        assert kw.get("await_promise") is True


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_returns_parsed_result(self, driver, mock_browser, mock_tab):
        await _start_driver(driver, mock_browser, mock_tab)
        fake_response = {
            "status": 200,
            "final_url": "https://x.com/api",
            "headers": {"Content-Type": "application/json"},
            "body": '{"ok":true}',
            "elapsed_ms": 42,
        }
        mock_tab.evaluate = AsyncMock(return_value=json.dumps(fake_response))
        r = await driver.fetch("https://x.com/api")
        assert r.status == 200
        assert r.body == '{"ok":true}'
        assert r.elapsed_ms == 42

    @pytest.mark.asyncio
    async def test_fetch_raises_on_invalid_json(self, driver, mock_browser, mock_tab):
        from clearancekit.errors import CFFetchFailed

        await _start_driver(driver, mock_browser, mock_tab)
        mock_tab.evaluate = AsyncMock(return_value="not json")
        with pytest.raises(CFFetchFailed):
            await driver.fetch("https://x.com/api")


class TestGetCookies:
    @pytest.mark.asyncio
    async def test_get_cookies_filters_by_host(self, driver, mock_browser, mock_tab):
        from types import SimpleNamespace

        await _start_driver(driver, mock_browser, mock_tab)
        fake_cookies = [
            SimpleNamespace(
                name="cf_clearance",
                value="x",
                domain=".x.com",
                path="/",
                secure=True,
                http_only=False,
                same_site="Lax",
                expires=None,
            ),
            SimpleNamespace(
                name="other",
                value="y",
                domain=".y.com",
                path="/",
                secure=False,
                http_only=False,
                same_site=None,
                expires=None,
            ),
        ]
        mock_tab.send = AsyncMock(return_value=fake_cookies)

        r = await driver.get_cookies(host="x.com")
        assert len(r) == 1
        assert r[0].name == "cf_clearance"


class TestScreenshot:
    @pytest.mark.asyncio
    async def test_screenshot_returns_decoded_bytes(
        self,
        driver,
        mock_browser,
        mock_tab,
    ):
        await _start_driver(driver, mock_browser, mock_tab)
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"abc"
        mock_tab.screenshot_b64 = AsyncMock(
            return_value=base64.b64encode(png_bytes).decode()
        )
        r = await driver.screenshot()
        assert r == png_bytes


class TestFindTextAndClick:
    @pytest.mark.asyncio
    async def test_returns_true_when_element_found(
        self, driver, mock_browser, mock_tab
    ):
        await _start_driver(driver, mock_browser, mock_tab)
        fake_el = MagicMock()
        fake_el.mouse_click = AsyncMock()
        mock_tab.find = AsyncMock(return_value=fake_el)

        result = await driver.find_text_and_click("Verify you are human")
        assert result is True
        mock_tab.find.assert_called_once_with("Verify you are human", timeout=10.0)
        fake_el.mouse_click.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_no_element(self, driver, mock_browser, mock_tab):
        await _start_driver(driver, mock_browser, mock_tab)
        mock_tab.find = AsyncMock(return_value=None)

        result = await driver.find_text_and_click("Missing text")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, driver, mock_browser, mock_tab):
        await _start_driver(driver, mock_browser, mock_tab)
        mock_tab.find = AsyncMock(side_effect=Exception("timeout"))

        result = await driver.find_text_and_click("text", timeout=1.0)
        assert result is False


class TestFindIframe:
    @pytest.mark.asyncio
    async def test_returns_info_with_src_rect_and_text(
        self, driver, mock_browser, mock_tab,
    ):
        await _start_driver(driver, mock_browser, mock_tab)

        from clearancekit.transports.base import IframeInfo

        target_info = MagicMock()
        target_info.url = (
            "https://challenges.cloudflare.com/turnstile/abc"
        )
        target_info.target_id = "T1"

        session_id = MagicMock()

        text_node = MagicMock()
        text_node.node_type = 3
        text_node.node_value = "Verify you are human"
        text_node.shadow_roots = None
        text_node.children = None
        text_node.content_document = None

        oopif_doc = MagicMock()
        oopif_doc.node_type = 1
        oopif_doc.node_value = None
        oopif_doc.shadow_roots = []
        oopif_doc.children = [text_node]
        oopif_doc.content_document = None

        fake_node = MagicMock()
        fake_node.node_name = "IFRAME"
        fake_node.attributes = [
            "src",
            "https://challenges.cloudflare.com/turnstile/abc",
        ]
        fake_node.children = []
        fake_node.shadow_roots = []
        fake_node.content_document = None
        fake_node.backend_node_id = 42

        parent_doc = MagicMock()
        parent_doc.node_name = "DOCUMENT"
        parent_doc.attributes = None
        parent_doc.children = [fake_node]
        parent_doc.shadow_roots = []
        parent_doc.content_document = None

        remote_obj = MagicMock()
        remote_obj.object_id = "obj-1"

        quads = [
            [10.0, 20.0, 310.0, 20.0, 310.0, 85.0, 10.0, 85.0],
        ]

        # Flow: get_targets → attach → get_document(oopif) →
        #       detach → get_document(parent) → resolve_node →
        #       get_content_quads
        mock_tab.send = AsyncMock(side_effect=[
            [target_info],
            session_id,
            oopif_doc,
            None,  # detach
            parent_doc,
            remote_obj,
            quads,
        ])

        result = await driver.find_iframe(
            "challenges.cloudflare.com",
        )
        assert result is not None
        assert isinstance(result, IframeInfo)
        assert "turnstile" in result.src
        assert result.rect.x == 10.0
        assert result.rect.width == 300.0
        assert result.text == "Verify you are human"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_target(
        self, driver, mock_browser, mock_tab,
    ):
        await _start_driver(driver, mock_browser, mock_tab)

        mock_tab.send = AsyncMock(return_value=[])

        result = await driver.find_iframe(
            "challenges.cloudflare.com",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(
        self, driver, mock_browser, mock_tab,
    ):
        await _start_driver(driver, mock_browser, mock_tab)
        mock_tab.send = AsyncMock(
            side_effect=Exception("CDP error"),
        )

        result = await driver.find_iframe(
            "challenges.cloudflare.com",
        )
        assert result is None

