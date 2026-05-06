"""
rukla5.py — TikTok advertising module

Features:
  - SOCKS5 proxy per account
  - Add accounts via Cookie or Login/Password
  - Country/geo selection
  - Main comment + up to 4 replies
  - Hashtag monitoring with background worker
  - Bot on/off toggle
  - Account/proxy purchase (delegates to rukla7)
"""

import json
import os
import re
import threading
import time
import requests
from telebot import types

# ─── File paths ───────────────────────────────────────────────────────────────
TIKTOK_ACCOUNTS_FILE  = 'tiktok_accounts.json'
TIKTOK_SETTINGS_FILE  = 'tiktok_settings.json'
TIKTOK_COMMENTED_FILE = 'tiktok_commented.json'

# ─── Bot reference (set in register_callbacks) ────────────────────────────────
_bot_ref = None

# ─── In-memory state ──────────────────────────────────────────────────────────
_accounts: dict  = {}   # uid_str -> [{cookie, active, nickname, unique_id, proxy}]
_settings: dict  = {}   # uid_str -> {country, main_comment, replies, hashtags, bot_active}
_commented: dict = {}   # uid_str -> {hashtag_clean -> [video_id, ...]}

# ─── Pending input trackers ───────────────────────────────────────────────────
_pending_cookie_input: set = set()          # waiting for cookie text
_pending_login_step:  dict = {}             # uid -> {'step':'user'|'pass', 'username':str}
_pending_proxy_input: dict = {}             # uid -> acc_idx (int)
_pending_text_input:  dict = {}             # uid -> 'comment'|'replies'|'hashtags'

# ─── Background workers ───────────────────────────────────────────────────────
_bg_stop:   dict = {}   # uid -> threading.Event
_bg_thread: dict = {}   # uid -> threading.Thread

# ─── Countries ────────────────────────────────────────────────────────────────
COUNTRIES = [
    "🇺🇦 Україна",        "🇵🇱 Польща",           "🇨🇿 Чехія",
    "🇸🇰 Словаччина",     "🇭🇺 Угорщина",          "🇷🇴 Румунія",
    "🇧🇬 Болгарія",       "🇦🇹 Австрія",            "🇨🇭 Швейцарія",
    "🇩🇪 Німеччина",      "🇫🇷 Франція",            "🇪🇸 Іспанія",
    "🇵🇹 Португалія",     "🇮🇹 Італія",             "🇳🇱 Нідерланди",
    "🇬🇧 Велика Британія","🇺🇸 США",                "🇨🇦 Канада",
    "🇦🇺 Австралія",
]

