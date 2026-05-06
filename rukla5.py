"""
rukla5.py — TikTok advertising module

Features:
  - Add accounts via Cookie (multi-line)
  - Single-column inline menus
  - Account deletion: single index / range "2-5" / "all"
  - Global SOCKS5 proxy list with same delete semantics; round-robin assignment
  - Hashtag monitoring with background worker
  - Main message + 1.5 min between posts; new videos prioritised over old
  - Reply styles (2-5 accounts respond per main comment, up to 15 styles)
  - Like-on-everything: parent comment, own comment/reply, and the video
  - Display-name distribution across accounts (1 nick → ~N/M accounts)
  - Avatar ZIP upload (PNG/JPG/JPEG/WEBP); ~50 % accounts get a random avatar
  - Neuro-feed: scroll FYP, like every 2nd, AI-comment every 4th (provider hook)
  - Bot state toggle (pause / resume)
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import shutil
import threading
import time
import zipfile
from typing import Optional

import requests
from telebot import types

# ─── File paths ───────────────────────────────────────────────────────────────
TIKTOK_ACCOUNTS_FILE  = 'tiktok_accounts.json'
TIKTOK_SETTINGS_FILE  = 'tiktok_settings.json'
TIKTOK_COMMENTED_FILE = 'tiktok_commented.json'
TIKTOK_AVATARS_ROOT   = 'tiktok_avatars'   # one sub-dir per uid

# ─── Bot reference ────────────────────────────────────────────────────────────
_bot_ref = None

# ─── In-memory state ──────────────────────────────────────────────────────────
_accounts:  dict = {}   # uid_str -> [acc, ...]
_settings:  dict = {}   # uid_str -> {settings dict}
_commented: dict = {}   # uid_str -> {hashtag -> [video_id, ...]}

# ─── Pending input ────────────────────────────────────────────────────────────
# uid -> action key (string).  All flows feed into one message handler.
_pending: dict = {}

ACT_COOKIE       = 'cookie'
ACT_PROXY_ADD    = 'proxy_add'
ACT_PROXY_DEL    = 'proxy_del'
ACT_ACC_DEL      = 'acc_del'
ACT_HASHTAGS     = 'hashtags'
ACT_NICKS        = 'nicks'
ACT_AVATARS      = 'avatars'        # waiting for ZIP document
ACT_MAIN_MSG     = 'main_msg'
ACT_REPLY_STYLES = 'reply_styles'

# ─── Background workers ──────────────────────────────────────────────────────
_bg_stop:      dict = {}   # uid -> threading.Event   (main comment worker)
_bg_thread:    dict = {}
_neuro_stop:   dict = {}   # uid -> threading.Event   (neuro-feed worker)
_neuro_thread: dict = {}

# ─── Constants ────────────────────────────────────────────────────────────────
COMMENT_DELAY_SECS = 90       # 1.5 minutes between main comments
ACCOUNT_LIMIT      = 25
REPLY_STYLE_LIMIT  = 15
DEFAULT_REPLY_MIN  = 2
DEFAULT_REPLY_MAX  = 5
NO_AVATAR_PCT      = 50

COUNTRIES = [
    "🇺🇦 Україна",        "🇵🇱 Польща",           "🇨🇿 Чехія",
    "🇸🇰 Словаччина",     "🇭🇺 Угорщина",         "🇷🇴 Румунія",
    "🇧🇬 Болгарія",       "🇦🇹 Австрія",           "🇨🇭 Швейцарія",
    "🇩🇪 Німеччина",      "🇫🇷 Франція",           "🇪🇸 Іспанія",
    "🇵🇹 Португалія",     "🇮🇹 Італія",            "🇳🇱 Нідерланди",
    "🇬🇧 Велика Британія","🇺🇸 США",                "🇨🇦 Канада",
    "🇦🇺 Австралія",
]

# ─── Translations (UK is full; EN/RU map to selected keys, UK fallback) ──────
_LX = {
    'uk': {
        # accounts menu
        'acc_header':     "📱 <b>Акаунти TikTok</b>\n\nСписок акаунтів:",
        'no_accs':        "Жодного акаунту не додано.",
        'btn_cookie':     "➕ Додати акаунт (Cookie)",
        'btn_buy_acc':    "📱 Купити акаунти",
        'btn_buy_proxy':  "🌍 Купити проксі",
        'btn_proxy':      "🌐 Керувати проксі",
        'btn_del_acc':    "🗑 Видалити акаунти",
        'btn_params':     "⚙️ Керувати параметрами реклами",
        # cookie input
        'ask_cookie':     ("📋 Надішліть Cookie рядок(и) для TikTok акаунту.\n"
                           "Кожен акаунт — з окремого рядка."),
        'checking':       "⏳ Перевіряю акаунт(и)...",
        'added_ok':       "✅ Додано: {n}",
        'added_fail':     "❌ Не вдалося (перевірте cookie): {n}",
        'added_dup':      "↩️ Пропущено дублікатів: {n}",
        'limit_hit':      "⚠️ Досягнуто ліміт у {lim} акаунтів",
        # account / proxy delete
        'ask_del_acc':    ("🗑 Введіть, кого видалити:\n"
                           "• <b>1</b> — один акаунт за номером\n"
                           "• <b>2-5</b> — діапазон\n"
                           "• <b>all</b> — всі акаунти"),
        'del_ok_n':       "✅ Видалено: {n}",
        'del_range_err':  "❌ Невірний діапазон. Приклад: 2-5",
        'acc_not_found':  "❌ Акаунт не знайдено",
        # proxy menu
        'proxy_header':   "🌐 <b>SOCKS5 проксі</b>\n\nСписок проксі (round-robin до акаунтів):",
        'no_proxies':     "Жодного проксі не додано.",
        'btn_proxy_add':  "➕ Додати проксі",
        'btn_proxy_del':  "🗑 Видалити проксі",
        'ask_proxy_add':  ("🌐 Надішліть SOCKS5 проксі — кожен з нового рядка:\n"
                           "<code>socks5://host:port</code>\n"
                           "<code>socks5://user:pass@host:port</code>"),
        'proxy_added_n':  "✅ Додано проксі: {n}",
        'proxy_invalid_n':"❌ Пропущено невірних: {n}",
        'ask_del_proxy':  ("🗑 Введіть, які проксі видалити:\n"
                           "• <b>1</b> — один проксі за номером\n"
                           "• <b>2-4</b> — діапазон\n"
                           "• <b>all</b> — всі проксі"),
        'proxy_not_found':"❌ Проксі не знайдено",
        # params menu
        'params_header':  "⚙️ <b>Параметри реклами TikTok</b>",
        'p_country':      "🌍 Країна: <b>{v}</b>",
        'p_hashtags':     "🔖 Хештеги: <b>{v}</b>",
        'p_nicks':        "📝 Нікнейми: <b>{v}</b>",
        'p_avatars':      "👥 Аватарки: <b>{v}</b>",
        'p_main':         "📕 Основне повідомлення: <b>{v}</b>",
        'p_replies':      "📗 Відповіді: <b>{v}</b>",
        'p_neuro':        "🖲 Нейроперегляд: <b>{v}</b>",
        'p_state':        "🤔 Стан боту: <b>{v}</b>",
        'on_str':         "✅ Увімкнено",
        'off_str':        "⏹ Вимкнено",
        'none_str':       "не встановлено",
        'btn_set_country':"🌍 Вибрати країну",
        'btn_add_hashtag':"➕ Додати хештег",
        'btn_set_nicks':  "📝 Змінити Nickname",
        'btn_set_avatar': "👥 Змінити аватарки",
        'btn_set_main':   "📕 Змінити текст основного повідомлення",
        'btn_set_reply':  "📗 Змінити текст додаткових повідомлень",
        'btn_neuro':      "🖲 Нейроперегляд",
        'btn_state':      "🤔 Стан боту",
        'btn_back':       "⬅️ Назад",
        'btn_cancel':     "⬅️ Скасувати",
        'country_title':  "🌍 Виберіть країну:",
        'country_set':    "✅ Країну встановлено: {v}",
        # text inputs
        'ask_hashtags':   ("🔖 Введіть хештеги (без #), через кому або з нового рядка.\n"
                           "Бот буде моніторити нові та старі відео під ними."),
        'hashtags_set':   "✅ Хештеги: {v}",
        'ask_nicks':      ("📝 Надішліть до 25 нікнеймів — кожен з нового рядка.\n"
                           "Вони будуть рівномірно розподілені на акаунти."),
        'nicks_set':      "✅ Нікнеймів збережено: {n}",
        'ask_avatars':    ("👥 Надішліть <b>ZIP-архів</b> з аватарками "
                           "(PNG/JPG/JPEG/WEBP).\n"
                           f"~{NO_AVATAR_PCT}% акаунтів залишаться без аватарки."),
        'avatars_set':    "✅ Завантажено {n} аватарок. Призначено випадково на {a} акаунтів.",
        'avatars_zip_err':"❌ Не вдалося розпакувати ZIP. Перевірте файл.",
        'avatars_empty':  "❌ В архіві немає підтримуваних зображень.",
        'ask_main':       ("📕 Введіть текст основного повідомлення.\n"
                           "Воно буде надіслане під кожне відео з затримкою 1,5 хв "
                           "між постами; нові відео обробляються першими."),
        'main_set':       "✅ Основне повідомлення збережено",
        'ask_reply':      (f"📗 Надішліть до {REPLY_STYLE_LIMIT} стилів відповідей — "
                           "кожен з <b>нового рядка</b>.\n"
                           "На кожне основне повідомлення відповідатимуть "
                           f"{DEFAULT_REPLY_MIN}-{DEFAULT_REPLY_MAX} акаунтів випадковими стилями."),
        'reply_set':      "✅ Стилів відповідей збережено: {n}",
        'neuro_on':       "✅ Нейроперегляд увімкнено",
        'neuro_off':      "⏹ Нейроперегляд вимкнено",
        'state_on':       "✅ Бот працює — продовжую розсилку",
        'state_off':      "⏹ Бот зупинено",
        # bot toggle errors
        'need_main':      "⚠️ Спочатку встановіть основне повідомлення",
        'need_hashtags':  "⚠️ Спочатку додайте хештеги",
        'need_acc':       "⚠️ Немає активних акаунтів",
    },
    'en': {
        'acc_header':     "📱 <b>TikTok Accounts</b>\n\nAccount list:",
        'no_accs':        "No accounts added.",
        'btn_cookie':     "➕ Add account (Cookie)",
        'btn_buy_acc':    "📱 Buy accounts",
        'btn_buy_proxy':  "🌍 Buy proxies",
        'btn_proxy':      "🌐 Manage proxies",
        'btn_del_acc':    "🗑 Delete accounts",
        'btn_params':     "⚙️ Ad parameters",
        'btn_back':       "⬅️ Back",
        'btn_cancel':     "⬅️ Cancel",
    },
    'ru': {
        'acc_header':     "📱 <b>Аккаунты TikTok</b>\n\nСписок аккаунтов:",
        'no_accs':        "Аккаунтов нет.",
        'btn_cookie':     "➕ Добавить аккаунт (Cookie)",
        'btn_buy_acc':    "📱 Купить аккаунты",
        'btn_buy_proxy':  "🌍 Купить прокси",
        'btn_proxy':      "🌐 Управление прокси",
        'btn_del_acc':    "🗑 Удалить аккаунты",
        'btn_params':     "⚙️ Параметры рекламы",
        'btn_back':       "⬅️ Назад",
        'btn_cancel':     "⬅️ Отмена",
    },
}


def _lang(uid: int) -> str:
    try:
        import rukla as _r
        return _r.get_user_data(uid).get('lang', 'uk')
    except Exception:
        return 'uk'


def _LT(uid: int, key: str) -> str:
    """Local translation; falls back to UK."""
    lang = _lang(uid)
    return _LX.get(lang, _LX['uk']).get(key, _LX['uk'].get(key, key))


def _T(uid: int, key: str) -> str:
    """Proxy to global rukla.T for shared keys (b_back, etc.)."""
    try:
        import rukla as _r
        return _r.T(uid, key)
    except Exception:
        return key


# ════════════════════════════════════════════════════════════════════════════
#  Persistence
# ════════════════════════════════════════════════════════════════════════════

def _load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _save_json(path: str, data) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_accounts() -> None:
    global _accounts
    _accounts = _load_json(TIKTOK_ACCOUNTS_FILE, {})


def _save_accounts() -> None:
    _save_json(TIKTOK_ACCOUNTS_FILE, _accounts)


def _load_settings() -> None:
    global _settings
    _settings = _load_json(TIKTOK_SETTINGS_FILE, {})


def _save_settings() -> None:
    _save_json(TIKTOK_SETTINGS_FILE, _settings)


def _load_commented() -> None:
    global _commented
    _commented = _load_json(TIKTOK_COMMENTED_FILE, {})


def _save_commented() -> None:
    _save_json(TIKTOK_COMMENTED_FILE, _commented)


def _load_all() -> None:
    _load_accounts(); _load_settings(); _load_commented()


def _get_user_accounts(uid: int) -> list:
    return _accounts.get(str(uid), [])


def _set_user_accounts(uid: int, accs: list) -> None:
    _accounts[str(uid)] = accs
    _save_accounts()


def _default_settings() -> dict:
    return {
        'country':       '',
        'hashtags':      [],
        'nicknames':     [],
        'avatars':       [],            # list of file paths under TIKTOK_AVATARS_ROOT/<uid>/
        'main_message':  '',
        'reply_styles':  [],            # up to REPLY_STYLE_LIMIT strings
        'reply_min':     DEFAULT_REPLY_MIN,
        'reply_max':     DEFAULT_REPLY_MAX,
        'proxies':       [],            # ['socks5://...', ...]
        'neuro_active':  False,
        'bot_active':    True,          # pause/resume — defaults ON
    }


def _get_user_settings(uid: int) -> dict:
    uid_str = str(uid)
    if uid_str not in _settings:
        _settings[uid_str] = _default_settings()
    else:
        # Ensure forward-compat keys
        defaults = _default_settings()
        for k, v in defaults.items():
            _settings[uid_str].setdefault(k, v)
    return _settings[uid_str]


def _clear_pending(uid: int) -> None:
    _pending.pop(uid, None)


# ════════════════════════════════════════════════════════════════════════════
#  TikTok API helpers
# ════════════════════════════════════════════════════════════════════════════

_TT_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/124.0.0.0 Safari/537.36'),
    'Referer': 'https://www.tiktok.com/',
    'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'application/json, text/plain, */*',
}


def _normalize_cookie_input(raw: str) -> list:
    raw = raw.strip()
    if raw.startswith('['):
        try:
            items = json.loads(raw)
            parts = [f"{i.get('name','')}={i.get('value','')}"
                     for i in items if i.get('name')]
            joined = '; '.join(parts)
            return [joined] if joined else []
        except (json.JSONDecodeError, AttributeError):
            pass
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _extract_uid_from_cookie(cookie: str) -> str:
    for part in cookie.split(';'):
        part = part.strip()
        if '=' not in part:
            continue
        k, _, v = part.partition('=')
        if k.strip() in ('uid', 'uid_tt', 'uid_tt_ss'):
            return v.strip()
    return ''


def _make_session(cookie: str = '', proxy: str = '') -> requests.Session:
    s = requests.Session()
    s.headers.update(_TT_HEADERS)
    if cookie:
        for part in cookie.split(';'):
            part = part.strip()
            if '=' in part:
                k, v = part.split('=', 1)
                s.cookies.set(k.strip(), v.strip(), domain='.tiktok.com')
    if proxy and proxy.startswith('socks5://'):
        s.proxies.update({'http': proxy, 'https': proxy})
    return s


def _get_tt_info(cookie: str, proxy: str = '') -> tuple:
    """Returns (valid, nickname, unique_id)."""
    try:
        if not any(k in cookie for k in ('sessionid', 'sid_guard', 'sessionid_ss')):
            return False, '?', 'unknown'
        s = _make_session(cookie, proxy)

        for endpoint in (
            'https://www.tiktok.com/passport/web/account/info/',
            'https://www.tiktok.com/api/user/detail/',
        ):
            try:
                resp = s.get(endpoint, timeout=10)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                user = (data.get('data') or
                        data.get('user') or
                        data.get('userInfo', {}).get('user') or
                        {})
                nick = user.get('nickname') or user.get('display_name') or '?'
                uid_  = (user.get('unique_id') or user.get('uniqueId') or
                         user.get('username') or '?')
                if uid_ != '?':
                    return True, nick, uid_
            except Exception:
                pass

        from_cookie = _extract_uid_from_cookie(cookie)
        if from_cookie:
            return True, '—', from_cookie
        return True, '—', '?'
    except Exception:
        return False, '?', 'unknown'


def _post_comment(session: requests.Session, video_id: str,
                  text: str, parent_cid: str = '') -> tuple:
    """Returns (success, comment_id)."""
    try:
        data = {
            'aweme_id': video_id,
            'text': text,
            'is_self_see': '0',
        }
        if parent_cid:
            data['reply_id'] = parent_cid
        resp = session.post('https://www.tiktok.com/api/comment/publish/',
                            data=data, timeout=15)
        if resp.status_code == 200:
            d = resp.json()
            if d.get('status_code') == 0:
                return True, d.get('comment', {}).get('cid', '')
    except Exception:
        pass
    return False, ''


def _like_video(session: requests.Session, video_id: str) -> bool:
    try:
        resp = session.post('https://www.tiktok.com/api/commit/digg/item/',
                            data={'aweme_id': video_id, 'type': '1'},
                            timeout=10)
        return resp.status_code == 200 and resp.json().get('status_code') == 0
    except Exception:
        return False


def _like_comment(session: requests.Session, video_id: str, cid: str) -> bool:
    if not cid:
        return False
    try:
        resp = session.post('https://www.tiktok.com/api/comment/digg/',
                            data={'aweme_id': video_id, 'cid': cid,
                                  'digg_type': '1'},
                            timeout=10)
        return resp.status_code == 200 and resp.json().get('status_code') == 0
    except Exception:
        return False


def _get_hashtag_id(name: str, session: requests.Session) -> str:
    try:
        resp = session.get('https://www.tiktok.com/api/challenge/detail/',
                           params={'challengeName': name}, timeout=10)
        if resp.status_code == 200:
            d = resp.json()
            return (d.get('challengeInfo', {})
                     .get('challenge', {})
                     .get('id', ''))
    except Exception:
        pass
    return ''


def _fetch_hashtag_videos(challenge_id: str, cursor: int,
                          session: requests.Session, count: int = 30) -> tuple:
    """Returns (items: list[dict {id, create_time}], next_cursor, has_more)."""
    try:
        resp = session.get('https://www.tiktok.com/api/challenge/item_list/',
                           params={'challengeID': challenge_id, 'count': count,
                                   'cursor': cursor, 'type': 5},
                           timeout=10)
        if resp.status_code == 200:
            d = resp.json()
            raw = d.get('itemList', [])
            items = []
            for it in raw:
                vid = str(it.get('id') or it.get('aweme_id', ''))
                if vid:
                    items.append({'id': vid,
                                  'create_time': int(it.get('createTime') or
                                                     it.get('create_time') or 0)})
            return items, int(d.get('cursor', cursor + len(items))), bool(d.get('hasMore'))
    except Exception:
        pass
    return [], cursor, False


# ════════════════════════════════════════════════════════════════════════════
#  Proxy parsing
# ════════════════════════════════════════════════════════════════════════════

_PROXY_RE = re.compile(r'^socks5://([^:@\s]+(?::[^@\s]+)?@)?[^:\s]+:\d+$')


def _is_valid_socks5(line: str) -> bool:
    return bool(_PROXY_RE.match(line.strip()))


def _proxy_for_account(uid: int, idx: int) -> str:
    """Round-robin proxy assignment from settings.proxies."""
    s = _get_user_settings(uid)
    proxies = s.get('proxies', [])
    if not proxies:
        return ''
    return proxies[idx % len(proxies)]


# ════════════════════════════════════════════════════════════════════════════
#  Range / single / all parser  (1, 2-5, all)
# ════════════════════════════════════════════════════════════════════════════

def _parse_range(text: str, n_total: int) -> tuple:
    """Returns (mode, indices) where mode in {'one','range','all','err'}.
    indices are 0-based and clamped to [0, n_total)."""
    t = text.strip().lower()
    if t == 'all':
        return 'all', list(range(n_total))
    if '-' in t:
        try:
            a, b = t.split('-', 1)
            start = int(a.strip()) - 1
            end   = int(b.strip()) - 1
            if start > end:
                start, end = end, start
            indices = [i for i in range(start, end + 1) if 0 <= i < n_total]
            return 'range', indices
        except Exception:
            return 'err', []
    digits = ''.join(filter(str.isdigit, t))
    if not digits:
        return 'err', []
    one = int(digits) - 1
    if 0 <= one < n_total:
        return 'one', [one]
    return 'err', []


# ════════════════════════════════════════════════════════════════════════════
#  Display name / avatar distribution helpers
# ════════════════════════════════════════════════════════════════════════════

def _distribute_nicknames(uid: int) -> None:
    """Assign settings.nicknames evenly to accounts (round-robin)."""
    s = _get_user_settings(uid)
    nicks = s.get('nicknames', [])
    accs  = _get_user_accounts(uid)
    if not nicks or not accs:
        return
    for i, acc in enumerate(accs):
        acc['display_nickname'] = nicks[i % len(nicks)]
    _set_user_accounts(uid, accs)


def _distribute_avatars(uid: int) -> int:
    """Assign settings.avatars to accounts; ~NO_AVATAR_PCT% get none.
    Returns number of accounts that received an avatar."""
    s = _get_user_settings(uid)
    pool = list(s.get('avatars', []))
    accs = _get_user_accounts(uid)
    if not accs:
        return 0
    rnd = random.Random()
    given = 0
    for acc in accs:
        if not pool:
            acc['avatar_path'] = ''
            continue
        if rnd.randint(1, 100) <= NO_AVATAR_PCT:
            acc['avatar_path'] = ''
        else:
            acc['avatar_path'] = rnd.choice(pool)
            given += 1
    _set_user_accounts(uid, accs)
    return given


def _avatars_dir(uid: int) -> str:
    p = os.path.join(TIKTOK_AVATARS_ROOT, str(uid))
    os.makedirs(p, exist_ok=True)
    return p


_IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp')


def _extract_avatars_zip(uid: int, zip_bytes: bytes) -> list:
    """Extract supported images from a ZIP archive, store under avatars dir.
    Returns list of stored absolute paths."""
    target = _avatars_dir(uid)
    # Wipe previous avatars to keep things tidy
    for fn in os.listdir(target):
        try:
            os.remove(os.path.join(target, fn))
        except Exception:
            pass
    paths: list = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = os.path.basename(info.filename)
            if not name:
                continue
            if not name.lower().endswith(_IMAGE_EXTS):
                continue
            dest = os.path.join(target, name)
            with zf.open(info) as src, open(dest, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            paths.append(dest)
    return paths


# ════════════════════════════════════════════════════════════════════════════
#  AI hook (Neuro-feed)
# ════════════════════════════════════════════════════════════════════════════

def _ai_comment_for_video(video_meta: dict) -> str:
    """Generate a topical comment for a TikTok video.
    Stub — wire to a real provider (Anthropic/OpenAI) when available.
    Receives whatever metadata the worker has (id, description, hashtags)."""
    desc = (video_meta.get('desc') or '').strip()
    if desc:
        return f"Цікаво про «{desc[:40]}» 🔥"
    return "Топ! 🔥"


# ════════════════════════════════════════════════════════════════════════════
#  Background workers
# ════════════════════════════════════════════════════════════════════════════

def _active_accounts(uid: int) -> list:
    return [a for a in _get_user_accounts(uid) if a.get('active', False)]


def _bg_worker(bot, uid: int, stop_evt: threading.Event) -> None:
    """Main comment + replies worker.

    For each hashtag, fetch videos; sort by create_time DESC (newest first);
    skip already-commented; for each new video:
      1. Pick primary account → post main comment.
      2. Like the video, like own comment.
      3. Pick reply_min..reply_max OTHER accounts → each posts a random
         reply style; likes parent comment + own reply + video.
      4. Wait COMMENT_DELAY_SECS before next video.
    """
    uid_str = str(uid)

    while not stop_evt.is_set():
        try:
            _load_all()
            s = _get_user_settings(uid)

            if not s.get('bot_active', True):
                stop_evt.wait(30); continue

            hashtags     = s.get('hashtags', [])
            main_message = s.get('main_message', '')
            styles       = s.get('reply_styles', [])
            r_min        = max(1, int(s.get('reply_min', DEFAULT_REPLY_MIN)))
            r_max        = max(r_min, int(s.get('reply_max', DEFAULT_REPLY_MAX)))

            if not hashtags or not main_message:
                stop_evt.wait(120); continue

            actives = _active_accounts(uid)
            if not actives:
                stop_evt.wait(120); continue

            if uid_str not in _commented:
                _commented[uid_str] = {}

            for hashtag in hashtags:
                if stop_evt.is_set():
                    break
                ht = hashtag.lstrip('#').strip()
                if not ht:
                    continue

                # Use the first active account for fetching
                lead_acc = actives[0]
                lead_proxy = _proxy_for_account(uid, 0)
                lead_session = _make_session(lead_acc.get('cookie', ''), lead_proxy)

                cid_h = _get_hashtag_id(ht, lead_session)
                if not cid_h:
                    continue

                seen = set(_commented[uid_str].get(ht, []))

                # Collect a page of videos
                items, _, _ = _fetch_hashtag_videos(cid_h, 0, lead_session, count=30)
                # Newest first
                items.sort(key=lambda x: x.get('create_time', 0), reverse=True)

                for it in items:
                    if stop_evt.is_set():
                        break
                    if not s.get('bot_active', True):
                        break

                    vid = it['id']
                    if vid in seen:
                        continue

                    # Refresh actives each loop in case some failed
                    actives = _active_accounts(uid)
                    if not actives:
                        break

                    primary = actives[0]
                    primary_idx = _get_user_accounts(uid).index(primary)
                    p_session = _make_session(primary.get('cookie', ''),
                                              _proxy_for_account(uid, primary_idx))
                    ok, main_cid = _post_comment(p_session, vid, main_message)
                    if not ok:
                        # Mark as seen anyway to avoid retry loop on the same vid
                        seen.add(vid)
                        _commented[uid_str][ht] = list(seen)
                        _save_commented()
                        stop_evt.wait(5)
                        continue

                    # Like-on-success
                    _like_video(p_session, vid)
                    _like_comment(p_session, vid, main_cid)

                    # Pick replier accounts (different from primary)
                    others = [a for a in actives if a is not primary]
                    if styles and others:
                        n_replies = random.randint(r_min, r_max)
                        n_replies = min(n_replies, len(others))
                        repliers = random.sample(others, n_replies) if n_replies else []
                        used_styles = random.sample(styles,
                                                    min(len(styles), n_replies))
                        for j, racc in enumerate(repliers):
                            if stop_evt.is_set():
                                break
                            r_idx     = _get_user_accounts(uid).index(racc)
                            r_session = _make_session(racc.get('cookie', ''),
                                                      _proxy_for_account(uid, r_idx))
                            r_text    = used_styles[j % len(used_styles)] if used_styles \
                                        else random.choice(styles)
                            r_ok, r_cid = _post_comment(r_session, vid, r_text,
                                                        parent_cid=main_cid)
                            if r_ok:
                                _like_comment(r_session, vid, main_cid)
                                _like_comment(r_session, vid, r_cid)
                                _like_video(r_session, vid)
                            stop_evt.wait(2)

                    seen.add(vid)
                    _commented[uid_str][ht] = list(seen)
                    _save_commented()

                    # 1.5 min between main comments — but new videos have priority,
                    # so we re-poll the hashtag every cycle.
                    stop_evt.wait(COMMENT_DELAY_SECS)

        except Exception:
            pass

        # Polling cadence between sweeps (catches new videos)
        stop_evt.wait(60)

    # Worker exited — mark inactive
    try:
        _load_settings()
        s = _get_user_settings(uid)
        s['bot_active'] = False
        _save_settings()
    except Exception:
        pass


def _start_bg_worker(bot, uid: int) -> None:
    _stop_bg_worker(uid)
    evt = threading.Event()
    _bg_stop[uid] = evt
    t = threading.Thread(target=_bg_worker, args=(bot, uid, evt), daemon=True)
    _bg_thread[uid] = t
    t.start()


def _stop_bg_worker(uid: int) -> None:
    if uid in _bg_stop:
        _bg_stop[uid].set()
        if uid in _bg_thread:
            _bg_thread[uid].join(timeout=5)
        _bg_stop.pop(uid, None)
        _bg_thread.pop(uid, None)


# ── Neuro-feed worker ────────────────────────────────────────────────────────

def _neuro_worker(bot, uid: int, stop_evt: threading.Event) -> None:
    """Scroll FYP per active account. Like every 2nd, comment every 4th
    using AI-generated text. Currently a skeleton — actually scrolling/
    liking on TikTok requires Playwright (see ruklaTikTok.py). Here we
    keep state and call hooks; wire to Playwright when ready."""
    while not stop_evt.is_set():
        try:
            _load_all()
            s = _get_user_settings(uid)
            if not s.get('neuro_active', False):
                stop_evt.wait(30); continue

            actives = _active_accounts(uid)
            if not actives:
                stop_evt.wait(120); continue

            for idx, acc in enumerate(actives):
                if stop_evt.is_set():
                    break
                if not s.get('neuro_active', False):
                    break
                # Per-account FYP iteration would happen here.
                # For now just sleep — full implementation requires
                # Playwright (ruklaTikTok.TikTokSession.warmup_fyp + AI hook).
                stop_evt.wait(15)
        except Exception:
            pass
        stop_evt.wait(60)


def _start_neuro_worker(bot, uid: int) -> None:
    _stop_neuro_worker(uid)
    evt = threading.Event()
    _neuro_stop[uid] = evt
    t = threading.Thread(target=_neuro_worker, args=(bot, uid, evt), daemon=True)
    _neuro_thread[uid] = t
    t.start()


def _stop_neuro_worker(uid: int) -> None:
    if uid in _neuro_stop:
        _neuro_stop[uid].set()
        if uid in _neuro_thread:
            _neuro_thread[uid].join(timeout=5)
        _neuro_stop.pop(uid, None)
        _neuro_thread.pop(uid, None)


# ════════════════════════════════════════════════════════════════════════════
#  Menu builders
# ════════════════════════════════════════════════════════════════════════════

def _acc_line(acc: dict, idx: int) -> str:
    nick = acc.get('display_nickname') or acc.get('nickname', '?')
    uid_ = acc.get('unique_id', '?')
    ico  = "✅" if acc.get('active', False) else "❌"
    av   = " 👤" if acc.get('avatar_path') else ""
    return f"№{idx} {nick} — @{uid_} {ico}{av}"


def _build_accounts_text(uid: int) -> str:
    accs = _get_user_accounts(uid)
    header = _LT(uid, 'acc_header')
    if not accs:
        return header + "\n\n" + _LT(uid, 'no_accs')
    lines = [header]
    for i, a in enumerate(accs, 1):
        lines.append(_acc_line(a, i))
    return "\n".join(lines)


def _acc_markup(uid: int) -> types.InlineKeyboardMarkup:
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_cookie'),    callback_data='tt_acc_add'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_proxy'),     callback_data='tt_proxy'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_del_acc'),   callback_data='tt_acc_del'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_params'),    callback_data='tt_params'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_buy_acc'),   callback_data='r7_buy_acc_tiktok'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_buy_proxy'), callback_data='r7_buy_proxy_tiktok'))
    m.add(types.InlineKeyboardButton(_T(uid, 'b_back'),         callback_data='m_manage_tiktok'))
    return m


def open_tiktok_menu(bot, uid: int, message_id: int) -> None:
    _load_all()
    text = _build_accounts_text(uid)
    try:
        bot.edit_message_text(text, uid, message_id,
                              reply_markup=_acc_markup(uid), parse_mode='HTML')
    except Exception:
        bot.send_message(uid, text, reply_markup=_acc_markup(uid), parse_mode='HTML')


# ── Proxy menu ───────────────────────────────────────────────────────────────

def _proxy_text(uid: int) -> str:
    s = _get_user_settings(uid)
    proxies = s.get('proxies', [])
    header = _LT(uid, 'proxy_header')
    if not proxies:
        return header + "\n\n" + _LT(uid, 'no_proxies')
    lines = [header]
    for i, p in enumerate(proxies, 1):
        lines.append(f"№{i} <code>{p}</code>")
    return "\n".join(lines)


def _proxy_markup(uid: int) -> types.InlineKeyboardMarkup:
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_proxy_add'), callback_data='tt_proxy_add'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_proxy_del'), callback_data='tt_proxy_del'))
    m.add(types.InlineKeyboardButton(_T(uid, 'b_back'),         callback_data='tt_acc_open'))
    return m


# ── Params menu ──────────────────────────────────────────────────────────────

def _short(text: str, n: int = 35) -> str:
    if not text:
        return ''
    return text if len(text) <= n else text[:n] + '…'


def _build_params_text(uid: int) -> str:
    s = _get_user_settings(uid)
    none = _LT(uid, 'none_str')

    country  = s.get('country') or none
    hashtags = ', '.join(f"#{h}" for h in s.get('hashtags', [])) or none
    nicks    = f"{len(s.get('nicknames', []))}" if s.get('nicknames') else none
    avatars  = f"{len(s.get('avatars', []))}"   if s.get('avatars')   else none
    main_v   = _short(s.get('main_message', ''), 35) or none
    replies  = f"{len(s.get('reply_styles', []))}/{REPLY_STYLE_LIMIT}" \
               if s.get('reply_styles') else none
    neuro    = _LT(uid, 'on_str') if s.get('neuro_active') else _LT(uid, 'off_str')
    state    = _LT(uid, 'on_str') if s.get('bot_active', True) else _LT(uid, 'off_str')

    return "\n".join([
        _LT(uid, 'params_header'),
        "",
        _LT(uid, 'p_country' ).format(v=country),
        _LT(uid, 'p_hashtags').format(v=_short(hashtags, 60)),
        _LT(uid, 'p_nicks'   ).format(v=nicks),
        _LT(uid, 'p_avatars' ).format(v=avatars),
        _LT(uid, 'p_main'    ).format(v=main_v),
        _LT(uid, 'p_replies' ).format(v=replies),
        _LT(uid, 'p_neuro'   ).format(v=neuro),
        _LT(uid, 'p_state'   ).format(v=state),
    ])


def _params_markup(uid: int) -> types.InlineKeyboardMarkup:
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_set_country'), callback_data='tt_set_country'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_add_hashtag'), callback_data='tt_set_hashtags'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_set_nicks'),   callback_data='tt_set_nicks'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_set_avatar'),  callback_data='tt_set_avatars'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_set_main'),    callback_data='tt_set_main'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_set_reply'),   callback_data='tt_set_reply'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_neuro'),       callback_data='tt_toggle_neuro'))
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_state'),       callback_data='tt_toggle_state'))
    m.add(types.InlineKeyboardButton(_T(uid, 'b_back'),           callback_data='tt_acc_open'))
    return m


def open_params_menu(bot, uid: int, message_id: int) -> None:
    _load_all()
    text = _build_params_text(uid)
    try:
        bot.edit_message_text(text, uid, message_id,
                              reply_markup=_params_markup(uid),
                              parse_mode='HTML')
    except Exception:
        bot.send_message(uid, text, reply_markup=_params_markup(uid),
                         parse_mode='HTML')


def _country_markup(uid: int) -> types.InlineKeyboardMarkup:
    m = types.InlineKeyboardMarkup(row_width=3)
    btns = [types.InlineKeyboardButton(c, callback_data=f"tt_country_{i}")
            for i, c in enumerate(COUNTRIES)]
    m.add(*btns)
    m.add(types.InlineKeyboardButton(_T(uid, 'b_back'), callback_data='tt_params'))
    return m


def _cancel_markup(uid: int, cb: str) -> types.InlineKeyboardMarkup:
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton(_LT(uid, 'btn_cancel'), callback_data=cb))
    return m


# ════════════════════════════════════════════════════════════════════════════
#  Callback registration
# ════════════════════════════════════════════════════════════════════════════

def register_callbacks(bot):
    global _bot_ref
    _bot_ref = bot

    _load_all()
    # Restart any active workers
    for uid_str, s in list(_settings.items()):
        try:
            uid_int = int(uid_str)
        except Exception:
            continue
        if s.get('bot_active', False):
            _start_bg_worker(bot, uid_int)
        if s.get('neuro_active', False):
            _start_neuro_worker(bot, uid_int)

    # ── open accounts menu ────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == 'tt_acc_open')
    def cb_acc_open(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        open_tiktok_menu(bot, uid, call.message.message_id)

    # ── add account by cookie ────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == 'tt_acc_add')
    def cb_acc_add(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending[uid] = ACT_COOKIE
        bot.answer_callback_query(call.id)
        bot.send_message(uid, _LT(uid, 'ask_cookie'),
                         reply_markup=_cancel_markup(uid, 'tt_cancel'))

    # ── delete accounts (one/range/all) ──────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == 'tt_acc_del')
    def cb_acc_del(call):
        uid = call.message.chat.id
        if not _get_user_accounts(uid):
            bot.answer_callback_query(call.id, _LT(uid, 'no_accs'))
            return
        _clear_pending(uid)
        _pending[uid] = ACT_ACC_DEL
        bot.answer_callback_query(call.id)
        bot.send_message(uid, _LT(uid, 'ask_del_acc'),
                         reply_markup=_cancel_markup(uid, 'tt_cancel'),
                         parse_mode='HTML')

    # ── proxy submenu ─────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == 'tt_proxy')
    def cb_proxy(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(_proxy_text(uid), uid, call.message.message_id,
                                  reply_markup=_proxy_markup(uid),
                                  parse_mode='HTML')
        except Exception:
            bot.send_message(uid, _proxy_text(uid),
                             reply_markup=_proxy_markup(uid),
                             parse_mode='HTML')

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_proxy_add')
    def cb_proxy_add(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending[uid] = ACT_PROXY_ADD
        bot.answer_callback_query(call.id)
        bot.send_message(uid, _LT(uid, 'ask_proxy_add'),
                         reply_markup=_cancel_markup(uid, 'tt_cancel'),
                         parse_mode='HTML')

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_proxy_del')
    def cb_proxy_del(call):
        uid = call.message.chat.id
        s = _get_user_settings(uid)
        if not s.get('proxies'):
            bot.answer_callback_query(call.id, _LT(uid, 'no_proxies'))
            return
        _clear_pending(uid)
        _pending[uid] = ACT_PROXY_DEL
        bot.answer_callback_query(call.id)
        bot.send_message(uid, _LT(uid, 'ask_del_proxy'),
                         reply_markup=_cancel_markup(uid, 'tt_cancel'),
                         parse_mode='HTML')

    # ── params submenu ────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == 'tt_params')
    def cb_params(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        open_params_menu(bot, uid, call.message.message_id)

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_set_country')
    def cb_set_country(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(_LT(uid, 'country_title'), uid,
                                  call.message.message_id,
                                  reply_markup=_country_markup(uid))
        except Exception:
            bot.send_message(uid, _LT(uid, 'country_title'),
                             reply_markup=_country_markup(uid))

    @bot.callback_query_handler(func=lambda c: c.data.startswith('tt_country_'))
    def cb_country_pick(call):
        uid = call.message.chat.id
        try:
            idx = int(call.data.split('_')[-1])
            country = COUNTRIES[idx]
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id)
            return
        s = _get_user_settings(uid)
        s['country'] = country
        _save_settings()
        bot.answer_callback_query(call.id, _LT(uid, 'country_set').format(v=country))
        open_params_menu(bot, uid, call.message.message_id)

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_set_hashtags')
    def cb_set_hashtags(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending[uid] = ACT_HASHTAGS
        bot.answer_callback_query(call.id)
        bot.send_message(uid, _LT(uid, 'ask_hashtags'),
                         reply_markup=_cancel_markup(uid, 'tt_cancel'))

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_set_nicks')
    def cb_set_nicks(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending[uid] = ACT_NICKS
        bot.answer_callback_query(call.id)
        bot.send_message(uid, _LT(uid, 'ask_nicks'),
                         reply_markup=_cancel_markup(uid, 'tt_cancel'))

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_set_avatars')
    def cb_set_avatars(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending[uid] = ACT_AVATARS
        bot.answer_callback_query(call.id)
        bot.send_message(uid, _LT(uid, 'ask_avatars'),
                         reply_markup=_cancel_markup(uid, 'tt_cancel'),
                         parse_mode='HTML')

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_set_main')
    def cb_set_main(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending[uid] = ACT_MAIN_MSG
        bot.answer_callback_query(call.id)
        bot.send_message(uid, _LT(uid, 'ask_main'),
                         reply_markup=_cancel_markup(uid, 'tt_cancel'))

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_set_reply')
    def cb_set_reply(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending[uid] = ACT_REPLY_STYLES
        bot.answer_callback_query(call.id)
        bot.send_message(uid, _LT(uid, 'ask_reply'),
                         reply_markup=_cancel_markup(uid, 'tt_cancel'),
                         parse_mode='HTML')

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_toggle_neuro')
    def cb_toggle_neuro(call):
        uid = call.message.chat.id
        s = _get_user_settings(uid)
        if s.get('neuro_active', False):
            s['neuro_active'] = False
            _save_settings()
            _stop_neuro_worker(uid)
            bot.answer_callback_query(call.id, _LT(uid, 'neuro_off'))
        else:
            if not _active_accounts(uid):
                bot.answer_callback_query(call.id, _LT(uid, 'need_acc'))
                return
            s['neuro_active'] = True
            _save_settings()
            _start_neuro_worker(bot, uid)
            bot.answer_callback_query(call.id, _LT(uid, 'neuro_on'))
        open_params_menu(bot, uid, call.message.message_id)

    @bot.callback_query_handler(func=lambda c: c.data == 'tt_toggle_state')
    def cb_toggle_state(call):
        uid = call.message.chat.id
        s = _get_user_settings(uid)
        currently = s.get('bot_active', True)
        if currently:
            s['bot_active'] = False
            _save_settings()
            _stop_bg_worker(uid)
            bot.answer_callback_query(call.id, _LT(uid, 'state_off'))
        else:
            if not s.get('main_message'):
                bot.answer_callback_query(call.id, _LT(uid, 'need_main'))
                return
            if not s.get('hashtags'):
                bot.answer_callback_query(call.id, _LT(uid, 'need_hashtags'))
                return
            if not _active_accounts(uid):
                bot.answer_callback_query(call.id, _LT(uid, 'need_acc'))
                return
            s['bot_active'] = True
            _save_settings()
            _start_bg_worker(bot, uid)
            bot.answer_callback_query(call.id, _LT(uid, 'state_on'))
        open_params_menu(bot, uid, call.message.message_id)

    # ── universal cancel ──────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == 'tt_cancel')
    def cb_cancel(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(uid, call.message.message_id)
        except Exception:
            pass

    # ── proxy buy stub ────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == 'r7_buy_proxy_tiktok')
    def cb_buy_proxy(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        try:
            import rukla as _r
            m = types.InlineKeyboardMarkup()
            m.add(types.InlineKeyboardButton(_T(uid, 'b_back'),
                                             callback_data='tt_acc_open'))
            bot.edit_message_text(_r.T(uid, 'r6_in_dev'), uid,
                                  call.message.message_id, reply_markup=m)
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════
    #  Single text-message handler — dispatches based on _pending[uid]
    # ════════════════════════════════════════════════════════════════════
    @bot.message_handler(
        func=lambda msg: msg.chat.id in _pending,
        content_types=['text'],
    )
    def on_text(message):
        uid    = message.chat.id
        action = _pending.get(uid)
        text   = message.text or ''

        if action == ACT_COOKIE:
            _handle_cookie(bot, uid, text)
        elif action == ACT_PROXY_ADD:
            _handle_proxy_add(bot, uid, text)
        elif action == ACT_PROXY_DEL:
            _handle_proxy_del(bot, uid, text)
        elif action == ACT_ACC_DEL:
            _handle_acc_del(bot, uid, text)
        elif action == ACT_HASHTAGS:
            _handle_hashtags(bot, uid, text)
        elif action == ACT_NICKS:
            _handle_nicks(bot, uid, text)
        elif action == ACT_MAIN_MSG:
            _handle_main_msg(bot, uid, text)
        elif action == ACT_REPLY_STYLES:
            _handle_reply_styles(bot, uid, text)
        # Avatars come via a document handler below

    # ── ZIP document handler (avatars) ────────────────────────────────────
    @bot.message_handler(
        func=lambda msg: (msg.chat.id in _pending and
                          _pending.get(msg.chat.id) == ACT_AVATARS),
        content_types=['document'],
    )
    def on_avatars_zip(message):
        uid = message.chat.id
        _clear_pending(uid)
        try:
            file_info = bot.get_file(message.document.file_id)
            data = bot.download_file(file_info.file_path)
        except Exception:
            bot.send_message(uid, _LT(uid, 'avatars_zip_err'))
            return
        try:
            paths = _extract_avatars_zip(uid, data)
        except zipfile.BadZipFile:
            bot.send_message(uid, _LT(uid, 'avatars_zip_err'))
            return
        if not paths:
            bot.send_message(uid, _LT(uid, 'avatars_empty'))
            return
        s = _get_user_settings(uid)
        s['avatars'] = paths
        _save_settings()
        given = _distribute_avatars(uid)
        bot.send_message(uid, _LT(uid, 'avatars_set').format(n=len(paths), a=given))


# ════════════════════════════════════════════════════════════════════════════
#  Action handlers
# ════════════════════════════════════════════════════════════════════════════

def _handle_cookie(bot, uid: int, text: str) -> None:
    _clear_pending(uid)
    _load_accounts()
    accs = _get_user_accounts(uid)
    cookies = _normalize_cookie_input(text)

    wait_msg = bot.send_message(uid, _LT(uid, 'checking'))
    added = failed = dups = 0
    limit_hit = False

    # Build dedup set: existing cookies AND existing unique_ids
    existing_cookies = {a.get('cookie', '') for a in accs}
    existing_uids    = {a.get('unique_id', '') for a in accs
                        if a.get('unique_id') and a.get('unique_id') != '?'}

    for cookie in cookies:
        if len(accs) >= ACCOUNT_LIMIT:
            limit_hit = True
            break
        # Dedup by raw cookie
        if cookie in existing_cookies:
            dups += 1
            continue
        valid, nick, uid_ = _get_tt_info(cookie)
        # Dedup by resolved unique_id
        if uid_ and uid_ != '?' and uid_ in existing_uids:
            dups += 1
            continue
        accs.append({
            'cookie':    cookie,
            'active':    valid,
            'nickname':  nick,
            'unique_id': uid_,
            'display_nickname': '',
            'avatar_path': '',
        })
        existing_cookies.add(cookie)
        if uid_ and uid_ != '?':
            existing_uids.add(uid_)
        if valid:
            added += 1
        else:
            failed += 1

    _set_user_accounts(uid, accs)
    _distribute_nicknames(uid)
    _distribute_avatars(uid)

    try:
        bot.delete_message(uid, wait_msg.message_id)
    except Exception:
        pass

    if limit_hit:
        bot.send_message(uid, _LT(uid, 'limit_hit').format(lim=ACCOUNT_LIMIT))
    parts = []
    if added:  parts.append(_LT(uid, 'added_ok').format(n=added))
    if failed: parts.append(_LT(uid, 'added_fail').format(n=failed))
    if dups:   parts.append(_LT(uid, 'added_dup').format(n=dups))
    if parts:
        bot.send_message(uid, "\n".join(parts))

    bot.send_message(uid, _build_accounts_text(uid),
                     reply_markup=_acc_markup(uid), parse_mode='HTML')


def _handle_acc_del(bot, uid: int, text: str) -> None:
    _clear_pending(uid)
    accs = _get_user_accounts(uid)
    mode, indices = _parse_range(text, len(accs))
    if mode == 'err':
        bot.send_message(uid, _LT(uid, 'del_range_err'))
        bot.send_message(uid, _build_accounts_text(uid),
                         reply_markup=_acc_markup(uid), parse_mode='HTML')
        return
    new = [a for i, a in enumerate(accs) if i not in indices]
    n = len(accs) - len(new)
    _set_user_accounts(uid, new)
    _distribute_nicknames(uid)
    _distribute_avatars(uid)
    bot.send_message(uid, _LT(uid, 'del_ok_n').format(n=n))
    bot.send_message(uid, _build_accounts_text(uid),
                     reply_markup=_acc_markup(uid), parse_mode='HTML')


def _handle_proxy_add(bot, uid: int, text: str) -> None:
    _clear_pending(uid)
    s = _get_user_settings(uid)
    proxies = list(s.get('proxies', []))
    valid_lines = []
    invalid_n = 0
    for line in text.splitlines():
        ln = line.strip()
        if not ln:
            continue
        if _is_valid_socks5(ln) and ln not in proxies:
            proxies.append(ln)
            valid_lines.append(ln)
        else:
            invalid_n += 1
    s['proxies'] = proxies
    _save_settings()
    parts = [_LT(uid, 'proxy_added_n').format(n=len(valid_lines))]
    if invalid_n:
        parts.append(_LT(uid, 'proxy_invalid_n').format(n=invalid_n))
    bot.send_message(uid, "\n".join(parts))
    bot.send_message(uid, _proxy_text(uid),
                     reply_markup=_proxy_markup(uid), parse_mode='HTML')


def _handle_proxy_del(bot, uid: int, text: str) -> None:
    _clear_pending(uid)
    s = _get_user_settings(uid)
    proxies = list(s.get('proxies', []))
    mode, indices = _parse_range(text, len(proxies))
    if mode == 'err':
        bot.send_message(uid, _LT(uid, 'del_range_err'))
        bot.send_message(uid, _proxy_text(uid),
                         reply_markup=_proxy_markup(uid), parse_mode='HTML')
        return
    new = [p for i, p in enumerate(proxies) if i not in indices]
    n = len(proxies) - len(new)
    s['proxies'] = new
    _save_settings()
    bot.send_message(uid, _LT(uid, 'del_ok_n').format(n=n))
    bot.send_message(uid, _proxy_text(uid),
                     reply_markup=_proxy_markup(uid), parse_mode='HTML')


def _handle_hashtags(bot, uid: int, text: str) -> None:
    _clear_pending(uid)
    s = _get_user_settings(uid)
    raw = re.split(r'[,\n]+', text)
    tags = [t.strip().lstrip('#') for t in raw if t.strip()]
    s['hashtags'] = tags
    _save_settings()
    shown = ', '.join(f"#{t}" for t in tags) or '—'
    bot.send_message(uid, _LT(uid, 'hashtags_set').format(v=shown))
    bot.send_message(uid, _build_params_text(uid),
                     reply_markup=_params_markup(uid), parse_mode='HTML')


def _handle_nicks(bot, uid: int, text: str) -> None:
    _clear_pending(uid)
    s = _get_user_settings(uid)
    nicks = [ln.strip() for ln in text.splitlines() if ln.strip()]
    nicks = nicks[:ACCOUNT_LIMIT]
    s['nicknames'] = nicks
    _save_settings()
    _distribute_nicknames(uid)
    bot.send_message(uid, _LT(uid, 'nicks_set').format(n=len(nicks)))
    bot.send_message(uid, _build_params_text(uid),
                     reply_markup=_params_markup(uid), parse_mode='HTML')


def _handle_main_msg(bot, uid: int, text: str) -> None:
    _clear_pending(uid)
    s = _get_user_settings(uid)
    s['main_message'] = text.strip()
    _save_settings()
    bot.send_message(uid, _LT(uid, 'main_set'))
    bot.send_message(uid, _build_params_text(uid),
                     reply_markup=_params_markup(uid), parse_mode='HTML')


def _handle_reply_styles(bot, uid: int, text: str) -> None:
    _clear_pending(uid)
    s = _get_user_settings(uid)
    styles = [ln.strip() for ln in text.splitlines() if ln.strip()]
    styles = styles[:REPLY_STYLE_LIMIT]
    s['reply_styles'] = styles
    _save_settings()
    bot.send_message(uid, _LT(uid, 'reply_set').format(n=len(styles)))
    bot.send_message(uid, _build_params_text(uid),
                     reply_markup=_params_markup(uid), parse_mode='HTML')
