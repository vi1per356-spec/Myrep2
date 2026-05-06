"""
ruklaTikTok.py — TikTok Playwright bot module.

• Integrates with rukla5.py via register_callbacks(bot).
  All controls are inline-keyboard buttons — no slash-commands required.
• Standalone CLI mode is still available:
    python ruklaTikTok.py --run-once #hashtag "comment {A|B}"

Panel entry point: callback_data = 'tiktok_pw_panel'
(rukla5 adds the button; this file handles everything from that point on)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright_stealth import stealth_async
from telebot import types

# ─────────────────────────── logging ──────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ruklaTikTok")


# ══════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AccountConfig:
    account_id:      str
    username:        str
    password:        str
    # Supported formats:
    #   IP:PORT:USER:PASS | IP:PORT
    #   socks5://[user:pass@]host:port
    #   "" (no proxy)
    proxy:           str
    cookies_file:    str
    user_agent:      str = ""
    viewport_width:  int = 0
    viewport_height: int = 0


@dataclass
class BotConfig:
    """Used only in standalone --run-once mode."""
    accounts:           list
    telegram_api_id:    int  = 0
    telegram_api_hash:  str  = ""
    telegram_bot_token: str  = ""
    telegram_chat_id:   int  = 0
    headless:           bool = True
    slow_mo:            int  = 50


# ══════════════════════════════════════════════════════════════════════════════
#  STATIC POOLS
# ══════════════════════════════════════════════════════════════════════════════

_MOBILE_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.66 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; SM-G998B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.5790.166 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; OnePlus 11) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Mobile Safari/537.36",
]

_VIEWPORT_PRESETS: list[tuple[int, int]] = [
    (390, 844),  # iPhone 14
    (393, 852),  # iPhone 15
    (375, 812),  # iPhone X / XS
    (414, 896),  # iPhone 11 Pro Max
    (428, 926),  # iPhone 14 Plus
    (412, 915),  # Pixel 7
    (411, 890),  # Pixel 6 Pro
    (360, 780),  # Samsung Galaxy S21
    (384, 854),  # Samsung Galaxy A54
]

_UA_GEO_BASES: list[tuple[float, float]] = [
    (50.4501, 30.5234),  # Kyiv
    (49.8397, 24.0297),  # Lviv
    (49.9935, 36.2304),  # Kharkiv
    (48.4647, 35.0462),  # Dnipro
    (47.8388, 35.1396),  # Zaporizhzhia
    (46.9775, 31.9946),  # Mykolaiv
]


# ══════════════════════════════════════════════════════════════════════════════
#  SPINTAX ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class SpintaxEngine:
    """Recursively resolves nested {option1|option2|…} patterns."""

    _PATTERN = re.compile(r"\{([^{}]+)\}")

    def spin(self, text: str) -> str:
        while True:
            m = self._PATTERN.search(text)
            if not m:
                break
            options = m.group(1).split("|")
            text = text[: m.start()] + random.choice(options) + text[m.end():]
        return text


# ══════════════════════════════════════════════════════════════════════════════
#  TIKTOK SESSION
# ══════════════════════════════════════════════════════════════════════════════

class TikTokSession:
    """
    One fully-isolated TikTok session per account.
    Owns its own Browser + BrowserContext — fingerprints, cookies and
    proxy settings never bleed between accounts.
    """

    def __init__(self, account: AccountConfig, pw: Playwright) -> None:
        self.account  = account
        self._pw      = pw
        self.browser: Optional[Browser]        = None
        self.context: Optional[BrowserContext] = None
        self.page:    Optional[Page]           = None
        self._spintax = SpintaxEngine()
        self._assign_random_identity()

    # ── identity ──────────────────────────────────────────────────────────────

    def _assign_random_identity(self) -> None:
        if not self.account.user_agent:
            self.account.user_agent = random.choice(_MOBILE_USER_AGENTS)
        if not self.account.viewport_width:
            w, h = random.choice(_VIEWPORT_PRESETS)
            self.account.viewport_width  = w
            self.account.viewport_height = h

    def _parse_proxy(self) -> Optional[dict]:
        proxy = self.account.proxy
        if not proxy:
            return None

        # socks5://[user:pass@]host:port
        if proxy.startswith("socks5://"):
            rest = proxy[9:]
            if "@" in rest:
                auth, hostport = rest.split("@", 1)
                user, pwd = auth.split(":", 1)
                return {"server": f"socks5://{hostport}", "username": user, "password": pwd}
            return {"server": proxy}

        # http[s]:// — pass through as-is
        if proxy.startswith(("http://", "https://")):
            return {"server": proxy}

        # IP:PORT:USER:PASS
        parts = proxy.split(":")
        if len(parts) == 4:
            ip, port, user, password = parts
            return {"server": f"http://{ip}:{port}", "username": user, "password": password}

        # IP:PORT
        if len(parts) == 2:
            ip, port = parts
            return {"server": f"http://{ip}:{port}"}

        logger.warning("[%s] unrecognised proxy format, skipping: %r", self.account.account_id, proxy)
        return None

    def _random_geolocation(self) -> dict:
        lat, lon = random.choice(_UA_GEO_BASES)
        return {
            "latitude":  lat + random.uniform(-0.05, 0.05),
            "longitude": lon + random.uniform(-0.05, 0.05),
        }

    # ── browser lifecycle ─────────────────────────────────────────────────────

    async def launch(self) -> None:
        proxy = self._parse_proxy()

        self.browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--disable-gpu",
                "--lang=uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            ],
        )

        ctx_kwargs: dict = {
            "user_agent":          self.account.user_agent,
            "viewport":            {"width": self.account.viewport_width, "height": self.account.viewport_height},
            "locale":              "uk-UA",
            "timezone_id":         "Europe/Kyiv",
            "permissions":         ["geolocation"],
            "geolocation":         self._random_geolocation(),
            "color_scheme":        "light",
            "device_scale_factor": random.choice([2.0, 3.0]),
            "is_mobile":           True,
            "has_touch":           True,
            "extra_http_headers":  {"Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"},
        }
        if proxy is not None:
            ctx_kwargs["proxy"] = proxy

        self.context = await self.browser.new_context(**ctx_kwargs)
        self.page    = await self.context.new_page()
        await stealth_async(self.page)

        logger.info(
            "[%s] launched  UA=%.35s…  %dx%d  proxy=%s",
            self.account.account_id,
            self.account.user_agent,
            self.account.viewport_width,
            self.account.viewport_height,
            (proxy["server"] if proxy else "none"),
        )

    async def close(self) -> None:
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
        except Exception as exc:
            logger.warning("[%s] close error: %s", self.account.account_id, exc)

    # ── cookie management ─────────────────────────────────────────────────────

    async def load_cookies(self) -> bool:
        path = Path(self.account.cookies_file)
        if not path.exists():
            logger.info("[%s] no cookies file at %s", self.account.account_id, path)
            return False
        try:
            cookies = json.loads(path.read_text(encoding="utf-8"))
            await self.context.add_cookies(cookies)
            logger.info("[%s] cookies loaded (%d entries)", self.account.account_id, len(cookies))
            return True
        except Exception as exc:
            logger.warning("[%s] load cookies error: %s", self.account.account_id, exc)
            return False

    async def save_cookies(self) -> None:
        cookies = await self.context.cookies()
        path = Path(self.account.cookies_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("[%s] cookies saved (%d entries)", self.account.account_id, len(cookies))

    # ── auth ──────────────────────────────────────────────────────────────────

    async def verify_login(self) -> bool:
        try:
            await self.page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=35_000)
        except Exception as exc:
            logger.warning("[%s] verify_login nav error: %s", self.account.account_id, exc)
            return False

        await self._delay(2_500, 4_500)

        for sel in ['[data-e2e="profile-icon"]', '[data-e2e="nav-upload"]', 'a[href*="/upload"]']:
            try:
                await self.page.wait_for_selector(sel, timeout=6_000)
                logger.info("[%s] session valid (%s)", self.account.account_id, sel)
                return True
            except Exception:
                pass

        for sel in ['[data-e2e="nav-login-button"]', 'a[href*="/login"]']:
            try:
                await self.page.wait_for_selector(sel, timeout=3_000)
                return False
            except Exception:
                pass

        return "login" not in self.page.url

    async def login_with_credentials(self) -> bool:
        if not self.account.password:
            logger.info("[%s] no password configured, skipping credential login", self.account.account_id)
            return False
        logger.info("[%s] credential login attempt", self.account.account_id)
        try:
            await self.page.goto(
                "https://www.tiktok.com/login/phone-or-email/email",
                wait_until="domcontentloaded",
                timeout=35_000,
            )
            await self._delay(2_000, 4_000)

            email_input = await self.page.wait_for_selector('input[name="username"]', timeout=15_000)
            await email_input.click()
            await self._delay(300, 700)
            await self._human_type_element(email_input, self.account.username)
            await self._delay(600, 1_200)

            pwd_input = await self.page.wait_for_selector('input[type="password"]', timeout=10_000)
            await pwd_input.click()
            await self._delay(300, 700)
            await self._human_type_element(pwd_input, self.account.password)
            await self._delay(900, 1_800)

            submit = await self.page.wait_for_selector('button[type="submit"]', timeout=10_000)
            await submit.click()
            await self._delay(4_000, 7_000)

            if await self._captcha_present():
                logger.warning("[%s] CAPTCHA detected", self.account.account_id)
                return False

            ok = await self.verify_login()
            if ok:
                await self.save_cookies()
            return ok

        except Exception as exc:
            logger.error("[%s] credential login failed: %s", self.account.account_id, exc)
            return False

    async def ensure_authenticated(self) -> bool:
        if await self.load_cookies():
            if await self.verify_login():
                return True
            logger.info("[%s] cookies stale, trying credentials", self.account.account_id)
        return await self.login_with_credentials()

    async def _captcha_present(self) -> bool:
        for sel in ['[class*="captcha"]', '[id*="captcha"]', 'iframe[src*="captcha"]', '[data-e2e="captcha"]']:
            try:
                await self.page.wait_for_selector(sel, timeout=2_000)
                return True
            except Exception:
                pass
        return False

    # ── FYP warm-up ───────────────────────────────────────────────────────────

    async def warmup_fyp(self) -> None:
        """
        Simulates organic browsing on the For You Page:
          • Watches 3-7 videos for 10-50 s each
          • 15 % chance to like each video
        """
        logger.info("[%s] FYP warm-up start", self.account.account_id)
        try:
            await self.page.goto("https://www.tiktok.com/foryou", wait_until="domcontentloaded", timeout=35_000)
        except Exception as exc:
            logger.warning("[%s] FYP nav error: %s", self.account.account_id, exc)
            return

        await self._delay(2_000, 4_000)
        count = random.randint(3, 7)
        logger.info("[%s] will watch %d FYP videos", self.account.account_id, count)

        for i in range(count):
            watch_secs = random.uniform(10.0, 50.0)
            logger.info("[%s] FYP %d/%d — %.1f s", self.account.account_id, i + 1, count, watch_secs)

            elapsed  = 0.0
            interval = random.uniform(4.0, 10.0)
            while elapsed < watch_secs:
                chunk = min(interval, watch_secs - elapsed)
                await asyncio.sleep(chunk)
                elapsed += chunk
                if random.random() < 0.35:
                    await self._random_mouse_move()

            if random.random() < 0.15:
                await self._like_current_video()

            await self._scroll_next_video()
            await self._delay(900, 2_200)

        logger.info("[%s] FYP warm-up done", self.account.account_id)

    async def _like_current_video(self) -> None:
        for sel in [
            '[data-e2e="like-icon"]',
            '[data-e2e="video-like-icon"]',
            'span[class*="like-icon"]',
            'button[aria-label*="Like"]',
        ]:
            try:
                btn = await self.page.wait_for_selector(sel, timeout=2_500)
                await self._delay(200, 600)
                await btn.click()
                logger.info("[%s] liked FYP video", self.account.account_id)
                await self._delay(400, 900)
                return
            except Exception:
                pass

    async def _scroll_next_video(self) -> None:
        await self.page.keyboard.press("ArrowDown")
        await self._delay(700, 1_400)

    # ── target action: comment under hashtag ──────────────────────────────────

    async def comment_on_hashtag_video(self, hashtag: str, comment_template: str) -> bool:
        hashtag = hashtag.lstrip("#")
        logger.info("[%s] opening hashtag #%s", self.account.account_id, hashtag)

        try:
            await self.page.goto(
                f"https://www.tiktok.com/tag/{hashtag}",
                wait_until="domcontentloaded",
                timeout=35_000,
            )
        except Exception as exc:
            logger.error("[%s] hashtag page error: %s", self.account.account_id, exc)
            return False

        await self._delay(2_500, 4_500)

        links = await self._collect_hashtag_video_links()
        if not links:
            logger.warning("[%s] no videos for #%s", self.account.account_id, hashtag)
            return False

        pool       = links[2:] if len(links) > 2 else links
        target_url = random.choice(pool)

        try:
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=35_000)
        except Exception as exc:
            logger.error("[%s] target video nav error: %s", self.account.account_id, exc)
            return False

        await self._delay(1_500, 3_000)

        watch_secs = random.uniform(5.0, 15.0)
        logger.info("[%s] watching target video %.1f s", self.account.account_id, watch_secs)
        await asyncio.sleep(watch_secs)
        await self._random_mouse_move()

        comment = self._spintax.spin(comment_template)
        logger.info("[%s] composed comment: %r", self.account.account_id, comment)
        return await self._post_comment(comment)

    async def _collect_hashtag_video_links(self) -> list[str]:
        links: list[str] = []
        for sel in [
            '[data-e2e="challenge-item"] a',
            '[class*="VideoCard"] a',
            '[class*="VideoItem"] a',
            'a[href*="/video/"]',
        ]:
            try:
                for el in await self.page.query_selector_all(sel):
                    href = await el.get_attribute("href")
                    if href and "/video/" in href:
                        full = href if href.startswith("http") else f"https://www.tiktok.com{href}"
                        if full not in links:
                            links.append(full)
            except Exception:
                pass
        logger.info("[%s] found %d video links", self.account.account_id, len(links))
        return links

    async def _post_comment(self, comment: str) -> bool:
        # 1. Open comment panel if collapsed
        for sel in [
            '[data-e2e="comment-icon"]',
            'span[class*="CommentIcon"]',
            'button[aria-label*="comment"]',
            'button[aria-label*="Comment"]',
        ]:
            try:
                icon = await self.page.wait_for_selector(sel, timeout=4_000)
                await icon.click()
                await self._delay(900, 1_800)
                break
            except Exception:
                pass

        # 2. Find comment input
        comment_input = None
        for sel in [
            '[data-e2e="comment-input"]',
            'div[contenteditable="true"][class*="comment"]',
            'div[contenteditable="true"][placeholder*="comment"]',
            'div[contenteditable="true"][placeholder*="коментар"]',
            'textarea[placeholder*="comment"]',
            'textarea[placeholder*="Add comment"]',
        ]:
            try:
                comment_input = await self.page.wait_for_selector(sel, timeout=5_000)
                break
            except Exception:
                pass

        if comment_input is None:
            logger.error("[%s] comment input not found", self.account.account_id)
            return False

        await comment_input.click()
        await self._delay(500, 1_000)
        await self._human_type_keyboard(comment)
        await self._delay(700, 1_500)

        # 3. Submit
        for sel in [
            '[data-e2e="comment-post"]',
            'div[data-e2e="comment-submit"]',
            'button[class*="send"]',
            'button[aria-label*="Post"]',
            'button[aria-label*="Send"]',
        ]:
            try:
                submit = await self.page.wait_for_selector(sel, timeout=4_000)
                await submit.click()
                await self._delay(2_500, 5_000)
                logger.info("[%s] comment posted", self.account.account_id)
                return True
            except Exception:
                pass

        # Fallback: Enter key
        await self.page.keyboard.press("Enter")
        await self._delay(2_500, 5_000)
        logger.info("[%s] comment via Enter key", self.account.account_id)
        return True

    # ── human simulation helpers ──────────────────────────────────────────────

    async def _delay(self, min_ms: int = 500, max_ms: int = 2_000) -> None:
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1_000)

    async def _human_type_element(self, element, text: str) -> None:
        for ch in text:
            await element.type(ch, delay=random.uniform(70, 210))
            if random.random() < 0.05:
                await self._delay(250, 700)

    async def _human_type_keyboard(self, text: str) -> None:
        for ch in text:
            await self.page.keyboard.type(ch, delay=random.uniform(70, 230))
            if random.random() < 0.04:
                await self._delay(200, 650)

    async def _random_mouse_move(self) -> None:
        w = self.account.viewport_width
        h = self.account.viewport_height
        await self.page.mouse.move(
            random.randint(int(w * 0.1), int(w * 0.9)),
            random.randint(int(h * 0.1), int(h * 0.9)),
        )
        await self._delay(80, 350)

    # ── full cycle ────────────────────────────────────────────────────────────

    async def full_cycle(self, hashtag: str, comment_template: str) -> dict:
        result: dict = {
            "account_id": self.account.account_id,
            "success":    False,
            "error":      None,
            "timestamp":  datetime.now().isoformat(timespec="seconds"),
        }
        try:
            if not await self.ensure_authenticated():
                result["error"] = "authentication failed"
                return result

            await self.warmup_fyp()
            await self._delay(2_000, 5_000)

            ok = await self.comment_on_hashtag_video(hashtag, comment_template)
            result["success"] = ok
            if not ok:
                result["error"] = "comment not posted"
        except Exception as exc:
            result["error"] = str(exc)
            logger.exception("[%s] unexpected error in full_cycle", self.account.account_id)
        return result


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYWRIGHT LOGIN  — collect cookies by simulating real browser login
# ══════════════════════════════════════════════════════════════════════════════

# Possible results returned by _pw_login_and_collect_async
_LOGIN_OK         = "ok"
_LOGIN_CAPTCHA    = "captcha"
_LOGIN_VERIFY     = "verify"     # email / SMS verification code requested
_LOGIN_WRONG_CRED = "wrong_cred"
_LOGIN_ERROR      = "error"


async def _pw_login_and_collect_async(
    username: str,
    password: str,
    proxy: str = "",
) -> tuple[str, str]:
    """
    Open a stealth Playwright browser, log in to TikTok, collect cookies.

    Returns (status, cookie_str) where status is one of the _LOGIN_* constants
    and cookie_str is 'key=val; key2=val2' (empty string on failure).
    """
    account = AccountConfig(
        account_id      = "_pw_login",
        username        = username,
        password        = password,
        proxy           = proxy,
        cookies_file    = "",   # no file needed
    )

    async with async_playwright() as pw:
        session = TikTokSession(account, pw)
        await session.launch()

        try:
            # ── navigate to login page ────────────────────────────────────
            await session.page.goto(
                "https://www.tiktok.com/login/phone-or-email/email",
                wait_until="domcontentloaded",
                timeout=35_000,
            )
            await session._delay(2_000, 4_500)

            # ── fill username ─────────────────────────────────────────────
            try:
                email_input = await session.page.wait_for_selector(
                    'input[name="username"]', timeout=15_000
                )
            except Exception:
                return _LOGIN_ERROR, ""

            await email_input.click()
            await session._delay(300, 700)
            await session._human_type_element(email_input, username)
            await session._delay(600, 1_200)

            # ── fill password ─────────────────────────────────────────────
            try:
                pwd_input = await session.page.wait_for_selector(
                    'input[type="password"]', timeout=10_000
                )
            except Exception:
                return _LOGIN_ERROR, ""

            await pwd_input.click()
            await session._delay(300, 700)
            await session._human_type_element(pwd_input, password)
            await session._delay(900, 1_800)

            # ── submit ────────────────────────────────────────────────────
            try:
                submit = await session.page.wait_for_selector(
                    'button[type="submit"]', timeout=10_000
                )
                await submit.click()
            except Exception:
                return _LOGIN_ERROR, ""

            await session._delay(4_000, 8_000)

            # ── check post-login state ────────────────────────────────────

            # CAPTCHA
            if await session._captcha_present():
                logger.warning("[_pw_login] CAPTCHA detected")
                return _LOGIN_CAPTCHA, ""

            # Email / SMS verification form
            verify_selectors = [
                'input[placeholder*="code"]',
                'input[placeholder*="код"]',
                'input[name="code"]',
                '[class*="VerifyCode"]',
                '[data-e2e*="verify"]',
            ]
            for sel in verify_selectors:
                try:
                    await session.page.wait_for_selector(sel, timeout=2_500)
                    logger.warning("[_pw_login] verification code screen detected")
                    return _LOGIN_VERIFY, ""
                except Exception:
                    pass

            # Wrong credentials message
            error_selectors = [
                '[class*="error"]',
                '[class*="Error"]',
                '[data-e2e*="error"]',
            ]
            for sel in error_selectors:
                try:
                    el = await session.page.wait_for_selector(sel, timeout=2_000)
                    text = await el.inner_text()
                    if text and len(text.strip()) > 3:
                        logger.warning("[_pw_login] error text on page: %s", text[:80])
                        return _LOGIN_WRONG_CRED, ""
                except Exception:
                    pass

            # Check if logged in
            if not await session.verify_login():
                return _LOGIN_WRONG_CRED, ""

            # ── collect cookies ───────────────────────────────────────────
            pw_cookies = await session.context.cookies()
            tiktok_cookies = [
                c for c in pw_cookies
                if "tiktok.com" in c.get("domain", "")
            ]

            if not tiktok_cookies:
                return _LOGIN_ERROR, ""

            cookie_str = "; ".join(
                f"{c['name']}={c['value']}"
                for c in tiktok_cookies
            )
            logger.info("[_pw_login] collected %d cookies", len(tiktok_cookies))
            return _LOGIN_OK, cookie_str

        except Exception as exc:
            logger.exception("[_pw_login] unexpected error: %s", exc)
            return _LOGIN_ERROR, ""
        finally:
            await session.close()


def pw_login_collect_cookies(
    bot,
    uid:         int,
    username:    str,
    password:    str,
    proxy:       str = "",
    wait_msg_id: int = 0,
) -> None:
    """
    Run Playwright login in a daemon thread.
    On completion sends result back via bot.send_message(uid, ...) and
    appends the account to rukla5's storage if login succeeded.
    """

    def _thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            status, cookie_str = loop.run_until_complete(
                _pw_login_and_collect_async(username, password, proxy)
            )
        except Exception as exc:
            logger.exception("pw_login_collect_cookies thread error")
            status, cookie_str = _LOGIN_ERROR, ""
        finally:
            loop.close()

        # Remove wait message
        if wait_msg_id:
            try:
                bot.delete_message(uid, wait_msg_id)
            except Exception:
                pass

        # ── failure paths ─────────────────────────────────────────────────
        if status == _LOGIN_CAPTCHA:
            bot.send_message(
                uid,
                "⚠️ <b>TikTok показав CAPTCHA</b>\n\n"
                "Playwright не може вирішити CAPTCHA автоматично.\n"
                "Варіанти:\n"
                "• Увійдіть у браузері вручну та скопіюйте <b>кукі</b>\n"
                "• Спробуйте ще раз через кілька хвилин з іншим IP",
                parse_mode="HTML",
            )
            return

        if status == _LOGIN_VERIFY:
            bot.send_message(
                uid,
                "⚠️ <b>Потрібна верифікація (email/SMS)</b>\n\n"
                "TikTok надіслав код підтвердження.\n"
                "Увійдіть у браузері вручну, підтвердіть акаунт, "
                "а потім скопіюйте <b>кукі</b>.",
                parse_mode="HTML",
            )
            return

        if status == _LOGIN_WRONG_CRED:
            bot.send_message(
                uid,
                "❌ <b>Невірний логін або пароль</b>\n\n"
                "Перевірте дані та спробуйте ще раз.",
                parse_mode="HTML",
            )
            return

        if status != _LOGIN_OK or not cookie_str:
            bot.send_message(
                uid,
                "❌ <b>Не вдалося увійти</b>\n\n"
                "Playwright не зміг завершити вхід.\n"
                "Спробуйте додати акаунт через <b>кукі</b>.",
                parse_mode="HTML",
            )
            return

        # ── success — store account ───────────────────────────────────────
        try:
            import rukla5 as _r5
            _r5._load_accounts()
            accounts = _r5._get_user_accounts(uid)

            if len(accounts) >= 25:
                bot.send_message(uid, "⚠️ Досягнуто ліміт у 25 акаунтів")
                return

            # Resolve nickname / unique_id via requests
            valid, nickname, unique_id = _r5._get_tt_info(cookie_str, proxy)

            # Fall back to the user-provided login when the profile API
            # is unavailable (regional / missing tokens) and returns
            # placeholders. This avoids "№1 — — @? ✅" entries.
            _PLACEHOLDER = ('?', '—', '', None, 'unknown')
            fallback = username.split("@")[0] if "@" in username else username
            if not valid or unique_id in _PLACEHOLDER:
                unique_id = fallback or unique_id
            if nickname in _PLACEHOLDER:
                nickname = fallback or nickname

            accounts.append({
                "cookie":    cookie_str,
                "active":    True,
                "nickname":  nickname,
                "unique_id": unique_id,
                "proxy":     proxy,
            })
            _r5._set_user_accounts(uid, accounts)

            bot.send_message(
                uid,
                f"✅ Акаунт <b>{nickname}</b> (@{unique_id}) додано через Playwright",
                parse_mode="HTML",
            )
            # Refresh account list
            text   = _r5._build_accounts_text(uid)
            markup = _r5._acc_markup(uid)
            bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML")

        except Exception as exc:
            logger.exception("pw_login_collect_cookies: account storage error")
            bot.send_message(uid, f"❌ Помилка збереження: {exc}")

    threading.Thread(target=_thread, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYWRIGHT PANEL STATE
# ══════════════════════════════════════════════════════════════════════════════

_PW_SETTINGS_FILE = "playwright_settings.json"
_pw_settings:      dict = {}
_pw_pending_input: dict = {}   # uid -> 'hashtag' | 'comment' | 'spin_test'
_pw_running:       set  = set()  # uids with a job currently executing


def _load_pw_settings() -> None:
    global _pw_settings
    if os.path.exists(_PW_SETTINGS_FILE):
        with open(_PW_SETTINGS_FILE, "r", encoding="utf-8") as f:
            _pw_settings = json.load(f)
    else:
        _pw_settings = {}


def _save_pw_settings() -> None:
    with open(_PW_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(_pw_settings, f, ensure_ascii=False, indent=2)


def _get_pw_settings(uid: int) -> dict:
    uid_str = str(uid)
    if uid_str not in _pw_settings:
        _pw_settings[uid_str] = {"hashtag": "", "comment_template": ""}
    return _pw_settings[uid_str]


# ══════════════════════════════════════════════════════════════════════════════
#  TRANSLATIONS  (Playwright panel)
# ══════════════════════════════════════════════════════════════════════════════

_PW_LX: dict = {
    "uk": {
        "header":        "🎭 <b>Playwright TikTok</b>",
        "row_hashtag":   "🔖 Хештег: <b>{v}</b>",
        "row_template":  "💬 Шаблон: <b>{v}</b>",
        "row_accounts":  "👤 Акаунтів до запуску: <b>{v}</b>",
        "status_run":    "🔄 Статус: <b>виконується...</b>",
        "status_idle":   "🟢 Статус: <b>готовий</b>",
        "none":          "не встановлено",
        "btn_run_all":   "▶️ Запустити всі акаунти",
        "btn_run_one":   "▶️ Акаунт №{i}  (@{nick})",
        "btn_hashtag":   "🔖 Встановити хештег",
        "btn_template":  "💬 Встановити шаблон",
        "btn_test_spin": "🔀 Тест спінтексту",
        "btn_cancel":    "⬅️ Скасувати",
        "btn_back":      "⬅️ Назад",
        "ask_hashtag":   "🔖 Введіть хештег (з # або без):",
        "ask_template":  (
            "💬 Введіть шаблон коментаря.\n"
            "Підтримується спінтекст: <code>{варіант1|варіант2}</code>"
        ),
        "ask_spin":      "🔀 Введіть текст для тесту спінтексту:",
        "no_hashtag":    "⚠️ Спочатку встановіть хештег",
        "no_template":   "⚠️ Спочатку встановіть шаблон коментаря",
        "no_accounts":   "⚠️ Немає активних акаунтів.\nДодайте їх у розділі <b>Акаунти TikTok</b>",
        "already_run":   "⚠️ Playwright вже виконується. Зачекайте завершення.",
        "starting_all":  "⏳ Запускаю Playwright для всіх акаунтів...",
        "starting_one":  "⏳ Запускаю Playwright для акаунту №{i}...",
        "hashtag_set":   "✅ Хештег встановлено: <b>#{v}</b>",
        "template_set":  "✅ Шаблон коментаря встановлено",
        "spin_header":   "🔀 <b>Спінтекст — 5 варіантів:</b>",
        "rep_header":    "📋 <b>Звіт Playwright:</b> {ok}/{total} успішно\n",
        "rep_ok":        "✅ <code>{acc}</code>  {ts}",
        "rep_fail":      "❌ <code>{acc}</code>  {ts}\n   ↳ {err}",
    },
    "en": {
        "header":        "🎭 <b>Playwright TikTok</b>",
        "row_hashtag":   "🔖 Hashtag: <b>{v}</b>",
        "row_template":  "💬 Template: <b>{v}</b>",
        "row_accounts":  "👤 Accounts ready: <b>{v}</b>",
        "status_run":    "🔄 Status: <b>running...</b>",
        "status_idle":   "🟢 Status: <b>idle</b>",
        "none":          "not set",
        "btn_run_all":   "▶️ Run all accounts",
        "btn_run_one":   "▶️ Account №{i}  (@{nick})",
        "btn_hashtag":   "🔖 Set hashtag",
        "btn_template":  "💬 Set template",
        "btn_test_spin": "🔀 Test spintax",
        "btn_cancel":    "⬅️ Cancel",
        "btn_back":      "⬅️ Back",
        "ask_hashtag":   "🔖 Enter hashtag (with or without #):",
        "ask_template":  (
            "💬 Enter comment template.\n"
            "Spintax supported: <code>{option1|option2}</code>"
        ),
        "ask_spin":      "🔀 Enter text to test spintax:",
        "no_hashtag":    "⚠️ Set hashtag first",
        "no_template":   "⚠️ Set comment template first",
        "no_accounts":   "⚠️ No active accounts.\nAdd them in the <b>TikTok Accounts</b> section",
        "already_run":   "⚠️ Playwright is already running. Please wait.",
        "starting_all":  "⏳ Starting Playwright for all accounts...",
        "starting_one":  "⏳ Starting Playwright for account №{i}...",
        "hashtag_set":   "✅ Hashtag set: <b>#{v}</b>",
        "template_set":  "✅ Comment template set",
        "spin_header":   "🔀 <b>Spintax — 5 variants:</b>",
        "rep_header":    "📋 <b>Playwright report:</b> {ok}/{total} success\n",
        "rep_ok":        "✅ <code>{acc}</code>  {ts}",
        "rep_fail":      "❌ <code>{acc}</code>  {ts}\n   ↳ {err}",
    },
    "ru": {
        "header":        "🎭 <b>Playwright TikTok</b>",
        "row_hashtag":   "🔖 Хэштег: <b>{v}</b>",
        "row_template":  "💬 Шаблон: <b>{v}</b>",
        "row_accounts":  "👤 Аккаунтов к запуску: <b>{v}</b>",
        "status_run":    "🔄 Статус: <b>выполняется...</b>",
        "status_idle":   "🟢 Статус: <b>готов</b>",
        "none":          "не задано",
        "btn_run_all":   "▶️ Запустить все аккаунты",
        "btn_run_one":   "▶️ Аккаунт №{i}  (@{nick})",
        "btn_hashtag":   "🔖 Установить хэштег",
        "btn_template":  "💬 Установить шаблон",
        "btn_test_spin": "🔀 Тест спинтекста",
        "btn_cancel":    "⬅️ Отмена",
        "btn_back":      "⬅️ Назад",
        "ask_hashtag":   "🔖 Введите хэштег (с # или без):",
        "ask_template":  (
            "💬 Введите шаблон комментария.\n"
            "Поддерживается спинтекст: <code>{вариант1|вариант2}</code>"
        ),
        "ask_spin":      "🔀 Введите текст для теста спинтекста:",
        "no_hashtag":    "⚠️ Сначала установите хэштег",
        "no_template":   "⚠️ Сначала установите шаблон комментария",
        "no_accounts":   "⚠️ Нет активных аккаунтов.\nДобавьте их в разделе <b>Аккаунты TikTok</b>",
        "already_run":   "⚠️ Playwright уже выполняется. Подождите завершения.",
        "starting_all":  "⏳ Запускаю Playwright для всех аккаунтов...",
        "starting_one":  "⏳ Запускаю Playwright для аккаунта №{i}...",
        "hashtag_set":   "✅ Хэштег установлен: <b>#{v}</b>",
        "template_set":  "✅ Шаблон комментария установлен",
        "spin_header":   "🔀 <b>Спинтекст — 5 вариантов:</b>",
        "rep_header":    "📋 <b>Отчёт Playwright:</b> {ok}/{total} успешно\n",
        "rep_ok":        "✅ <code>{acc}</code>  {ts}",
        "rep_fail":      "❌ <code>{acc}</code>  {ts}\n   ↳ {err}",
    },
}


def _PWT(uid: int, key: str) -> str:
    try:
        import rukla as _r
        lang = _r.get_user_data(uid).get("lang", "uk")
    except Exception:
        lang = "uk"
    return _PW_LX.get(lang, _PW_LX["uk"]).get(key, _PW_LX["uk"].get(key, key))


# ══════════════════════════════════════════════════════════════════════════════
#  ACCOUNT BRIDGE  (rukla5 → AccountConfig)
# ══════════════════════════════════════════════════════════════════════════════

def _cookie_str_to_playwright(cookie_str: str) -> list[dict]:
    """Convert TikTok cookie string (k=v; k2=v2) to Playwright JSON format."""
    http_only = {"sessionid", "sid_guard", "uid_tt", "sid_tt", "sessionid_ss"}
    result: list[dict] = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        result.append({
            "name":     name,
            "value":    value.strip(),
            "domain":   ".tiktok.com",
            "path":     "/",
            "httpOnly": name in http_only,
            "secure":   True,
            "sameSite": "None",
        })
    return result


def _build_accounts_for_uid(uid: int) -> list[AccountConfig]:
    """
    Build AccountConfig list from rukla5 accounts for this Telegram user.
    Converts cookie strings to Playwright JSON files and adapts proxy format.
    Only active accounts are included.
    """
    try:
        import rukla5 as _r5
        _r5._load_accounts()
        raw_accounts = _r5._get_user_accounts(uid)
    except Exception as exc:
        logger.warning("_build_accounts_for_uid: rukla5 error: %s", exc)
        return []

    cookies_dir = Path(f"playwright_cookies/{uid}")
    cookies_dir.mkdir(parents=True, exist_ok=True)
    result: list[AccountConfig] = []

    for idx, acc in enumerate(raw_accounts):
        if not acc.get("active", False):
            continue

        cookie_str = acc.get("cookie", "")
        proxy_str  = acc.get("proxy", "")   # socks5://[user:pass@]host:port from rukla5

        # Persist cookies in Playwright format
        cookies_file = str(cookies_dir / f"acc{idx}.json")
        if cookie_str:
            pl_cookies = _cookie_str_to_playwright(cookie_str)
            Path(cookies_file).write_text(
                json.dumps(pl_cookies, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        result.append(AccountConfig(
            account_id   = f"acc{idx + 1}",
            username     = acc.get("unique_id", f"acc{idx + 1}"),
            password     = "",            # not needed — cookies are present
            proxy        = proxy_str,     # _parse_proxy handles socks5://
            cookies_file = cookies_file,
        ))

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  ASYNC JOB RUNNERS
# ══════════════════════════════════════════════════════════════════════════════

async def _run_all_async(
    accounts: list[AccountConfig],
    hashtag: str,
    template: str,
) -> list[dict]:
    results: list[dict] = []
    async with async_playwright() as pw:
        for i, account in enumerate(accounts):
            if i > 0:
                jitter = random.uniform(5.0, 15.0)
                logger.info("waiting %.1f s before next account", jitter)
                await asyncio.sleep(jitter)
            session = TikTokSession(account, pw)
            await session.launch()
            result = await session.full_cycle(hashtag, template)
            await session.close()
            results.append(result)
    return results


async def _run_single_async(
    account: AccountConfig,
    hashtag: str,
    template: str,
) -> dict:
    async with async_playwright() as pw:
        session = TikTokSession(account, pw)
        await session.launch()
        result  = await session.full_cycle(hashtag, template)
        await session.close()
    return result


def _build_report(results: list[dict], uid: int) -> str:
    ok    = sum(1 for r in results if r["success"])
    lines = [_PWT(uid, "rep_header").format(ok=ok, total=len(results))]
    for r in results:
        if r["success"]:
            lines.append(_PWT(uid, "rep_ok").format(acc=r["account_id"], ts=r["timestamp"]))
        else:
            lines.append(_PWT(uid, "rep_fail").format(
                acc=r["account_id"], ts=r["timestamp"], err=r.get("error", "?")
            ))
    return "\n".join(lines)


def _thread_run_all(
    bot,
    uid: int,
    accounts: list[AccountConfig],
    hashtag: str,
    template: str,
) -> None:
    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(_run_all_async(accounts, hashtag, template))
            bot.send_message(uid, _build_report(results, uid), parse_mode="HTML")
        except Exception as exc:
            logger.exception("_thread_run_all error")
            bot.send_message(uid, f"❌ Playwright error: {exc}")
        finally:
            _pw_running.discard(uid)
            loop.close()

    _pw_running.add(uid)
    threading.Thread(target=target, daemon=True).start()


def _thread_run_single(
    bot,
    uid: int,
    account: AccountConfig,
    acc_num: int,
    hashtag: str,
    template: str,
) -> None:
    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_run_single_async(account, hashtag, template))
            bot.send_message(uid, _build_report([result], uid), parse_mode="HTML")
        except Exception as exc:
            logger.exception("_thread_run_single error")
            bot.send_message(uid, f"❌ Playwright error (acc{acc_num}): {exc}")
        finally:
            _pw_running.discard(uid)
            loop.close()

    _pw_running.add(uid)
    threading.Thread(target=target, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
#  MENU BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _build_pw_text(uid: int) -> str:
    s        = _get_pw_settings(uid)
    accounts = _build_accounts_for_uid(uid)
    none_str = _PWT(uid, "none")

    hashtag  = f"#{s['hashtag']}" if s.get("hashtag") else none_str
    template = s.get("comment_template") or none_str
    if len(template) > 45 and template != none_str:
        template = template[:45] + "…"

    status = _PWT(uid, "status_run") if uid in _pw_running else _PWT(uid, "status_idle")

    return "\n".join([
        _PWT(uid, "header"),
        "",
        _PWT(uid, "row_hashtag").format(v=hashtag),
        _PWT(uid, "row_template").format(v=template),
        _PWT(uid, "row_accounts").format(v=len(accounts)),
        status,
    ])


def _build_pw_markup(uid: int) -> types.InlineKeyboardMarkup:
    markup   = types.InlineKeyboardMarkup(row_width=1)
    accounts = _build_accounts_for_uid(uid)

    # Run-all button
    markup.add(
        types.InlineKeyboardButton(_PWT(uid, "btn_run_all"), callback_data="tiktok_pw_run_all")
    )

    # Per-account run buttons
    for i, acc in enumerate(accounts):
        label = _PWT(uid, "btn_run_one").format(i=i + 1, nick=acc.username)
        markup.add(
            types.InlineKeyboardButton(label, callback_data=f"tiktok_pw_acc_{i}")
        )

    # Settings buttons (2 per row)
    markup.row(
        types.InlineKeyboardButton(_PWT(uid, "btn_hashtag"),   callback_data="tiktok_pw_set_hashtag"),
        types.InlineKeyboardButton(_PWT(uid, "btn_template"),  callback_data="tiktok_pw_set_template"),
    )
    markup.add(
        types.InlineKeyboardButton(_PWT(uid, "btn_test_spin"), callback_data="tiktok_pw_test_spin")
    )
    # Back → rukla5 params menu
    markup.add(
        types.InlineKeyboardButton(_PWT(uid, "btn_back"), callback_data="tiktok_params_back")
    )
    return markup


def open_pw_menu(bot, uid: int, message_id: int) -> None:
    _load_pw_settings()
    text   = _build_pw_text(uid)
    markup = _build_pw_markup(uid)
    try:
        bot.edit_message_text(text, uid, message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════════════════
#  PENDING INPUT HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _clear_pw_pending(uid: int) -> None:
    _pw_pending_input.pop(uid, None)
    # Clear rukla5 pending states so both handlers don't fire at once
    try:
        import rukla5 as _r5
        _r5._clear_pending(uid)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  register_callbacks  — called once from the main bot file
# ══════════════════════════════════════════════════════════════════════════════

def register_callbacks(bot) -> None:
    _load_pw_settings()

    # ── open Playwright panel ─────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == "tiktok_pw_panel")
    def pw_open(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        open_pw_menu(bot, uid, call.message.message_id)

    # ── run ALL accounts ──────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == "tiktok_pw_run_all")
    def pw_run_all(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)

        if uid in _pw_running:
            bot.send_message(uid, _PWT(uid, "already_run"))
            return

        _load_pw_settings()
        s = _get_pw_settings(uid)

        if not s.get("hashtag"):
            bot.send_message(uid, _PWT(uid, "no_hashtag"))
            return
        if not s.get("comment_template"):
            bot.send_message(uid, _PWT(uid, "no_template"))
            return

        accounts = _build_accounts_for_uid(uid)
        if not accounts:
            bot.send_message(uid, _PWT(uid, "no_accounts"), parse_mode="HTML")
            return

        bot.send_message(uid, _PWT(uid, "starting_all"))
        _thread_run_all(bot, uid, accounts, s["hashtag"], s["comment_template"])

    # ── run SINGLE account (tiktok_pw_acc_N) ─────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data.startswith("tiktok_pw_acc_"))
    def pw_run_single(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)

        if uid in _pw_running:
            bot.send_message(uid, _PWT(uid, "already_run"))
            return

        try:
            idx = int(call.data.split("_")[-1])
        except (ValueError, IndexError):
            return

        _load_pw_settings()
        s = _get_pw_settings(uid)

        if not s.get("hashtag"):
            bot.send_message(uid, _PWT(uid, "no_hashtag"))
            return
        if not s.get("comment_template"):
            bot.send_message(uid, _PWT(uid, "no_template"))
            return

        accounts = _build_accounts_for_uid(uid)
        if idx >= len(accounts):
            bot.send_message(uid, "❌ Account not found")
            return

        bot.send_message(uid, _PWT(uid, "starting_one").format(i=idx + 1))
        _thread_run_single(bot, uid, accounts[idx], idx + 1, s["hashtag"], s["comment_template"])

    # ── set hashtag ───────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == "tiktok_pw_set_hashtag")
    def pw_ask_hashtag(call):
        uid = call.message.chat.id
        _clear_pw_pending(uid)
        _pw_pending_input[uid] = "hashtag"
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            _PWT(uid, "btn_cancel"), callback_data="tiktok_pw_cancel"
        ))
        bot.send_message(uid, _PWT(uid, "ask_hashtag"), reply_markup=markup)

    # ── set comment template ──────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == "tiktok_pw_set_template")
    def pw_ask_template(call):
        uid = call.message.chat.id
        _clear_pw_pending(uid)
        _pw_pending_input[uid] = "comment"
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            _PWT(uid, "btn_cancel"), callback_data="tiktok_pw_cancel"
        ))
        bot.send_message(uid, _PWT(uid, "ask_template"), reply_markup=markup, parse_mode="HTML")

    # ── test spintax ──────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == "tiktok_pw_test_spin")
    def pw_ask_spin(call):
        uid = call.message.chat.id
        _clear_pw_pending(uid)
        _pw_pending_input[uid] = "spin_test"
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            _PWT(uid, "btn_cancel"), callback_data="tiktok_pw_cancel"
        ))
        bot.send_message(uid, _PWT(uid, "ask_spin"), reply_markup=markup)

    # ── cancel pending input ──────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == "tiktok_pw_cancel")
    def pw_cancel(call):
        uid = call.message.chat.id
        _clear_pw_pending(uid)
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(uid, call.message.message_id)
        except Exception:
            pass

    # ── message handler for all pending playwright inputs ─────────────────────

    @bot.message_handler(
        func=lambda msg: msg.chat.id in _pw_pending_input,
        content_types=["text"],
    )
    def pw_receive_text(message):
        uid  = message.chat.id
        mode = _pw_pending_input.pop(uid, None)
        raw  = message.text.strip()

        if mode == "hashtag":
            hashtag = raw.lstrip("#").strip()
            _load_pw_settings()
            _get_pw_settings(uid)["hashtag"] = hashtag
            _save_pw_settings()
            bot.send_message(
                uid,
                _PWT(uid, "hashtag_set").format(v=hashtag),
                parse_mode="HTML",
            )
            text   = _build_pw_text(uid)
            markup = _build_pw_markup(uid)
            bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML")

        elif mode == "comment":
            _load_pw_settings()
            _get_pw_settings(uid)["comment_template"] = raw
            _save_pw_settings()
            bot.send_message(uid, _PWT(uid, "template_set"))
            text   = _build_pw_text(uid)
            markup = _build_pw_markup(uid)
            bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML")

        elif mode == "spin_test":
            engine   = SpintaxEngine()
            variants = [engine.spin(raw) for _ in range(5)]
            lines    = [_PWT(uid, "spin_header")] + [f"• {v}" for v in variants]
            bot.send_message(uid, "\n".join(lines), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════════════════
#  STANDALONE MODE  (config.json + --run-once)
# ══════════════════════════════════════════════════════════════════════════════

def load_config(path: str = "config.json") -> BotConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    accounts: list[AccountConfig] = []
    for a in raw["accounts"]:
        accounts.append(AccountConfig(
            account_id      = a["account_id"],
            username        = a["username"],
            password        = a["password"],
            proxy           = a["proxy"],
            cookies_file    = a.get("cookies_file", f"cookies/{a['account_id']}.json"),
            user_agent      = a.get("user_agent", ""),
            viewport_width  = a.get("viewport_width", 0),
            viewport_height = a.get("viewport_height", 0),
        ))

    tg = raw.get("telegram", {})
    return BotConfig(
        accounts           = accounts,
        telegram_api_id    = tg.get("api_id", 0),
        telegram_api_hash  = tg.get("api_hash", ""),
        telegram_bot_token = tg.get("bot_token", ""),
        telegram_chat_id   = tg.get("chat_id", 0),
        headless           = raw.get("headless", True),
        slow_mo            = raw.get("slow_mo", 50),
    )


async def _cli_run_once(config: BotConfig, hashtag: str, template: str) -> None:
    results = await _run_all_async(config.accounts, hashtag, template)
    for r in results:
        status = "OK" if r["success"] else f"FAIL ({r['error']})"
        print(f"  [{r['account_id']}]  {status}  @ {r['timestamp']}")


async def _main() -> None:
    args = sys.argv[1:]
    if "--run-once" in args:
        try:
            idx      = args.index("--run-once")
            hashtag  = args[idx + 1]
            template = args[idx + 2]
        except IndexError:
            print("Usage: python ruklaTikTok.py --run-once #hashtag 'comment {A|B}'")
            return
        config = load_config()
        await _cli_run_once(config, hashtag, template)
    else:
        print("This module is imported by the main bot. Use --run-once for CLI mode.")
        print("Example: python ruklaTikTok.py --run-once #dance '{Круто|Топ} танець!'")


if __name__ == "__main__":
    asyncio.run(_main())