# ─── Local translations ───────────────────────────────────────────────────────
_LX = {
    'uk': {
        'acc_header':         "📱 <b>Акаунти TikTok</b>\n\nСписок акаунтів:",
        'no_accs':            "Жодного акаунту не додано.",
        'btn_cookie':         "➕ Додати через Cookie",
        'btn_login':          "➕ Додати через Логін/Пароль",
        'btn_buy_acc':        "📱 Купити акаунти",
        'btn_buy_proxy':      "🌍 Купити проксі",
        'btn_set_proxy_i':    "🔒 Проксі №{i}",
        'btn_del_acc_i':      "🗑 Видалити №{i}",
        'ask_cookie':         (
            "📋 Надішліть Cookie рядок(и) для TikTok акаунту.\n"
            "Кожен акаунт — з окремого рядка."
        ),
        'ask_login_user':     "👤 Введіть логін (email або username) TikTok акаунту:",
        'ask_login_pass':     "🔑 Введіть пароль TikTok акаунту:",
        'btn_cancel':         "⬅️ Скасувати",
        'checking':           "⏳ Перевіряю акаунт(и)...",
        'login_checking':     "⏳ Спроба входу...",
        'added_ok':           "✅ Додано: {n}",
        'added_fail':         "❌ Не вдалося (перевірте cookie): {n}",
        'login_ok':           "✅ Акаунт <b>{nick}</b> (@{uid}) додано",
        'login_fail':         (
            "❌ Не вдалося увійти. Перевірте логін/пароль або "
            "спробуйте через Cookie."
        ),
        'ask_proxy':          (
            "🌐 Введіть SOCKS5 проксі для акаунту №{i}:\n"
            "<code>socks5://host:port</code>\n"
            "або\n"
            "<code>socks5://user:pass@host:port</code>\n\n"
            "Введіть <b>-</b> щоб видалити поточний проксі."
        ),
        'proxy_set':          "✅ Проксі встановлено для акаунту №{i}",
        'proxy_removed':      "✅ Проксі видалено для акаунту №{i}",
        'proxy_invalid':      "❌ Невірний формат. Введіть socks5://... або - для видалення.",
        'acc_deleted':        "✅ Акаунт №{i} видалено",
        'acc_not_found':      "❌ Акаунт не знайдено",
        'limit_hit':          "⚠️ Досягнуто ліміт у 25 акаунтів",
        'params_header':      "⚙️ <b>Параметри TikTok реклами</b>",
        'params_country':     "🌍 Країна: <b>{v}</b>",
        'params_comment':     "💬 Коментар: <b>{v}</b>",
        'params_replies':     "📝 Відповіді: <b>{v}</b>",
        'params_hashtags':    "🔖 Хештеги: <b>{v}</b>",
        'params_bot':         "🤖 Стан боту: <b>{v}</b>",
        'params_bot_on':      "✅ Активний",
        'params_bot_off':     "❌ Вимкнений",
        'params_none':        "не встановлено",
        'btn_set_country':    "🌍 Вибрати країну",
        'btn_set_comment':    "💬 Встановити коментар",
        'btn_set_replies':    "📝 Встановити відповіді (4)",
        'btn_add_hashtags':   "🔖 Встановити хештеги",
        'btn_clear_hashtags': "🗑 Очистити хештеги",
        'btn_bot_on':         "▶️ Увімкнути бот",
        'btn_bot_off':        "⏹ Вимкнути бот",
        'btn_playwright':     "🎭 Playwright режим",
        'country_title':      "🌍 Виберіть країну:",
        'country_set':        "✅ Країну встановлено: {v}",
        'ask_comment':        "💬 Введіть основний коментар (одне повідомлення):",
        'comment_set':        "✅ Основний коментар встановлено",
        'ask_replies':        (
            "📝 Введіть до 4 відповідей — кожна з <b>нового рядка</b>.\n"
            "(якщо менше 4 — решта буде порожньою)"
        ),
        'replies_set':        "✅ Відповіді встановлено ({n}/4)",
        'ask_hashtags':       "🔖 Введіть хештеги через кому або з нового рядка (без #):",
        'hashtags_set':       "✅ Хештеги встановлено: {v}",
        'hashtags_cleared':   "✅ Хештеги очищено",
        'bot_enabled':        "✅ Бот увімкнено! Починаю моніторинг хештегів...",
        'bot_disabled':       "⏹ Бот вимкнено",
        'bot_need_setup':     "⚠️ Спочатку встановіть коментар та хештеги",
        'bot_no_acc':         "⚠️ Немає активних акаунтів. Додайте або перевірте акаунт.",
        'bot_already_on':     "ℹ️ Бот вже запущено",
    },
    'en': {
        'acc_header':         "📱 <b>TikTok Accounts</b>\n\nAccount list:",
        'no_accs':            "No accounts added.",
        'btn_cookie':         "➕ Add via Cookie",
        'btn_login':          "➕ Add via Login/Password",
        'btn_buy_acc':        "📱 Buy accounts",
        'btn_buy_proxy':      "🌍 Buy proxies",
        'btn_set_proxy_i':    "🔒 Proxy №{i}",
        'btn_del_acc_i':      "🗑 Delete №{i}",
        'ask_cookie':         (
            "📋 Send Cookie string(s) for TikTok account.\n"
            "One account per line."
        ),
        'ask_login_user':     "👤 Enter TikTok login (email or username):",
        'ask_login_pass':     "🔑 Enter TikTok account password:",
        'btn_cancel':         "⬅️ Cancel",
        'checking':           "⏳ Checking account(s)...",
        'login_checking':     "⏳ Attempting login...",
        'added_ok':           "✅ Added: {n}",
        'added_fail':         "❌ Failed (check cookie): {n}",
        'login_ok':           "✅ Account <b>{nick}</b> (@{uid}) added",
        'login_fail':         (
            "❌ Login failed. Check credentials or try via Cookie."
        ),
        'ask_proxy':          (
            "🌐 Enter SOCKS5 proxy for account №{i}:\n"
            "<code>socks5://host:port</code>\n"
            "or\n"
            "<code>socks5://user:pass@host:port</code>\n\n"
            "Enter <b>-</b> to remove current proxy."
        ),
        'proxy_set':          "✅ Proxy set for account №{i}",
        'proxy_removed':      "✅ Proxy removed for account №{i}",
        'proxy_invalid':      "❌ Invalid format. Use socks5://... or - to remove.",
        'acc_deleted':        "✅ Account №{i} deleted",
        'acc_not_found':      "❌ Account not found",
        'limit_hit':          "⚠️ 25 account limit reached",
        'params_header':      "⚙️ <b>TikTok Ad Parameters</b>",
        'params_country':     "🌍 Country: <b>{v}</b>",
        'params_comment':     "💬 Comment: <b>{v}</b>",
        'params_replies':     "📝 Replies: <b>{v}</b>",
        'params_hashtags':    "🔖 Hashtags: <b>{v}</b>",
        'params_bot':         "🤖 Bot status: <b>{v}</b>",
        'params_bot_on':      "✅ Active",
        'params_bot_off':     "❌ Inactive",
        'params_none':        "not set",
        'btn_set_country':    "🌍 Select country",
        'btn_set_comment':    "💬 Set main comment",
        'btn_set_replies':    "📝 Set replies (4)",
        'btn_add_hashtags':   "🔖 Set hashtags",
        'btn_clear_hashtags': "🗑 Clear hashtags",
        'btn_bot_on':         "▶️ Enable bot",
        'btn_bot_off':        "⏹ Disable bot",
        'btn_playwright':     "🎭 Playwright mode",
        'country_title':      "🌍 Select country:",
        'country_set':        "✅ Country set: {v}",
        'ask_comment':        "💬 Enter the main comment (one message):",
        'comment_set':        "✅ Main comment set",
        'ask_replies':        (
            "📝 Enter up to 4 replies — each on a <b>new line</b>.\n"
            "(fewer than 4 is OK — the rest will be empty)"
        ),
        'replies_set':        "✅ Replies set ({n}/4)",
        'ask_hashtags':       "🔖 Enter hashtags separated by comma or new line (without #):",
        'hashtags_set':       "✅ Hashtags set: {v}",
        'hashtags_cleared':   "✅ Hashtags cleared",
        'bot_enabled':        "✅ Bot enabled! Starting hashtag monitoring...",
        'bot_disabled':       "⏹ Bot disabled",
        'bot_need_setup':     "⚠️ Set comment and hashtags first",
        'bot_no_acc':         "⚠️ No active accounts. Add or check an account.",
        'bot_already_on':     "ℹ️ Bot is already running",
    },
    'ru': {
        'acc_header':         "📱 <b>Аккаунты TikTok</b>\n\nСписок аккаунтов:",
        'no_accs':            "Аккаунтов нет.",
        'btn_cookie':         "➕ Добавить через Cookie",
        'btn_login':          "➕ Добавить через Логин/Пароль",
        'btn_buy_acc':        "📱 Купить аккаунты",
        'btn_buy_proxy':      "🌍 Купить прокси",
        'btn_set_proxy_i':    "🔒 Прокси №{i}",
        'btn_del_acc_i':      "🗑 Удалить №{i}",
        'ask_cookie':         (
            "📋 Отправьте Cookie строку(и) для TikTok аккаунта.\n"
            "Каждый аккаунт — с новой строки."
        ),
        'ask_login_user':     "👤 Введите логин (email или username) TikTok:",
        'ask_login_pass':     "🔑 Введите пароль TikTok аккаунта:",
        'btn_cancel':         "⬅️ Отмена",
        'checking':           "⏳ Проверяю аккаунт(ы)...",
        'login_checking':     "⏳ Попытка входа...",
        'added_ok':           "✅ Добавлено: {n}",
        'added_fail':         "❌ Ошибка (проверьте cookie): {n}",
        'login_ok':           "✅ Аккаунт <b>{nick}</b> (@{uid}) добавлен",
        'login_fail':         (
            "❌ Не удалось войти. Проверьте логин/пароль или используйте Cookie."
        ),
        'ask_proxy':          (
            "🌐 Введите SOCKS5 прокси для аккаунта №{i}:\n"
            "<code>socks5://host:port</code>\n"
            "или\n"
            "<code>socks5://user:pass@host:port</code>\n\n"
            "Введите <b>-</b> для удаления прокси."
        ),
        'proxy_set':          "✅ Прокси установлен для аккаунта №{i}",
        'proxy_removed':      "✅ Прокси удалён для аккаунта №{i}",
        'proxy_invalid':      "❌ Неверный формат. Используйте socks5://... или - для удаления.",
        'acc_deleted':        "✅ Аккаунт №{i} удалён",
        'acc_not_found':      "❌ Аккаунт не найден",
        'limit_hit':          "⚠️ Лимит 25 аккаунтов достигнут",
        'params_header':      "⚙️ <b>Параметры TikTok рекламы</b>",
        'params_country':     "🌍 Страна: <b>{v}</b>",
        'params_comment':     "💬 Комментарий: <b>{v}</b>",
        'params_replies':     "📝 Ответы: <b>{v}</b>",
        'params_hashtags':    "🔖 Хэштеги: <b>{v}</b>",
        'params_bot':         "🤖 Статус бота: <b>{v}</b>",
        'params_bot_on':      "✅ Активен",
        'params_bot_off':     "❌ Отключён",
        'params_none':        "не задано",
        'btn_set_country':    "🌍 Выбрать страну",
        'btn_set_comment':    "💬 Установить комментарий",
        'btn_set_replies':    "📝 Установить ответы (4)",
        'btn_add_hashtags':   "🔖 Установить хэштеги",
        'btn_clear_hashtags': "🗑 Очистить хэштеги",
        'btn_bot_on':         "▶️ Включить бот",
        'btn_bot_off':        "⏹ Отключить бот",
        'btn_playwright':     "🎭 Playwright режим",
        'country_title':      "🌍 Выберите страну:",
        'country_set':        "✅ Страна установлена: {v}",
        'ask_comment':        "💬 Введите основной комментарий (одно сообщение):",
        'comment_set':        "✅ Основной комментарий установлен",
        'ask_replies':        (
            "📝 Введите до 4 ответов — каждый с <b>новой строки</b>.\n"
            "(меньше 4 — оставшиеся будут пустыми)"
        ),
        'replies_set':        "✅ Ответы установлены ({n}/4)",
        'ask_hashtags':       "🔖 Введите хэштеги через запятую или новую строку (без #):",
        'hashtags_set':       "✅ Хэштеги установлены: {v}",
        'hashtags_cleared':   "✅ Хэштеги очищены",
        'bot_enabled':        "✅ Бот включён! Начинаю мониторинг хэштегов...",
        'bot_disabled':       "⏹ Бот отключён",
        'bot_need_setup':     "⚠️ Сначала установите комментарий и хэштеги",
        'bot_no_acc':         "⚠️ Нет активных аккаунтов. Добавьте или проверьте аккаунт.",
        'bot_already_on':     "ℹ️ Бот уже запущен",
    },
}

