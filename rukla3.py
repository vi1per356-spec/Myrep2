import asyncio, re
import aiohttp
from urllib.parse import quote
from telethon import Button
from telethon.tl.types import Channel, Chat
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.contacts import SearchRequest

from rukla1 import get_ctx


def _T(uid: int, key: str) -> str:
    try:
        import rukla as _r
        return _r.T(uid, key)
    except Exception:
        return key

SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "uk,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TME_SKIP = {"share", "iv", "s", "joinchat", "addlist", "privacy", "faq", "blog", "apps", "store", "deloitte", "telegram"}


def _extract_usernames_from_html(html: str) -> list:
    raw = re.findall(r'(?:https?://)?t\.me/([a-zA-Z][a-zA-Z0-9_]{3,})', html)
    result = []
    for u in raw:
        if u.lower() not in _TME_SKIP and not u.startswith("+"):
            result.append(u)
    return list(set(result))


async def has_discussion_chat(client, username: str) -> bool:
    try:
        entity = await client.get_entity(username)
        full = await client(GetFullChannelRequest(entity))
        return bool(full.full_chat.linked_chat_id)
    except Exception:
        return False


# ================= ПОШУК НА TGSTAT =================
async def _tgstat_usernames(session, keyword: str) -> list:
    usernames = []
    url = f"https://tgstat.com/channels/search?q={quote(keyword)}&language=uk"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with session.get(url, headers=SEARCH_HEADERS, timeout=timeout) as resp:
            if resp.status != 200:
                return usernames
            html = await resp.text()
        found = re.findall(r'href="https://tgstat\.(?:com|ru)/channel/(@[a-zA-Z][a-zA-Z0-9_]{3,})"', html)
        usernames = list({u.lstrip("@") for u in found})
    except Exception as e:
        print(f"[tgstat] Помилка '{keyword}': {e}")
    return usernames


async def _teleads_usernames(session, keyword: str) -> list:
    url = f"https://teleads.com.ua/catalog/channels?search={quote(keyword)}"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with session.get(url, headers=SEARCH_HEADERS, timeout=timeout) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()
        return _extract_usernames_from_html(html)
    except Exception as e:
        print(f"[teleads] Помилка '{keyword}': {e}")
        return []


async def _tg_api_usernames(client, keyword: str) -> list:
    usernames = []
    try:
        res = await client(SearchRequest(q=keyword, limit=50))
        for chat in res.chats:
            if isinstance(chat, Channel) and chat.broadcast:
                u = getattr(chat, "username", None)
                if u:
                    usernames.append(u)
    except Exception as e:
        print(f"[TG API] Помилка '{keyword}': {e}")
    return usernames


# ================= ГОЛОВНА ФУНКЦІЯ ПОШУКУ КАНАЛІВ =================
async def run_channel_search(chat_id, keywords):
    ctx = get_ctx(chat_id)
    tg_client = ctx.userbots[0]["client"] if ctx.userbots else None
    if not tg_client:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_no_accs'), [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"back_to_accounts")]])
        return

    seen: set = set()
    candidates: list = []
    final_links: list = []

    await ctx.send_and_track(chat_id, _T(chat_id, 'r3_ch_collecting'))
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        for keyword in keywords:
            for u in await _tgstat_usernames(session, keyword):
                if u.lower() not in seen:
                    seen.add(u.lower())
                    candidates.append(u)
            for u in await _teleads_usernames(session, keyword):
                if u.lower() not in seen:
                    seen.add(u.lower())
                    candidates.append(u)
            for u in await _tg_api_usernames(tg_client, keyword):
                if u.lower() not in seen:
                    seen.add(u.lower())
                    candidates.append(u)
            await asyncio.sleep(1.5)

    total_candidates = len(candidates)
    if total_candidates == 0:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r3_ch_not_found'), [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"back_to_accounts")]])
        return

    await ctx.send_and_track(chat_id, _T(chat_id, 'r3_ch_checking').format(total=total_candidates))
    for i, username in enumerate(candidates, 1):
        if i % 10 == 0:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r3_ch_progress').format(checked=i, total=total_candidates, found=len(final_links)))
        if await has_discussion_chat(tg_client, username):
            final_links.append(f"https://t.me/{username}")
        await asyncio.sleep(0.5)

    if not final_links:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r3_ch_no_chat').format(total=total_candidates), [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"back_to_accounts")]])
        return

    chunk_size = 50
    total = len(final_links)
    for i in range(0, total, chunk_size):
        chunk = final_links[i:i + chunk_size]
        header = _T(chat_id, 'r3_search_ch_header').format(total=total) if i == 0 else _T(chat_id, 'r3_search_cont')
        is_last = (i + chunk_size) >= total
        btns = [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"back_to_accounts")]] if is_last else None
        await ctx.send_and_track(chat_id, header + "\n".join(chunk), btns)
        await asyncio.sleep(0.3)


