#!/usr/bin/env python3
"""core/browser.py — 沙箱 Chrome 启动：干净 profile + 注入真实 cookie + 自动清理。

原理：用 patchright（Playwright 反检测版）+ 系统真 Chrome（channel="chrome"）起一个
独立 profile 的浏览器（同机同出口 IP、同 UA），注入从真实 profile 解密出的 cookie，
让目标站点把它当成"真人已登录/已过检的设备"直接放行。不挂载、不干扰你正在用的
Chrome。原来 5 个脚本里各自重复的 profile 目录准备/清理 Singleton 锁/启动 context/
注入 cookie/收尾关闭这套样板代码，统一收在 sandboxed_page() 里。
"""

import sys
from contextlib import contextmanager
from pathlib import Path

TRANSIENT = ("ERR_NETWORK_CHANGED", "ERR_CONNECTION", "ERR_ABORTED",
             "ERR_NAME_NOT_RESOLVED", "ERR_TIMED_OUT", "Timeout")


def goto_retry(page, url, timeout_s, tries=3):
    """跳转，遇到瞬时网络错误自动重试；其它异常直接抛出。"""
    last = None
    for _ in range(tries):
        try:
            return page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        except Exception as e:
            last = e
            if any(x in str(e) for x in TRANSIENT):
                page.wait_for_timeout(1500)
                continue
            raise
    raise last


def work_profile_dir(tag):
    """本工具专用的干净 profile 目录：~/.config/google-chrome-<tag>"""
    return str(Path.home() / ".config" / f"google-chrome-{tag}")


def _clear_stale_locks(profile_dir):
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (Path(profile_dir) / name).unlink()
        except FileNotFoundError:
            pass


@contextmanager
def sandboxed_page(profile_dir, cookies=None, headless=False):
    """起一个持久化 profile 的干净 Chrome，注入 cookies 后 yield page；
    退出 with 块时自动关闭 context（调用方不需要关心 context 生命周期）。"""
    from patchright.sync_api import sync_playwright

    _clear_stale_locks(profile_dir)
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                profile_dir, channel="chrome", headless=headless, no_viewport=True)
        except Exception as e:
            raise SystemExit(
                f"启动 Chrome 失败：{e!r}\n"
                f"若提示 profile 被占用：pkill -f {Path(profile_dir).name}（只杀本工具的浏览器）")
        if cookies:
            try:
                ctx.add_cookies(cookies)
            except Exception as e:
                print(f"[debug] add_cookies 失败: {e!r}", file=sys.stderr)
        try:
            yield ctx.pages[0] if ctx.pages else ctx.new_page()
        finally:
            try:
                ctx.close()
            except Exception:
                pass