# ─── Translation helpers ──────────────────────────────────────────────────────

def _LT(uid: int, key: str) -> str:
    """Local translation for TikTok-specific texts."""
    try:
        import rukla as _r
        lang = _r.get_user_data(uid).get('lang', 'uk')
    except Exception:
        lang = 'uk'
    texts = _LX.get(lang, _LX['uk'])
    return texts.get(key, _LX['uk'].get(key, key))


def _T(uid: int, key: str) -> str:
    """Proxy to rukla.T for shared keys (b_back, etc.)."""
    try:
        import rukla as _r
        return _r.T(uid, key)
    except Exception:
        return key


# ─── Persistence ─────────────────────────────────────────────────────────────

def _load_accounts():
    global _accounts
    if os.path.exists(TIKTOK_ACCOUNTS_FILE):
        with open(TIKTOK_ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            _accounts = json.load(f)
    else:
        _accounts = {}


def _save_accounts():
    with open(TIKTOK_ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(_accounts, f, ensure_ascii=False, indent=2)


def _load_settings():
    global _settings
    if os.path.exists(TIKTOK_SETTINGS_FILE):
        with open(TIKTOK_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            _settings = json.load(f)
    else:
        _settings = {}


def _save_settings():
    with open(TIKTOK_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(_settings, f, ensure_ascii=False, indent=2)


def _load_commented():
    global _commented
    if os.path.exists(TIKTOK_COMMENTED_FILE):
        with open(TIKTOK_COMMENTED_FILE, 'r', encoding='utf-8') as f:
            _commented = json.load(f)
    else:
        _commented = {}


def _save_commented():
    with open(TIKTOK_COMMENTED_FILE, 'w', encoding='utf-8') as f:
        json.dump(_commented, f, ensure_ascii=False, indent=2)


def _load_all():
    _load_accounts()
    _load_settings()
    _load_commented()


def _get_user_accounts(uid: int) -> list:
    return _accounts.get(str(uid), [])


def _set_user_accounts(uid: int, accounts: list):
    _accounts[str(uid)] = accounts
    _save_accounts()


def _get_user_settings(uid: int) -> dict:
    uid_str = str(uid)
    if uid_str not in _settings:
        _settings[uid_str] = {
            'country': '',
            'main_comment': '',
            'replies': ['', '', '', ''],
            'hashtags': [],
            'bot_active': False,
        }
    return _settings[uid_str]


def _save_user_settings(uid: int):
    _save_settings()


# ─── Pending state helpers ────────────────────────────────────────────────────

def _clear_pending(uid: int):
    """Clear all pending input states for a user."""
    _pending_cookie_input.discard(uid)
    _pending_login_step.pop(uid, None)
    _pending_proxy_input.pop(uid, None)
    _pending_text_input.pop(uid, None)


# ─── TikTok headers ──────────────────────────────────────────────────────────

_TT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Referer': 'https://www.tiktok.com/',
    'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'application/json, text/plain, */*',
}


# ─── TikTok API helpers ───────────────────────────────────────────────────────

def _make_session(cookie_str: str = '', proxy_str: str = '') -> requests.Session:
    """Create a requests.Session with TikTok cookies and optional SOCKS5 proxy."""
    s = requests.Session()
    s.headers.update(_TT_HEADERS)
    if cookie_str:
        for part in cookie_str.split(';'):
            part = part.strip()
            if '=' in part:
                k, v = part.split('=', 1)
                s.cookies.set(k.strip(), v.strip(), domain='.tiktok.com')
    if proxy_str and proxy_str.startswith('socks5://'):
        s.proxies.update({'http': proxy_str, 'https': proxy_str})
    return s


def _get_tt_info(cookie_str: str, proxy_str: str = '') -> tuple:
    """Check TikTok cookie validity. Returns (valid, nickname, unique_id)."""
    try:
        if 'sessionid' not in cookie_str:
            return False, '?', 'unknown'
        s = _make_session(cookie_str, proxy_str)

        # Primary endpoint
        resp = s.get(
            'https://www.tiktok.com/passport/web/account/info/',
            timeout=10,
        )
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get('statusCode') == 0 or data.get('status_code') == 0:
                    user = data.get('data', data.get('user', {}))
                    nickname  = user.get('nickname') or user.get('name') or '?'
                    unique_id = user.get('unique_id') or user.get('uniqueId') or '?'
                    if unique_id != '?':
                        return True, nickname, unique_id
            except Exception:
                pass

        # Fallback endpoint
        resp2 = s.get(
            'https://www.tiktok.com/api/user/detail/',
            params={'uniqueId': '', 'secUid': ''},
            timeout=10,
        )
        if resp2.status_code == 200:
            try:
                d  = resp2.json()
                ui = d.get('userInfo', {}).get('user', {})
                nickname  = ui.get('nickname') or '?'
                unique_id = ui.get('uniqueId') or '?'
                if unique_id != '?':
                    return True, nickname, unique_id
            except Exception:
                pass

        return False, '?', 'unknown'
    except Exception:
        return False, '?', 'unknown'


def _try_tt_login(username: str, password: str) -> tuple:
    """
    Best-effort TikTok login via username/password.
    Returns (success, cookie_str, nickname, unique_id).
    Note: TikTok has heavy bot-detection; this may fail frequently.
    """
    try:
        s = requests.Session()
        s.headers.update(_TT_HEADERS)
        # Seed session cookies
        s.get('https://www.tiktok.com/', timeout=10)

        payload = {
            'username': username,
            'password': password,
            'mix_mode': '1',
            'multi_login': '1',
            'aid': '1988',
        }
        resp = s.post(
            'https://www.tiktok.com/passport/web/user/login/',
            data=payload,
            timeout=15,
        )
        if resp.status_code == 200:
            try:
                data = resp.json()
                # Success indicators vary by TikTok version
                if (
                    data.get('message') == 'success'
                    or data.get('data', {}).get('redirect_url')
                    or data.get('status_code') == 0
                ):
                    cookie_str = '; '.join(
                        f"{c.name}={c.value}" for c in s.cookies
                    )
                    if 'sessionid' in cookie_str:
                        valid, nickname, unique_id = _get_tt_info(cookie_str)
                        if valid:
                            return True, cookie_str, nickname, unique_id
            except Exception:
                pass
        return False, '', '?', 'unknown'
    except Exception:
        return False, '', '?', 'unknown'


def _parse_cookie_dict(cookie_str: str) -> dict:
    result = {}
    for part in cookie_str.split(';'):
        part = part.strip()
        if '=' in part:
            k, v = part.split('=', 1)
            result[k.strip()] = v.strip()
    return result


def _get_hashtag_id(hashtag_clean: str, session: requests.Session) -> str:
    """Fetch TikTok challenge ID for a hashtag name."""
    try:
        resp = session.get(
            'https://www.tiktok.com/api/challenge/detail/',
            params={'challengeName': hashtag_clean},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return (
                data.get('challengeInfo', {})
                    .get('challenge', {})
                    .get('id', '')
            )
    except Exception:
        pass
    return ''


def _fetch_hashtag_videos(
    challenge_id: str,
    cursor: int,
    session: requests.Session,
    count: int = 30,
) -> tuple:
    """
    Fetch video IDs for a TikTok hashtag/challenge.
    Returns (video_ids: list[str], next_cursor: int, has_more: bool).
    """
    try:
        resp = session.get(
            'https://www.tiktok.com/api/challenge/item_list/',
            params={
                'challengeID': challenge_id,
                'count': count,
                'cursor': cursor,
                'type': 5,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data.get('itemList', [])
            video_ids = [
                str(item.get('id') or item.get('aweme_id', ''))
                for item in items
            ]
            video_ids = [v for v in video_ids if v]
            next_cursor = int(data.get('cursor', cursor + len(items)))
            has_more    = bool(data.get('hasMore', False))
            return video_ids, next_cursor, has_more
    except Exception:
        pass
    return [], cursor, False


def _post_comment(
    session: requests.Session,
    video_id: str,
    text: str,
) -> tuple:
    """
    Post a comment on a TikTok video.
    Returns (success: bool, comment_id: str).
    """
    try:
        resp = session.post(
            'https://www.tiktok.com/api/comment/publish/',
            data={
                'aweme_id': video_id,
                'text': text,
                'is_self_see': '0',
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status_code') == 0:
                comment_id = data.get('comment', {}).get('cid', '')
                return True, comment_id
    except Exception:
        pass
    return False, ''


def _reply_to_comment(
    session: requests.Session,
    video_id: str,
    comment_id: str,
    text: str,
) -> bool:
    """
    Reply to a TikTok comment. Returns success bool.
    """
    try:
        resp = session.post(
            'https://www.tiktok.com/api/comment/publish/',
            data={
                'aweme_id': video_id,
                'text': text,
                'reply_id': comment_id,
                'is_self_see': '0',
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get('status_code') == 0
    except Exception:
        pass
    return False


# ─── Background worker ────────────────────────────────────────────────────────

def _get_active_account(uid: int) -> dict | None:
    """Return first active account for this user, or None."""
    for acc in _accounts.get(str(uid), []):
        if acc.get('active', False):
            return acc
    return None


def _bg_worker(bot, uid: int, stop_evt: threading.Event):
    """
    Background thread: monitors hashtags and posts comments + replies.
    - First pass: comments on ALL existing videos.
    - Subsequent passes (every 10 min): only new videos.
    """
    uid_str    = str(uid)
    first_run  = True

    while not stop_evt.is_set():
        try:
            _load_all()
            settings = _get_user_settings(uid)
            hashtags     = settings.get('hashtags', [])
            main_comment = settings.get('main_comment', '')
            replies      = settings.get('replies', ['', '', '', ''])

            if not hashtags or not main_comment:
                stop_evt.wait(300)
                first_run = False
                continue

            acc = _get_active_account(uid)
            if not acc:
                stop_evt.wait(120)
                first_run = False
                continue

            cookie_str = acc.get('cookie', '')
            proxy_str  = acc.get('proxy', '')
            session    = _make_session(cookie_str, proxy_str)

            if uid_str not in _commented:
                _commented[uid_str] = {}

            for hashtag in hashtags:
                if stop_evt.is_set():
                    break
                ht_clean = hashtag.lstrip('#').strip()
                if not ht_clean:
                    continue

                try:
                    challenge_id = _get_hashtag_id(ht_clean, session)
                    if not challenge_id:
                        continue

                    commented_for_tag = _commented[uid_str].get(ht_clean, [])
                    cursor   = 0
                    has_more = True

                    while not stop_evt.is_set() and has_more:
                        video_ids, next_cursor, has_more = _fetch_hashtag_videos(
                            challenge_id, cursor, session
                        )
                        for vid in video_ids:
                            if stop_evt.is_set():
                                break
                            if vid in commented_for_tag:
                                # Already commented — skip on non-first run
                                if not first_run:
                                    continue
                                else:
                                    continue  # skip on first run too

                            # Post main comment
                            ok, cid = _post_comment(session, vid, main_comment)
                            if ok:
                                commented_for_tag.append(vid)
                                # Post replies
                                for reply_text in replies:
                                    if stop_evt.is_set():
                                        break
                                    if reply_text and reply_text.strip():
                                        _reply_to_comment(session, vid, cid, reply_text)
                                        stop_evt.wait(2)  # polite delay
                                stop_evt.wait(5)  # delay between videos
                            else:
                                stop_evt.wait(3)

                        _commented[uid_str][ht_clean] = commented_for_tag
                        _save_commented()

                        # On subsequent runs only scan first page
                        if not first_run:
                            break
                        cursor = next_cursor

                except Exception:
                    pass  # Continue to next hashtag on error

        except Exception:
            pass

        first_run = False
        # Wait 10 minutes before next scan (approximates "new video detection")
        stop_evt.wait(600)

    # Worker exited — mark bot as inactive
    try:
        _load_settings()
        s = _get_user_settings(uid)
        s['bot_active'] = False
        _save_settings()
    except Exception:
        pass


def _start_worker(bot, uid: int):
    """Start background worker for a user (stops existing one first)."""
    _stop_worker(uid)
    evt = threading.Event()
    _bg_stop[uid]   = evt
    t = threading.Thread(target=_bg_worker, args=(bot, uid, evt), daemon=True)
    _bg_thread[uid] = t
    t.start()


def _stop_worker(uid: int):
    """Stop background worker for a user."""
    if uid in _bg_stop:
        _bg_stop[uid].set()
        if uid in _bg_thread:
            _bg_thread[uid].join(timeout=5)
        _bg_stop.pop(uid, None)
        _bg_thread.pop(uid, None)


# ─── Menu builders — accounts ─────────────────────────────────────────────────

def _build_acc_line(acc: dict, idx: int) -> str:
    nick      = acc.get('nickname', '?')
    unique_id = acc.get('unique_id', 'unknown')
    status    = "✅" if acc.get('active', False) else "❌"
    proxy_ico = " 🔒" if acc.get('proxy', '') else ""
    return f"№{idx} {nick} — @{unique_id} {status}{proxy_ico}"


def _build_accounts_text(uid: int) -> str:
    accounts = _get_user_accounts(uid)
    header   = _LT(uid, 'acc_header')
    if not accounts:
        return header + "\n\n" + _LT(uid, 'no_accs')
    lines = [header]
    for i, acc in enumerate(accounts, 1):
        lines.append(_build_acc_line(acc, i))
    return "\n".join(lines)


def _acc_markup(uid: int) -> types.InlineKeyboardMarkup:
    markup   = types.InlineKeyboardMarkup(row_width=2)
    accounts = _get_user_accounts(uid)

    # Add / login buttons (side-by-side)
    markup.row(
        types.InlineKeyboardButton(_LT(uid, 'btn_cookie'), callback_data="tiktok_add_cookie"),
        types.InlineKeyboardButton(_LT(uid, 'btn_login'),  callback_data="tiktok_add_login"),
    )

    # Per-account management rows: [🔒 №i] [🗑 №i]
    for i in range(1, len(accounts) + 1):
        markup.row(
            types.InlineKeyboardButton(
                _LT(uid, 'btn_set_proxy_i').format(i=i),
                callback_data=f"tiktok_set_proxy_{i - 1}",
            ),
            types.InlineKeyboardButton(
                _LT(uid, 'btn_del_acc_i').format(i=i),
                callback_data=f"tiktok_del_acc_{i - 1}",
            ),
        )

    # Buy buttons
    markup.add(
        types.InlineKeyboardButton(_LT(uid, 'btn_buy_acc'),   callback_data="r7_buy_acc_tiktok"),
        types.InlineKeyboardButton(_LT(uid, 'btn_buy_proxy'), callback_data="r7_buy_proxy_tiktok"),
    )
    markup.add(types.InlineKeyboardButton(_T(uid, 'b_back'), callback_data="m_manage_tiktok"))
    return markup


def open_tiktok_menu(bot, uid: int, message_id: int):
    _load_accounts()
    text = _build_accounts_text(uid)
    try:
        bot.edit_message_text(
            text, uid, message_id,
            reply_markup=_acc_markup(uid),
            parse_mode='HTML',
        )
    except Exception:
        bot.send_message(uid, text, reply_markup=_acc_markup(uid), parse_mode='HTML')


# ─── Menu builders — params ───────────────────────────────────────────────────

def _build_params_text(uid: int) -> str:
    s        = _get_user_settings(uid)
    none_str = _LT(uid, 'params_none')

    country = s.get('country') or none_str

    mc = s.get('main_comment') or none_str
    if len(mc) > 35 and mc != none_str:
        mc = mc[:35] + '…'

    replies      = s.get('replies', [])
    non_empty    = [r for r in replies if r and r.strip()]
    replies_str  = f"{len(non_empty)}/4" if non_empty else none_str

    hashtags     = s.get('hashtags', [])
    hashtags_str = ', '.join(f"#{h}" for h in hashtags) if hashtags else none_str
    if len(hashtags_str) > 60 and hashtags:
        hashtags_str = hashtags_str[:60] + '…'

    bot_active = s.get('bot_active', False)
    bot_str    = _LT(uid, 'params_bot_on') if bot_active else _LT(uid, 'params_bot_off')

    return "\n".join([
        _LT(uid, 'params_header'),
        "",
        _LT(uid, 'params_country').format(v=country),
        _LT(uid, 'params_comment').format(v=mc),
        _LT(uid, 'params_replies').format(v=replies_str),
        _LT(uid, 'params_hashtags').format(v=hashtags_str),
        _LT(uid, 'params_bot').format(v=bot_str),
    ])


def _params_markup(uid: int) -> types.InlineKeyboardMarkup:
    s          = _get_user_settings(uid)
    bot_active = s.get('bot_active', False)
    markup     = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(_LT(uid, 'btn_set_country'),  callback_data="tiktok_set_country"),
        types.InlineKeyboardButton(_LT(uid, 'btn_set_comment'),  callback_data="tiktok_set_comment"),
        types.InlineKeyboardButton(_LT(uid, 'btn_set_replies'),  callback_data="tiktok_set_replies"),
        types.InlineKeyboardButton(_LT(uid, 'btn_add_hashtags'), callback_data="tiktok_add_hashtags"),
    )
    if s.get('hashtags'):
        markup.add(
            types.InlineKeyboardButton(
                _LT(uid, 'btn_clear_hashtags'), callback_data="tiktok_clear_hashtags"
            )
        )
    bot_btn_key = 'btn_bot_off' if bot_active else 'btn_bot_on'
    markup.add(
        types.InlineKeyboardButton(_LT(uid, bot_btn_key), callback_data="tiktok_toggle_bot")
    )
    markup.add(
        types.InlineKeyboardButton(_LT(uid, 'btn_playwright'), callback_data="tiktok_pw_panel")
    )
    markup.add(types.InlineKeyboardButton(_T(uid, 'b_back'), callback_data="m_manage_tiktok"))
    return markup


def open_params_menu(bot, uid: int, message_id: int):
    _load_settings()
    text = _build_params_text(uid)
    try:
        bot.edit_message_text(
            text, uid, message_id,
            reply_markup=_params_markup(uid),
            parse_mode='HTML',
        )
    except Exception:
        bot.send_message(uid, text, reply_markup=_params_markup(uid), parse_mode='HTML')


# ─── Country markup ───────────────────────────────────────────────────────────

def _country_markup(uid: int) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=3)
    btns   = [
        types.InlineKeyboardButton(c, callback_data=f"tiktok_country_{i}")
        for i, c in enumerate(COUNTRIES)
    ]
    markup.add(*btns)
    markup.add(types.InlineKeyboardButton(_T(uid, 'b_back'), callback_data="tiktok_params_back"))
    return markup


# ─── Cancel markup ────────────────────────────────────────────────────────────

def _cancel_markup(uid: int, cancel_data: str) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(_LT(uid, 'btn_cancel'), callback_data=cancel_data))
    return markup


# ─── Callback registration ────────────────────────────────────────────────────

def register_callbacks(bot):
    global _bot_ref
    _bot_ref = bot

    # Load state and restart any active workers
    _load_all()
    for uid_str, s in _settings.items():
        if s.get('bot_active', False):
            try:
                _start_worker(bot, int(uid_str))
            except Exception:
                pass

    # ── Cookie add ────────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_add_cookie')
    def tiktok_ask_cookie(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending_cookie_input.add(uid)
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            _LT(uid, 'ask_cookie'),
            reply_markup=_cancel_markup(uid, 'tiktok_cancel_add'),
        )

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_cancel_add')
    def tiktok_cancel_cookie(call):
        uid = call.message.chat.id
        _pending_cookie_input.discard(uid)
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(uid, call.message.message_id)
        except Exception:
            pass

    @bot.message_handler(
        func=lambda msg: msg.chat.id in _pending_cookie_input,
        content_types=['text'],
    )
    def tiktok_receive_cookie(message):
        uid = message.chat.id
        _pending_cookie_input.discard(uid)
        _load_accounts()
        accounts    = _get_user_accounts(uid)
        cookie_lines = [
            ln.strip()
            for ln in message.text.strip().splitlines()
            if ln.strip()
        ]

        wait_msg = bot.send_message(uid, _LT(uid, 'checking'))
        added = failed = 0
        limit_hit = False

        for cookie in cookie_lines:
            if len(accounts) >= 25:
                limit_hit = True
                break
            valid, nickname, unique_id = _get_tt_info(cookie)
            accounts.append({
                'cookie':    cookie,
                'active':    valid,
                'nickname':  nickname,
                'unique_id': unique_id,
                'proxy':     '',
            })
            if valid:
                added += 1
            else:
                failed += 1

        _set_user_accounts(uid, accounts)
        try:
            bot.delete_message(uid, wait_msg.message_id)
        except Exception:
            pass

        if limit_hit:
            bot.send_message(uid, _LT(uid, 'limit_hit'))

        lines = []
        if added:
            lines.append(_LT(uid, 'added_ok').format(n=added))
        if failed:
            lines.append(_LT(uid, 'added_fail').format(n=failed))
        if lines:
            bot.send_message(uid, "\n".join(lines))

        text = _build_accounts_text(uid)
        bot.send_message(uid, text, reply_markup=_acc_markup(uid), parse_mode='HTML')

    # ── Login/Password add ────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_add_login')
    def tiktok_ask_login(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending_login_step[uid] = {'step': 'user'}
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            _LT(uid, 'ask_login_user'),
            reply_markup=_cancel_markup(uid, 'tiktok_cancel_login'),
        )

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_cancel_login')
    def tiktok_cancel_login(call):
        uid = call.message.chat.id
        _pending_login_step.pop(uid, None)
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(uid, call.message.message_id)
        except Exception:
            pass

    @bot.message_handler(
        func=lambda msg: msg.chat.id in _pending_login_step,
        content_types=['text'],
    )
    def tiktok_receive_login(message):
        uid       = message.chat.id
        step_data = _pending_login_step.get(uid, {})
        step      = step_data.get('step', 'user')

        if step == 'user':
            username = message.text.strip()
            _pending_login_step[uid] = {'step': 'pass', 'username': username}
            bot.send_message(
                uid,
                _LT(uid, 'ask_login_pass'),
                reply_markup=_cancel_markup(uid, 'tiktok_cancel_login'),
            )

        elif step == 'pass':
            username = step_data.get('username', '')
            password = message.text.strip()
            _pending_login_step.pop(uid, None)

            wait_msg = bot.send_message(uid, _LT(uid, 'login_checking'))
            ok, cookie_str, nickname, unique_id = _try_tt_login(username, password)

            try:
                bot.delete_message(uid, wait_msg.message_id)
            except Exception:
                pass

            _load_accounts()
            accounts = _get_user_accounts(uid)

            if ok:
                if len(accounts) >= 25:
                    bot.send_message(uid, _LT(uid, 'limit_hit'))
                else:
                    accounts.append({
                        'cookie':    cookie_str,
                        'active':    True,
                        'nickname':  nickname,
                        'unique_id': unique_id,
                        'proxy':     '',
                    })
                    _set_user_accounts(uid, accounts)
                    bot.send_message(
                        uid,
                        _LT(uid, 'login_ok').format(nick=nickname, uid=unique_id),
                        parse_mode='HTML',
                    )
            else:
                bot.send_message(uid, _LT(uid, 'login_fail'))

            text = _build_accounts_text(uid)
            bot.send_message(uid, text, reply_markup=_acc_markup(uid), parse_mode='HTML')

    # ── Proxy management ──────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data.startswith('tiktok_set_proxy_'))
    def tiktok_ask_proxy(call):
        uid = call.message.chat.id
        try:
            idx = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id)
            return
        _clear_pending(uid)
        _pending_proxy_input[uid] = idx
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            _LT(uid, 'ask_proxy').format(i=idx + 1),
            reply_markup=_cancel_markup(uid, 'tiktok_proxy_cancel'),
            parse_mode='HTML',
        )

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_proxy_cancel')
    def tiktok_proxy_cancel(call):
        uid = call.message.chat.id
        _pending_proxy_input.pop(uid, None)
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(uid, call.message.message_id)
        except Exception:
            pass

    @bot.message_handler(
        func=lambda msg: msg.chat.id in _pending_proxy_input,
        content_types=['text'],
    )
    def tiktok_receive_proxy(message):
        uid  = message.chat.id
        idx  = _pending_proxy_input.pop(uid, None)
        text = message.text.strip()

        _load_accounts()
        accounts = _get_user_accounts(uid)
        if idx is None or idx >= len(accounts):
            bot.send_message(uid, _LT(uid, 'acc_not_found'))
            return

        if text == '-':
            accounts[idx]['proxy'] = ''
            _set_user_accounts(uid, accounts)
            bot.send_message(uid, _LT(uid, 'proxy_removed').format(i=idx + 1))
        elif text.startswith('socks5://'):
            accounts[idx]['proxy'] = text
            _set_user_accounts(uid, accounts)
            bot.send_message(uid, _LT(uid, 'proxy_set').format(i=idx + 1))
        else:
            bot.send_message(uid, _LT(uid, 'proxy_invalid'))
            return

        acc_text = _build_accounts_text(uid)
        bot.send_message(uid, acc_text, reply_markup=_acc_markup(uid), parse_mode='HTML')

    # ── Delete account ────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data.startswith('tiktok_del_acc_'))
    def tiktok_delete_account(call):
        uid = call.message.chat.id
        try:
            idx = int(call.data.split('_')[-1])
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id)
            return
        bot.answer_callback_query(call.id)
        _load_accounts()
        accounts = _get_user_accounts(uid)
        if idx >= len(accounts):
            bot.send_message(uid, _LT(uid, 'acc_not_found'))
            return
        accounts.pop(idx)
        _set_user_accounts(uid, accounts)
        bot.send_message(uid, _LT(uid, 'acc_deleted').format(i=idx + 1))
        text = _build_accounts_text(uid)
        try:
            bot.edit_message_text(
                text, uid, call.message.message_id,
                reply_markup=_acc_markup(uid),
                parse_mode='HTML',
            )
        except Exception:
            bot.send_message(uid, text, reply_markup=_acc_markup(uid), parse_mode='HTML')

    # ── Proxy purchase (TikTok) ───────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == 'r7_buy_proxy_tiktok')
    def tiktok_buy_proxy(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        # Delegate to rukla7 if available, else show in-dev message
        try:
            import rukla7
            # rukla7 doesn't have a dedicated proxy_tiktok handler yet;
            # fall through to message
            raise AttributeError("no proxy handler")
        except Exception:
            pass
        try:
            import rukla as _r
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(_T(uid, 'b_back'), callback_data="m_tiktok_accounts"))
            bot.edit_message_text(
                _r.T(uid, 'r6_in_dev'), uid, call.message.message_id, reply_markup=markup
            )
        except Exception:
            pass

    # ── Country selection ─────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_set_country')
    def tiktok_show_countries(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(
                _LT(uid, 'country_title'), uid, call.message.message_id,
                reply_markup=_country_markup(uid),
            )
        except Exception:
            bot.send_message(uid, _LT(uid, 'country_title'), reply_markup=_country_markup(uid))

    @bot.callback_query_handler(func=lambda c: c.data.startswith('tiktok_country_'))
    def tiktok_select_country(call):
        uid = call.message.chat.id
        try:
            idx = int(call.data.split('_')[-1])
            country = COUNTRIES[idx]
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id)
            return
        _load_settings()
        s = _get_user_settings(uid)
        s['country'] = country
        _save_settings()
        bot.answer_callback_query(call.id, _LT(uid, 'country_set').format(v=country))
        # Return to params menu
        text = _build_params_text(uid)
        try:
            bot.edit_message_text(
                text, uid, call.message.message_id,
                reply_markup=_params_markup(uid),
                parse_mode='HTML',
            )
        except Exception:
            bot.send_message(uid, text, reply_markup=_params_markup(uid), parse_mode='HTML')

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_params_back')
    def tiktok_params_back(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        _load_settings()
        text = _build_params_text(uid)
        try:
            bot.edit_message_text(
                text, uid, call.message.message_id,
                reply_markup=_params_markup(uid),
                parse_mode='HTML',
            )
        except Exception:
            bot.send_message(uid, text, reply_markup=_params_markup(uid), parse_mode='HTML')

    # ── Text input: comment / replies / hashtags ──────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_set_comment')
    def tiktok_ask_comment(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending_text_input[uid] = 'comment'
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            _LT(uid, 'ask_comment'),
            reply_markup=_cancel_markup(uid, 'tiktok_text_cancel'),
        )

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_set_replies')
    def tiktok_ask_replies(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending_text_input[uid] = 'replies'
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            _LT(uid, 'ask_replies'),
            reply_markup=_cancel_markup(uid, 'tiktok_text_cancel'),
            parse_mode='HTML',
        )

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_add_hashtags')
    def tiktok_ask_hashtags(call):
        uid = call.message.chat.id
        _clear_pending(uid)
        _pending_text_input[uid] = 'hashtags'
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            _LT(uid, 'ask_hashtags'),
            reply_markup=_cancel_markup(uid, 'tiktok_text_cancel'),
        )

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_text_cancel')
    def tiktok_text_cancel(call):
        uid = call.message.chat.id
        _pending_text_input.pop(uid, None)
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(uid, call.message.message_id)
        except Exception:
            pass

    @bot.message_handler(
        func=lambda msg: msg.chat.id in _pending_text_input,
        content_types=['text'],
    )
    def tiktok_receive_text(message):
        uid     = message.chat.id
        key     = _pending_text_input.pop(uid, None)
        raw     = message.text.strip()

        _load_settings()
        s = _get_user_settings(uid)

        confirm = ''
        if key == 'comment':
            s['main_comment'] = raw
            confirm = _LT(uid, 'comment_set')

        elif key == 'replies':
            lines   = [ln.strip() for ln in raw.splitlines()]
            # Pad / trim to exactly 4 slots
            replies = (lines + ['', '', '', ''])[:4]
            s['replies'] = replies
            n       = len([r for r in replies if r])
            confirm = _LT(uid, 'replies_set').format(n=n)

        elif key == 'hashtags':
            # Accept comma-separated or newline-separated, strip '#'
            raw_tags = re.split(r'[,\n]+', raw)
            tags     = [t.strip().lstrip('#') for t in raw_tags if t.strip()]
            s['hashtags'] = tags
            displayed = ', '.join(f"#{t}" for t in tags)
            confirm   = _LT(uid, 'hashtags_set').format(v=displayed)

        _save_settings()
        if confirm:
            bot.send_message(uid, confirm)

        # Show updated params menu
        text = _build_params_text(uid)
        bot.send_message(uid, text, reply_markup=_params_markup(uid), parse_mode='HTML')

    # ── Clear hashtags ────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_clear_hashtags')
    def tiktok_clear_hashtags(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        _load_settings()
        s = _get_user_settings(uid)
        s['hashtags'] = []
        _save_settings()
        # Also stop worker if running (no hashtags = nothing to do)
        if uid in _bg_stop:
            _stop_worker(uid)
            s['bot_active'] = False
            _save_settings()
        text = _build_params_text(uid)
        try:
            bot.edit_message_text(
                text, uid, call.message.message_id,
                reply_markup=_params_markup(uid),
                parse_mode='HTML',
            )
        except Exception:
            bot.send_message(uid, text, reply_markup=_params_markup(uid), parse_mode='HTML')

    # ── Bot toggle ────────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: c.data == 'tiktok_toggle_bot')
    def tiktok_toggle_bot(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        _load_settings()
        _load_accounts()
        s = _get_user_settings(uid)
        currently_active = s.get('bot_active', False)

        if currently_active:
            # Disable
            _stop_worker(uid)
            s['bot_active'] = False
            _save_settings()
            bot.send_message(uid, _LT(uid, 'bot_disabled'))
        else:
            # Validate requirements before enabling
            if not s.get('main_comment', ''):
                bot.send_message(uid, _LT(uid, 'bot_need_setup'))
                return
            if not s.get('hashtags'):
                bot.send_message(uid, _LT(uid, 'bot_need_setup'))
                return
            if not _get_active_account(uid):
                bot.send_message(uid, _LT(uid, 'bot_no_acc'))
                return

            s['bot_active'] = True
            _save_settings()
            _start_worker(bot, uid)
            bot.send_message(uid, _LT(uid, 'bot_enabled'))

        text = _build_params_text(uid)
        try:
            bot.edit_message_text(
                text, uid, call.message.message_id,
                reply_markup=_params_markup(uid),
                parse_mode='HTML',
            )
        except Exception:
            bot.send_message(uid, text, reply_markup=_params_markup(uid), parse_mode='HTML')
