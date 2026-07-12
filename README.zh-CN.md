# clearancekit

> **实验性项目** — 个人实验，按原样分享。
> 无支持、无路线图、无保证。仅供学习/个人使用。
> 请遵守目标网站的服务条款。

基于真实 Chromium 的进程内 Cloudflare 绕过工具（底层驱动：[nodriver]），
提供可插拔的挑战管道和自动 Turnstile 求解。

**支持两种 Cloudflare 挑战类型：**
- **被动挑战**（"Just a moment..." 5 秒等待）— 自动检测并等待通过
- **交互式挑战**（Turnstile 复选框 / managed challenge）— 自动检测，通过 OS 级 xdotool 点击

[nodriver]: https://github.com/ultrafunkamsterdam/nodriver

## 功能特性

- **通过 Turnstile 交互式挑战** — OS 级 xdotool 点击，
  无需 CAPTCHA API，无需 token 注入
- 自动通过 Cloudflare 被动挑战（自动等待）
- 在已绕过的浏览器标签页内发起同源 HTTP 请求
- 持久化 Chrome profile — `cf_clearance` cookie 跨请求保持
- 可插拔的 检测 → 聚合 → 求解 管道，支持 solver 回退链
- 通过 `XvfbBackend` 管理虚拟显示（仅 `OSClickSolver` 需要）

## 安装

### Python

```bash
pip install git+https://github.com/zen1f/clearancekit
```

唯一的 Python 依赖是 `nodriver`。

### 系统依赖（OSClickSolver 需要 Linux + X11）

```bash
sudo apt update
sudo apt install -y chromium-browser xdotool x11-utils xvfb
```

### macOS / Windows

使用 Linux 容器运行 `OSClickSolver`：

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium xdotool x11-utils xvfb \
    && rm -rf /var/lib/apt/lists/*
RUN pip install git+https://github.com/zen1f/clearancekit
CMD ["python", "-m", "clearancekit", "selftest"]
```

## 快速开始

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

### 自定义管道

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

### 屏蔽 nodriver 日志

```python
import logging

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(message)s")
for name in ("nodriver", "websockets", "uc"):
    logging.getLogger(name).setLevel(logging.WARNING)
```

## 架构

```
Session
├── BrowserDriver (nodriver)    — Chrome 生命周期、evaluate、fetch、cookies
├── ChallengePipeline           — 检测 → 聚合 → 求解 循环
│   ├── Detectors               — DOMDetector（OOPIF iframe 文本 + DOM 信号）
│   │   └── 投票机制             — MAJORITY / ANY / WEIGHTED + CF_BLOCKED 一票否决
│   └── Solvers                 — PassiveWaitSolver, OSClickSolver
│       └── 回退链               — 按顺序尝试所有匹配的 solver，直到一个成功
└── DisplayBackend (XvfbBackend) — Linux 下的虚拟 X 显示
```

- **Session** = 一个 Chrome 进程 + 一个 `ChallengePipeline`。标签页为内部实现，
  关闭后自动重建。
- **Pipeline** 运行 `Detector` → `Solver` 循环。Solver 按顺序尝试，直到一个
  返回 `success=True`（回退链）。任意 detector 投出 `CF_BLOCKED` 即一票否决。
- **Transport** 层通过 nodriver CDP 与 Chrome 通信。管道内仅使用 `tab.evaluate()`
  （在 Target 事件密集时仍安全）。`tab.send()`（通用 CDP）仅用于管道外的用户 API。

## 扩展

### 自定义 Solver

实现 `ChallengeSolver` Protocol 并添加到 solver 列表。
Solver 按顺序尝试——把廉价的放前面：

```python
class MyPaidSolver:
    name = "paid_api"
    handles = {ck.ChallengeKind.CF_INTERACTIVE}

    async def solve(self, driver, kind, *, display=None):
        # 调用付费验证码 API
        return ck.SolveResult(success=True, solver_name=self.name, elapsed_s=3.0)

pipeline = ck.ChallengePipeline(
    solvers=[
        ck.PassiveWaitSolver(),
        ck.OSClickSolver(),
        MyPaidSolver(),  # 回退：仅在 OS 点击失败后调用
    ],
)
```

参见 `examples/custom_solver.py`。

### 自定义 Detector

实现 `ChallengeDetector` Protocol。对于非 CF 的站点特定封锁（如登录墙），
在 detector 中 `raise` 一个 `CFError` 子类——这会干净地中止管道并传播给调用方。

### 自定义 Display 后端

实现 `DisplayBackend` 协议
（`start()` / `stop()` / `display_id()` / `screen_size()`），
作为 `display=` 传给 `session()` 或 `Session.create()`。

## 多会话模式

clearancekit 不提供会话池——由调用方自行管理。
参见 `examples/caller_managed_pool.py`，约 30 行的注册表实现，
带有 EAFP 自愈逻辑（`CFCookieExpired` → 刷新，`CFSessionDead` → 重建）。

## Solvers

| Solver | 方式 | OS 依赖 | 无头模式 |
|--------|------|---------|---------|
| `PassiveWaitSolver` | 等待被动挑战自行通过 | 无 | 支持 |
| `OSClickSolver` | 通过 OOPIF target 定位 CF iframe，xdotool 点击 | Linux + X11 + xdotool | 不支持 |

默认 solver 链：`PassiveWaitSolver` → `OSClickSolver`。

## 限制

1. **`OSClickSolver` 需要 Linux + X11。** Mac/Win 用户请使用 Linux 容器。
2. **必须 `headless=False`。** CF 反检测与无头模式不兼容。
3. **`fetch()` 仅文本 + 同源。** 不支持二进制 / 跨域。
4. **IP 封禁不可恢复。** 库不提供 IP 轮换。
5. **无会话池。** 调用方管理生命周期。
6. **无状态查询 API。** 纯 EAFP——尝试操作并捕获异常。

## 许可证

AGPL-3.0-or-later。

## 致谢

- [nodriver](https://github.com/ultrafunkamsterdam/nodriver) — 反检测 Chromium 驱动
- [xdotool](https://www.semicomplete.com/projects/xdotool/) — X11 输入自动化（仅 OSClickSolver）