# ================= ПОШУК ГРУП/ЧАТІВ =================
async def _tg_api_group_usernames(client, keyword: str) -> list:
    usernames = []
    try:
        res = await client(SearchRequest(q=keyword, limit=50))
        for chat in res.chats:
            if isinstance(chat, Channel) and chat.megagroup:
                u = getattr(chat, "username", None)
                if u:
                    usernames.append(u)
    except Exception as e:
        print(f"[TG API Groups] Помилка '{keyword}': {e}")
    return usernames


async def _tgstat_group_usernames(session, keyword: str) -> list:
    usernames = []
    urls = [f"https://uk.tgstat.com/chats/search?q={quote(keyword)}",
            f"https://tgstat.com/chats/search?q={quote(keyword)}&language=uk"]
    for url in urls:
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with session.get(url, headers=SEARCH_HEADERS, timeout=timeout) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text()
            found = re.findall(r'href="(?:https://(?:uk\.)?tgstat\.(?:com|ru))?/(?:uk/)?chat/(@[a-zA-Z][a-zA-Z0-9_]{3,})"', html)
            usernames = list({u.lstrip("@") for u in found})
            if usernames:
                break
        except Exception as e:
            print(f"[tgstat groups] {url}: {e}")
    return usernames


async def _teleads_group_usernames(session, keyword: str) -> list:
    urls = [f"https://teleads.com.ua/catalog/chats?search={quote(keyword)}",
            f"https://teleads.com.ua/catalog/channels?search={quote(keyword)}"]
    result = []
    for url in urls:
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with session.get(url, headers=SEARCH_HEADERS, timeout=timeout) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text()
            result.extend(_extract_usernames_from_html(html))
        except Exception as e:
            print(f"[teleads groups] {url}: {e}")
    return list(set(result))


async def run_chat_search(chat_id, keywords):
    ctx = get_ctx(chat_id)
    tg_client = ctx.group_userbots[0]["client"] if ctx.group_userbots else None
    if not tg_client:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r3_grp_no_acc'), [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]])
        return

    seen: set = set()
    candidates: list = []
    final_links: list = []

    await ctx.send_and_track(chat_id, _T(chat_id, 'r3_grp_collecting'))
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        for keyword in keywords:
            for u in await _tgstat_group_usernames(session, keyword):
                if u.lower() not in seen:
                    seen.add(u.lower())
                    candidates.append(u)
            for u in await _teleads_group_usernames(session, keyword):
                if u.lower() not in seen:
                    seen.add(u.lower())
                    candidates.append(u)
            for u in await _tg_api_group_usernames(tg_client, keyword):
                if u.lower() not in seen:
                    seen.add(u.lower())
                    candidates.append(u)
            await asyncio.sleep(1.5)

    total_candidates = len(candidates)
    if total_candidates == 0:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r3_grp_not_found'), [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]])
        return

    await ctx.send_and_track(chat_id, _T(chat_id, 'r3_grp_checking').format(total=total_candidates))
    for i, username in enumerate(candidates, 1):
        if i % 10 == 0:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r3_grp_progress').format(checked=i, total=total_candidates, found=len(final_links)))
        try:
            entity = await tg_client.get_entity(username)
            is_group = (isinstance(entity, Channel) and entity.megagroup) or isinstance(entity, Chat)
            if is_group:
                final_links.append(f"https://t.me/{username}")
        except:
            pass
        await asyncio.sleep(0.5)

    if not final_links:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r3_grp_no_groups').format(total=total_candidates), [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]])
        return

    chunk_size = 50
    total = len(final_links)
    for i in range(0, total, chunk_size):
        chunk = final_links[i:i + chunk_size]
        header = _T(chat_id, 'r3_search_grp_header').format(total=total) if i == 0 else _T(chat_id, 'r3_search_cont')
        is_last = (i + chunk_size) >= total
        btns = [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]] if is_last else None
        await ctx.send_and_track(chat_id, header + "\n".join(chunk), btns)
        await asyncio.sleep(0.3)


# ================= ОБРОБНИКИ ДЛЯ rukla1 =================
async def handle_text_state(ctx, chat_id, state, text, event) -> bool:
    if state == "WAITING_SEARCH_KEYWORDS":
        keywords = [k.strip() for k in text.split(",") if k.strip()]
        ctx.user_states[chat_id] = None
        await ctx.send_and_track(chat_id, _T(chat_id, 'r3_searching_ch'))
        asyncio.create_task(run_channel_search(chat_id, keywords))
        return True
    if state == "G_WAITING_SEARCH_KEYWORDS":
        keywords = [k.strip() for k in text.split(",") if k.strip()]
        ctx.user_states[chat_id] = None
        await ctx.send_and_track(chat_id, _T(chat_id, 'r3_searching_grp'))
        asyncio.create_task(run_chat_search(chat_id, keywords))
        return True
    return False


async def handle_callback(ctx, chat_id, data, event) -> bool:
    if data == b"search_channels":
        ctx.user_states[chat_id] = "WAITING_SEARCH_KEYWORDS"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r3_kw_prompt_ch'))
        return True
    if data == b"g_search_chats":
        ctx.user_states[chat_id] = "G_WAITING_SEARCH_KEYWORDS"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r3_kw_prompt_grp'))
        return True
    return False
