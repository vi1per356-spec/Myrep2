"""
ruklaTikTok.py — TikTok Playwright bot + Telegram (Telethon) manager.

Modules:
  1. Anti-detect & isolation  — playwright-stealth, per-account BrowserContext,
                                individual residential proxies, UA/viewport randomisation
  2. Auth system              — cookies JSON load/save + credential fallback
  3. FYP warm-up              — watches 3-7 videos, 10-50 s each, 15 % like chance
  4. Target action            — hashtag search → human-watch → spintax comment

Usage:
  python ruklaTikTok.py               # start Telegram bot listener
  python ruklaTikTok.py --run-once    # fire all accounts once (CLI mode)

Config: config.json  (see config.example.json)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import sys
from dataclasses import dataclass, field
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
from telethon import TelegramClient, events

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
    account_id:     str
    username:       str
    password:       str
    # format  IP:PORT:USER:PASS  or  IP:PORT
    proxy:          str
    cookies_file:   str
    # leave empty → auto-assigned at runtime
    user_agent:     str = ""
    viewport_width:  int = 0
    viewport_height: int = 0


@dataclass
class BotConfig:
    accounts:           list[AccountConfig]
    telegram_api_id:    int
    telegram_api_hash:  str
    telegram_bot_token: str
    telegram_chat_id:   int  = 0
    headless:           bool = True
    slow_mo:            int  = 50


# ══════════════════════════════════════════════════════════════════════════════
#  STATIC POOLS
# ══════════════════════════════════════════════════════════════════════════════

_MOBILE_USER_AGENTS: list[str] = [
    # iOS / Safari
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6.1 Mobile/15E148 Safari/604.1",
    # Android / Chrome
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
    (390, 844),   # iPhone 14
    (393, 852),   # iPhone 15
    (375, 812),   # iPhone X / XS
    (414, 896),   # iPhone 11 Pro Max
    (428, 926),   # iPhone 14 Plus
    (412, 915),   # Pixel 7
    (411, 890),   # Pixel 6 Pro
    (360, 780),   # Samsung Galaxy S21
    (384, 854),   # Samsung Galaxy A54
]

# Rough lat/lon for Ukrainian cities (used as geolocation)
_UA_GEO_BASES: list[tuple[float, float]] = [
    (50.4501, 30.5234),   # Kyiv
    (49.8397, 24.0297),   # Lviv
    (49.9935, 36.2304),   # Kharkiv
    (48.4647, 35.0462),   # Dnipro
    (47.8388, 35.1396),   # Zaporizhzhia
    (46.9775, 31.9946),   # Mykolaiv
]


# ══════════════════════════════════════════════════════════════════════════════
#  SPINTAX ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class SpintaxEngine:
    """Recursively resolves nested {option1|option2|…} patterns."""

    _PATTERN = re.compile(r"\{([^{}]+)\}")

    def spin(self, text: str) -> str:
        while True:
            match = self._PATTERN.search(text)
            if not match:
                break
            options = match.group(1).split("|")
            text = text[: match.start()] + random.choice(options) + text[match.end():]
        return text


# ══════════════════════════════════════════════════════════════════════════════
#  TIKTOK SESSION
# ══════════════════════════════════════════════════════════════════════════════

class TikTokSession:
    """
    One fully-isolated TikTok session per account.
    Each instance owns its own Browser + BrowserContext so fingerprints,
    cookies and proxy settings never bleed between accounts.
    """

    def __init__(self, account: AccountConfig, pw: Playwright) -> None:
        self.account = account
        self._pw     = pw
        self.browser:  Optional[Browser]        = None
        self.context:  Optional[BrowserContext] = None
        self.page:     Optional[Page]           = None
        self._spintax  = SpintaxEngine()
        self._assign_random_identity()

    # ── identity ──────────────────────────────────────────────────────────────

    def _assign_random_identity(self) -> None:
        if not self.account.user_agent:
            self.account.user_agent = random.choice(_MOBILE_USER_AGENTS)
        if not self.account.viewport_width:
            w, h = random.choice(_VIEWPORT_PRESETS)
            self.account.viewport_width  = w
            self.account.viewport_height = h

    def _parse_proxy(self) -> dict:
        parts = self.account.proxy.split(":")
        if len(parts) == 4:
            ip, port, user, password = parts
            return {"server": f"http://{ip}:{port}", "username": user, "password": password}
        if len(parts) == 2:
            ip, port = parts
            return {"server": f"http://{ip}:{port}"}
        raise ValueError(f"[{self.account.account_id}] Bad proxy format: {self.account.proxy!r}")

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

        self.context = await self.browser.new_context(
            proxy               = proxy,
            user_agent          = self.account.user_agent,
            viewport            = {
                "width":  self.account.viewport_width,
                "height": self.account.viewport_height,
            },
            locale              = "uk-UA",
            timezone_id         = "Europe/Kyiv",
            permissions         = ["geolocation"],
            geolocation         = self._random_geolocation(),
            color_scheme        = "light",
            device_scale_factor = random.choice([2.0, 3.0]),
            is_mobile           = True,
            has_touch           = True,
            extra_http_headers  = {
                "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        self.page = await self.context.new_page()
        await stealth_async(self.page)

        logger.info(
            "[%s] browser launched  UA=%.40s  viewport=%dx%d  proxy=%s",
            self.account.account_id,
            self.account.user_agent,
            self.account.viewport_width,
            self.account.viewport_height,
            self.account.proxy.split(":")[0],
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
            logger.warning("[%s] failed to load cookies: %s", self.account.account_id, exc)
            return False

    async def save_cookies(self) -> None:
        cookies = await self.context.cookies()
        path = Path(self.account.cookies_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("[%s] cookies saved (%d entries) → %s", self.account.account_id, len(cookies), path)

    # ── auth ──────────────────────────────────────────────────────────────────

    async def verify_login(self) -> bool:
        """
        Navigate to TikTok home and check whether the account is logged in.
        Returns True only when an authenticated element is visible.
        """
        try:
            await self.page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=35_000)
        except Exception as exc:
            logger.warning("[%s] verify_login navigation error: %s", self.account.account_id, exc)
            return False

        await self._delay(2_500, 4_500)

        # logged-in indicators
        for sel in [
            '[data-e2e="profile-icon"]',
            '[data-e2e="nav-upload"]',
            'a[href*="/upload"]',
        ]:
            try:
                await self.page.wait_for_selector(sel, timeout=6_000)
                logger.info("[%s] session valid (found %s)", self.account.account_id, sel)
                return True
            except Exception:
                pass

        # logged-out indicators
        for sel in [
            '[data-e2e="nav-login-button"]',
            'a[href*="/login"]',
        ]:
            try:
                await self.page.wait_for_selector(sel, timeout=3_000)
                logger.info("[%s] not logged in (found %s)", self.account.account_id, sel)
                return False
            except Exception:
                pass

        return "login" not in self.page.url

    async def login_with_credentials(self) -> bool:
        logger.info("[%s] falling back to credential login", self.account.account_id)
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
                logger.warning("[%s] CAPTCHA detected — manual intervention required", self.account.account_id)
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
        for sel in [
            '[class*="captcha"]',
            '[id*="captcha"]',
            'iframe[src*="captcha"]',
            '[data-e2e="captcha"]',
        ]:
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
        logger.info("[%s] starting FYP warm-up", self.account.account_id)
        try:
            await self.page.goto("https://www.tiktok.com/foryou", wait_until="domcontentloaded", timeout=35_000)
        except Exception as exc:
            logger.warning("[%s] FYP navigation error: %s", self.account.account_id, exc)
            return

        await self._delay(2_000, 4_000)

        count = random.randint(3, 7)
        logger.info("[%s] will watch %d FYP videos", self.account.account_id, count)

        for i in range(count):
            watch_secs = random.uniform(10.0, 50.0)
            logger.info(
                "[%s] FYP video %d/%d — watching %.1f s",
                self.account.account_id, i + 1, count, watch_secs,
            )

            # Simulate watching: random mouse wiggles while time passes
            elapsed  = 0.0
            interval = random.uniform(4.0, 10.0)
            while elapsed < watch_secs:
                chunk = min(interval, watch_secs - elapsed)
                await asyncio.sleep(chunk)
                elapsed += chunk
                if random.random() < 0.35:
                    await self._random_mouse_move()

            # 15 % chance to like
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
        # Arrow-down is the most reliable way to advance the TikTok feed
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
            logger.warning("[%s] no videos found for #%s", self.account.account_id, hashtag)
            return False

        # Avoid the very first (most-viewed) video to look less bot-like
        pool = links[2:] if len(links) > 2 else links
        target_url = random.choice(pool)
        logger.info("[%s] target video: %s", self.account.account_id, target_url)

        try:
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=35_000)
        except Exception as exc:
            logger.error("[%s] target video navigation error: %s", self.account.account_id, exc)
            return False

        await self._delay(1_500, 3_000)

        # Watch the video for a natural amount of time before commenting
        watch_secs = random.uniform(5.0, 15.0)
        logger.info("[%s] watching target video %.1f s before commenting", self.account.account_id, watch_secs)
        await asyncio.sleep(watch_secs)
        await self._random_mouse_move()

        comment = self._spintax.spin(comment_template)
        logger.info("[%s] composed comment: %r", self.account.account_id, comment)
        return await self._post_comment(comment)

    async def _collect_hashtag_video_links(self) -> list[str]:
        links: list[str] = []
        selectors = [
            '[data-e2e="challenge-item"] a',
            '[class*="VideoCard"] a',
            '[class*="VideoItem"] a',
            'a[href*="/video/"]',
        ]
        for sel in selectors:
            try:
                elements = await self.page.query_selector_all(sel)
                for el in elements:
                    href = await el.get_attribute("href")
                    if href and "/video/" in href:
                        full = href if href.startswith("http") else f"https://www.tiktok.com{href}"
                        if full not in links:
                            links.append(full)
            except Exception:
                pass
        logger.info("[%s] collected %d video links", self.account.account_id, len(links))
        return links

    async def _post_comment(self, comment: str) -> bool:
        # 1. Open comment section if collapsed
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

        # 2. Find comment text input
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

        # 3. Type with human-like keystroke delays
        await self._human_type_keyboard(comment)
        await self._delay(700, 1_500)

        # 4. Submit
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
                logger.info("[%s] comment posted successfully", self.account.account_id)
                return True
            except Exception:
                pass

        # Fallback: Enter key
        await self.page.keyboard.press("Enter")
        await self._delay(2_500, 5_000)
        logger.info("[%s] comment submitted via Enter", self.account.account_id)
        return True

    # ── human simulation helpers ──────────────────────────────────────────────

    async def _delay(self, min_ms: int = 500, max_ms: int = 2_000) -> None:
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1_000)

    async def _human_type_element(self, element, text: str) -> None:
        """Type into a Playwright element handle with per-key random delay."""
        for ch in text:
            await element.type(ch, delay=random.uniform(70, 210))
            if random.random() < 0.05:           # occasional 'thinking' pause
                await self._delay(250, 700)

    async def _human_type_keyboard(self, text: str) -> None:
        """Type via page keyboard (works for contenteditable divs)."""
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
#  BOT MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class TikTokBotManager:
    """
    Manages a pool of TikTok sessions.
    Use as an async context manager:
        async with TikTokBotManager(config) as mgr:
            results = await mgr.run_all_accounts(hashtag, template)
    """

    def __init__(self, config: BotConfig) -> None:
        self.config     = config
        self._pw:       Optional[Playwright]          = None
        self._sessions: dict[str, TikTokSession]      = {}

    async def __aenter__(self) -> "TikTokBotManager":
        self._pw = await async_playwright().start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close_all()
        if self._pw:
            await self._pw.stop()

    async def _make_session(self, account: AccountConfig) -> TikTokSession:
        session = TikTokSession(account, self._pw)
        await session.launch()
        self._sessions[account.account_id] = session
        return session

    async def run_all_accounts(self, hashtag: str, comment_template: str) -> list[dict]:
        """
        Runs the full cycle for every account sequentially with a random
        jitter between starts (5–20 s) to avoid coordinated traffic spikes.
        """
        results: list[dict] = []
        for idx, account in enumerate(self.config.accounts):
            if idx > 0:
                jitter = random.uniform(5.0, 20.0)
                logger.info("waiting %.1f s before next account…", jitter)
                await asyncio.sleep(jitter)

            session = await self._make_session(account)
            result  = await session.full_cycle(hashtag, comment_template)
            results.append(result)

        return results

    async def run_single_account(self, account_id: str, hashtag: str, comment_template: str) -> dict:
        account = next((a for a in self.config.accounts if a.account_id == account_id), None)
        if not account:
            return {"account_id": account_id, "success": False, "error": "account not found"}
        session = await self._make_session(account)
        return await session.full_cycle(hashtag, comment_template)

    async def close_all(self) -> None:
        for session in self._sessions.values():
            await session.close()
        self._sessions.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  TELEGRAM BOT INTERFACE  (Telethon)
# ══════════════════════════════════════════════════════════════════════════════

class TelegramBotInterface:
    """
    Telegram bot that acts as the command-and-control layer for TikTokBotManager.

    Commands
    ────────
    /start                         — help message
    /comment #tag {Text|Text}      — run all accounts
    /comment_one accN #tag text    — run a single account
    /status                        — show cookie status per account
    /spin {A|B} text               — preview spintax (5 variants)
    """

    def __init__(self, config: BotConfig) -> None:
        self.config   = config
        self._spintax = SpintaxEngine()
        self._client  = TelegramClient(
            "tiktok_mgr_session",
            config.telegram_api_id,
            config.telegram_api_hash,
        )

    # ── command handlers ──────────────────────────────────────────────────────

    def _register_handlers(self) -> None:

        @self._client.on(events.NewMessage(pattern=r"/start"))
        async def cmd_start(ev):
            await ev.respond(
                "**TikTok Bot Manager**\n\n"
                "`/comment #хештег {варіант1|варіант2} текст`\n"
                "  → коментує від усіх акаунтів\n\n"
                "`/comment_one accID #хештег текст`\n"
                "  → один акаунт\n\n"
                "`/status`  — перевірити cookies\n"
                "`/spin {A|B} текст`  — тест спінтексту",
                parse_mode="md",
            )

        @self._client.on(events.NewMessage(pattern=r"/comment (.+)"))
        async def cmd_comment(ev):
            raw   = ev.pattern_match.group(1).strip()
            parts = raw.split(" ", 1)
            if len(parts) < 2:
                await ev.respond("❌ Формат: `/comment #хештег текст коментаря`", parse_mode="md")
                return

            hashtag, template = parts[0], parts[1]
            await ev.respond(f"▶️ Запускаю для всіх акаунтів → `{hashtag}`…", parse_mode="md")

            async with TikTokBotManager(self.config) as mgr:
                results = await mgr.run_all_accounts(hashtag, template)

            await ev.respond(self._build_report(results), parse_mode="md")

        @self._client.on(events.NewMessage(pattern=r"/comment_one (\S+) (\S+) (.+)"))
        async def cmd_comment_one(ev):
            acc_id   = ev.pattern_match.group(1)
            hashtag  = ev.pattern_match.group(2)
            template = ev.pattern_match.group(3)
            await ev.respond(f"▶️ Запускаю акаунт `{acc_id}` → `{hashtag}`…", parse_mode="md")

            async with TikTokBotManager(self.config) as mgr:
                result = await mgr.run_single_account(acc_id, hashtag, template)

            await ev.respond(self._build_report([result]), parse_mode="md")

        @self._client.on(events.NewMessage(pattern=r"/status"))
        async def cmd_status(ev):
            lines = ["📊 **Статус акаунтів:**\n"]
            for acc in self.config.accounts:
                exists = Path(acc.cookies_file).exists()
                icon   = "✅" if exists else "❌"
                lines.append(f"{icon}  `{acc.account_id}` ({acc.username})  cookies: {'є' if exists else 'немає'}")
            await ev.respond("\n".join(lines), parse_mode="md")

        @self._client.on(events.NewMessage(pattern=r"/spin (.+)"))
        async def cmd_spin(ev):
            template = ev.pattern_match.group(1)
            variants = [self._spintax.spin(template) for _ in range(5)]
            text = "🔀 **Спінтекст (5 варіантів):**\n\n" + "\n".join(f"• {v}" for v in variants)
            await ev.respond(text, parse_mode="md")

    @staticmethod
    def _build_report(results: list[dict]) -> str:
        ok    = sum(1 for r in results if r["success"])
        lines = [f"📋 **Звіт:** {ok}/{len(results)} успішно\n"]
        for r in results:
            icon = "✅" if r["success"] else "❌"
            lines.append(f"{icon} `{r['account_id']}`  {r['timestamp']}")
            if r.get("error"):
                lines.append(f"   ↳ {r['error']}")
        return "\n".join(lines)

    async def run(self) -> None:
        self._register_handlers()
        await self._client.start(bot_token=self.config.telegram_bot_token)
        logger.info("Telegram bot started — waiting for commands…")
        await self._client.run_until_disconnected()


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG LOADER
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

    tg = raw["telegram"]
    return BotConfig(
        accounts           = accounts,
        telegram_api_id    = tg["api_id"],
        telegram_api_hash  = tg["api_hash"],
        telegram_bot_token = tg["bot_token"],
        telegram_chat_id   = tg.get("chat_id", 0),
        headless           = raw.get("headless", True),
        slow_mo            = raw.get("slow_mo", 50),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINTS
# ══════════════════════════════════════════════════════════════════════════════

async def _cli_run_once(config: BotConfig, hashtag: str, template: str) -> None:
    """One-shot run from CLI: all accounts → hashtag → comment."""
    async with TikTokBotManager(config) as mgr:
        results = await mgr.run_all_accounts(hashtag, template)

    for r in results:
        status = "OK" if r["success"] else f"FAIL ({r['error']})"
        print(f"  [{r['account_id']}]  {status}  @ {r['timestamp']}")


async def _main() -> None:
    args = sys.argv[1:]

    if "--run-once" in args:
        # Usage: python ruklaTikTok.py --run-once #хештег "{спінтекст}"
        try:
            hashtag  = args[args.index("--run-once") + 1]
            template = args[args.index("--run-once") + 2]
        except IndexError:
            print("Usage: python ruklaTikTok.py --run-once #hashtag 'comment {template}'")
            return
        config = load_config()
        await _cli_run_once(config, hashtag, template)
    else:
        config = load_config()
        await TelegramBotInterface(config).run()


if __name__ == "__main__":
    asyncio.run(_main())
