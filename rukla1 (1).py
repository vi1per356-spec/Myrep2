import os, re, asyncio, zipfile, random, shutil, sqlite3, time, itertools, json, threading
from collections import defaultdict
from telethon import TelegramClient, events, Button
from telethon.tl.types import (ReactionEmoji, InputPhoneContact,
                               Channel, Chat)
from telethon.tl.functions.messages import (SendReactionRequest,
                                            GetDiscussionMessageRequest,
                                            DeleteHistoryRequest,
                                            ImportChatInviteRequest)
from telethon.tl.functions.channels import (JoinChannelRequest,
                                            GetFullChannelRequest,
                                            LeaveChannelRequest,
                                            CreateChannelRequest,
                                            EditPhotoRequest,
                                            UpdateUsernameRequest)
from telethon.tl.functions.photos import (DeletePhotosRequest,
                                          GetUserPhotosRequest,
                                          UploadProfilePhotoRequest)
from telethon.tl.functions.account import (UpdateProfileRequest,
                                           UpdateUsernameRequest as _AccUpdUsername)
from telethon.tl.functions.contacts import ImportContactsRequest, SearchRequest
from telethon.tl.functions.chatlists import (CheckChatlistInviteRequest,
                                             JoinChatlistInviteRequest)
from telethon.errors import SessionPasswordNeededError, AuthKeyDuplicatedError
import google.generativeai as genai
import aiohttp
from urllib.parse import quote

def _T(uid: int, key: str) -> str:
    try:
        import rukla as _r
        return _r.T(uid, key)
    except Exception:
        return key


def can_write(path: str) -> bool:
    try:
        with open(path, 'a'):
            pass
        return True
    except OSError:
        return False

try:
    import socks as _socks_module
    SOCKS5_AVAILABLE = True
except ImportError:
    _socks_module = None
    SOCKS5_AVAILABLE = False

API_ID = 6
API_HASH = "eb06d4abfb49dc3eeb1aeb98ae0f581e"
GEMINI_API_KEY = "AIzaSyAT4T8N_FwMM3eAcjfIFB0a8xkSaAQQv3w"
_genai_ready = False
def _ensure_genai():
    global _genai_ready
    if not _genai_ready:
        genai.configure(api_key=GEMINI_API_KEY)
        _genai_ready = True

ADMIN_ID = 6326560451
PASSWORD = "sh$(4291y+)$_&hsb??!"

USERS_DATA_DIR = "users_data"
os.makedirs(USERS_DATA_DIR, exist_ok=True)

# ================= КОНТЕКСТ КОРИСТУВАЧА =================
class UserContext:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.userbots = []
        self.active_commenter_idx = 0
        self.url_proxies = []
        self.group_proxies = []
        self.processed_posts = set()
        self.latest_channel_posts = {}
        self.auth_sessions = {}
        self.user_states = {}
        self.messages_to_delete = defaultdict(list)
        self.nav_msg_id: dict = {}
        self.bot_settings = {
            "keywords": [],
            "rules_text": "Напиши щось позитивне і згодься з автором поста.",
            "channels": {},
            "styles": {},
            "reminders": {},
            "reminder_delay": 60,
            "cycle_delay": 0,
            "bot_enabled": True,
            "private_reply": ""
        }
        self.group_userbots = []
        self.group_auth_sessions = {}
        self.group_bot_settings = {
            "bot_enabled": True,
            "name_pool": [],
            "avatar_pool": [],
            "monitoring_channel": None,
            "monitoring_channel_id": None,
            "monitoring_country": "Україна",
            "monitoring_active": False,
            "group_chats": [],
            "repost_interval": 180,
            "repost_repeat": 5,
        }
        self._monitoring_handlers_registered = set()
        self._last_monitoring_msg_id = 0
        self._processed_monitoring_msgs: set = set()
        self._sessions_dir = os.path.join(USERS_DATA_DIR, str(user_id), "sessions")
        self._group_sessions_dir = os.path.join(USERS_DATA_DIR, str(user_id), "group_sessions")
        os.makedirs(self._sessions_dir, exist_ok=True)
        os.makedirs(self._group_sessions_dir, exist_ok=True)

    async def clear_chat(self, chat_id):
        for msg_id in list(self.messages_to_delete.get(chat_id, [])):
            try:
                await bot.delete_messages(chat_id, msg_id)
            except:
                pass
        self.messages_to_delete[chat_id] = []

    async def send_and_track(self, chat_id, text, buttons=None):
        msg = await bot.send_message(chat_id, text, buttons=buttons)
        self.messages_to_delete[chat_id].append(msg.id)
        return msg

    async def show_nav(self, chat_id, text, buttons=None):
        """Edit the persistent navigation message in-place; send fresh if needed."""
        for msg_id in list(self.messages_to_delete.get(chat_id, [])):
            try:
                await bot.delete_messages(chat_id, msg_id)
            except:
                pass
        self.messages_to_delete[chat_id] = []

        nav_id = self.nav_msg_id.get(chat_id)
        if nav_id:
            try:
                await bot.edit_message(chat_id, nav_id, text, buttons=buttons)
                return
            except Exception as e:
                if "not modified" in str(e).lower():
                    return  # Content already correct, nothing to do
                self.nav_msg_id.pop(chat_id, None)  # Stale message — fall through to send new

        msg = await bot.send_message(chat_id, text, buttons=buttons)
        self.nav_msg_id[chat_id] = msg.id

# Глобальні змінні
user_contexts: dict[int, UserContext] = {}
authenticated_users: set[int] = set()

def get_ctx(user_id: int) -> UserContext:
    if user_id not in user_contexts:
        user_contexts[user_id] = UserContext(user_id)
    return user_contexts[user_id]

# ================= ГЕОГРАФІЯ УКРАЇНИ =================
UA_REGIONS = {
    "Київська":          ["Київ","Бориспіль","Бровари","Біла Церква","Фастів","Васильків",
                          "Обухів","Переяслав","Вишневе","Ірпінь","Буча","Гостомель","Вишгород",
                          "Боярка","Бровари","Славутич","Узин","Тараща","Ржищів"],
    "Харківська":        ["Харків","Ізюм","Лозова","Куп'янськ","Чугуїв","Балаклія",
                          "Первомайський","Богодухів","Зміїв","Вовчанськ","Люботин"],
    "Дніпропетровська":  ["Дніпро","Кривий Ріг","Кам'янське","Нікополь","Павлоград",
                          "Жовті Води","Новомосковськ","Кривий Ріг","Верхньодніпровськ","Марганець"],
    "Одеська":           ["Одеса","Ізмаїл","Чорноморськ","Южне","Білгород-Дністровський",
                          "Котовськ","Теплодар","Арциз","Болград","Рені"],
    "Донецька":          ["Маріуполь","Краматорськ","Слов'янськ","Бахмут","Костянтинівка",
                          "Дружківка","Покровськ","Авдіївка","Торецьк","Лиман"],
    "Запорізька":        ["Запоріжжя","Мелітополь","Бердянськ","Енергодар","Токмак",
                          "Пологи","Гуляйполе","Василівка"],
    "Львівська":         ["Львів","Дрогобич","Стрий","Червоноград","Трускавець",
                          "Самбір","Борислав","Новий Розділ","Моршин","Броди"],
    "Вінницька":         ["Вінниця","Жмеринка","Могилів-Подільський","Хмільник",
                          "Козятин","Бар","Ладижин","Тульчин","Гайсин"],
    "Полтавська":        ["Полтава","Кременчук","Лубни","Миргород","Комсомольськ",
                          "Гадяч","Зіньків","Пирятин","Хорол","Карлівка"],
    "Черкаська":         ["Черкаси","Умань","Сміла","Золотоноша","Канів",
                          "Шпола","Корсунь-Шевченківський","Христинівка","Тальне"],
    "Сумська":           ["Суми","Конотоп","Шостка","Ромни","Охтирка",
                          "Глухів","Лебедин","Тростянець","Середина-Буда"],
    "Чернігівська":      ["Чернігів","Ніжин","Прилуки","Бахмач","Новгород-Сіверський",
                          "Корюківка","Ічня","Борзна","Носівка"],
    "Житомирська":       ["Житомир","Бердичів","Коростень","Новоград-Волинський",
                          "Малин","Баранівка","Коростишів","Радомишль"],
    "Рівненська":        ["Рівне","Дубно","Острог","Здолбунів","Костопіль",
                          "Корець","Рокитне","Сарни","Березне"],
    "Волинська":         ["Луцьк","Ковель","Нововолинськ","Володимир","Ківерці",
                          "Камінь-Каширський","Любомль","Турійськ"],
    "Хмельницька":       ["Хмельницький","Кам'янець-Подільський","Шепетівка",
                          "Нетішин","Красилів","Славута","Старокостянтинів","Дунаєвці"],
    "Тернопільська":     ["Тернопіль","Кременець","Чортків","Борщів",
                          "Збараж","Бережани","Теребовля","Підволочиськ"],
    "Івано-Франківська": ["Івано-Франківськ","Калуш","Коломия","Надвірна",
                          "Болехів","Долина","Яремче","Снятин","Косів"],
    "Чернівецька":       ["Чернівці","Новодністровськ","Сторожинець","Хотин",
                          "Заставна","Кіцмань","Вижниця"],
    "Кіровоградська":    ["Кропивницький","Олександрія","Знам'янка","Світловодськ",
                          "Гайворон","Новоукраїнка","Добровеличківка"],
    "Миколаївська":      ["Миколаїв","Вознесенськ","Первомайськ","Южноукраїнськ",
                          "Баштанка","Снігурівка","Очаків","Нова Одеса"],
    "Херсонська":        ["Херсон","Нова Каховка","Скадовськ","Генічеськ",
                          "Цюрупинськ","Каховка","Берислав","Таврійськ"],
    "Закарпатська":      ["Ужгород","Мукачево","Хуст","Берегово",
                          "Виноградів","Рахів","Тячів","Свалява","Перечин"],
    "Запорізька":        ["Запоріжжя","Мелітополь","Бердянськ","Енергодар"],
    "Луганська":         ["Сєвєродонецьк","Лисичанськ","Рубіжне","Старобільськ",
                          "Попасна","Кремінна","Щастя","Брянка"],
}
UA_CITY_TO_REGION = {}
for _oblast, _cities in UA_REGIONS.items():
    for _city in _cities:
        UA_CITY_TO_REGION[_city.lower()] = _oblast

# ============================================================
# DUMMY MASTER BOT
# Замість Telethon TelegramClient на BOT_TOKEN — заглушка, яка
# проксі-методи направляє в telebot (rukla.py). Тому конфлікту
# за токен немає: один токен = один telebot-клієнт.
# ============================================================
class _DummyMasterBot:
    """Емулює інтерфейс Telethon TelegramClient що використовує rukla1."""
    def __init__(self):
        self._handlers = []   # (callback, event) — для list_event_handlers
        self._tb = None       # telebot bot, виставляється через register_callbacks
        self._connected = True

    def _set_telebot(self, tb):
        self._tb = tb

    # ----- Telethon API, що використовується кодом rukla1 -----
    def on(self, event):
        """Декоратор @bot.on(events.X) — реєструє хендлер. Ніколи не запускається."""
        def deco(callback):
            self._handlers.append((callback, event))
            return callback
        return deco

    def add_event_handler(self, callback, event=None):
        self._handlers.append((callback, event))

    def remove_event_handler(self, callback, event=None):
        self._handlers = [(c, e) for c, e in self._handlers if c is not callback]

    def list_event_handlers(self):
        return list(self._handlers)

    async def start(self, **kwargs):
        return self

    async def connect(self):
        return

    async def disconnect(self):
        return

    def is_connected(self):
        return self._connected

    async def run_until_disconnected(self):
        while True:
            await asyncio.sleep(3600)

    # ----- Перенаправлення повідомлень у telebot -----
    async def send_message(self, entity, message, buttons=None, **kwargs):
        """rukla1 викликає це з send_and_track. Перенаправляємо в telebot."""
        if self._tb is None:
            print(f"[dummy_bot.send_message] no telebot bound; entity={entity}")
            return _FakeMsg(0)
        markup = _telethon_buttons_to_telebot(buttons)
        try:
            sent = self._tb.send_message(entity, message, reply_markup=markup)
            return _FakeMsg(sent.message_id)
        except Exception as e:
            print(f"[dummy_bot.send_message] {e}")
            return _FakeMsg(0)

    async def edit_message(self, entity, message_id, text, buttons=None, **kwargs):
        if self._tb is None:
            return None
        markup = _telethon_buttons_to_telebot(buttons)
        try:
            self._tb.edit_message_text(text, entity, message_id, reply_markup=markup)
        except Exception as e:
            print(f"[dummy_bot.edit_message] {e}")
            raise

    async def delete_messages(self, entity, message_ids):
        if self._tb is None:
            return
        if isinstance(message_ids, int):
            message_ids = [message_ids]
        for mid in message_ids:
            try:
                self._tb.delete_message(entity, mid)
            except Exception:
                pass


class _FakeMsg:
    """Емулює Telethon Message з мінімумом полів (.id)."""
    def __init__(self, msg_id):
        self.id = msg_id


def _telethon_buttons_to_telebot(buttons):
    """Конвертує Telethon Button.inline розмітку у telebot InlineKeyboardMarkup."""
    if not buttons:
        return None
    try:
        from telebot import types as _tbt
    except ImportError:
        return None
    markup = _tbt.InlineKeyboardMarkup()
    # buttons — це список рядків (list of lists of Button)
    for row in buttons:
        tb_row = []
        for b in row:
            try:
                text = getattr(b, "text", None) or str(b)
                data = getattr(b, "data", None)
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                if data is None:
                    continue
                tb_row.append(_tbt.InlineKeyboardButton(text, callback_data=data))
            except Exception:
                continue
        if tb_row:
            markup.row(*tb_row)
    return markup


bot = _DummyMasterBot()

# ============================================================

# ================= СТАТИЧНІ ДІАЛОГИ =================
STATIC_DIALOGUES = [
    [
        "Привіт! Як справи?",
        "Привіт 🙂 Все добре, а в тебе?",
        "Теж нормально. Чим займаєшся?",
        "Та відпочиваю після роботи.",
        "Звучить добре. Може, підемо завтра на каву?",
        "Давай, я не проти ☕",
        "Супер, домовились!"
    ],
    [
        "Привіт! Як справи?",
        "Привіт 🙂 Нормально, щойно додому прийшов. А ти?",
        "Теж норм, трохи втомилась після навчання.",
        "Багато завдань дали?",
        "Та як завжди 😅 Але вже майже все зробила.",
        "Може ввечері вийдеш прогулятись?",
        "Можна, а котра година?",
        "Десь о 19:00 підійде?",
        "Так, давай 👍",
        "Супер, тоді напишу ще перед виходом.",
        "Окей, чекаю 🙂"
    ],
    [
        "Ти вже дивився той фільм?",
        "Ні, ще ні. Варто?",
        "Дуже! Мені прям зайшов 🔥",
        "Тоді сьогодні гляну.",
        "Напишеш потім, як тобі?",
        "Звісно 🙂",
        "Домовились",
        "Гарного вечора!",
        "І тобі 😊"
    ],
    [
        "Привіт, ти вже бачив нові ціни на таксі? 😬",
        "Привіт. О так, сьогодні вранці замовляв, то був в шоці.",
        "От і я про те. Напевно, буду частіше на метро їздити.",
        "Та я теж так думаю. Хоча взимку не дуже хочеться.",
        "Це точно. Ну побачимо, може впадуть трохи.",
        "Будемо сподіватись 🙏"
    ],
    [
        "Привіт! Слухай, ти не знаєш де зараз можна купити нормальний павербанк?",
        "Привіт. Та в будь-якому магазині техніки, розетка чи щось таке.",
        "Дивився, там багато розкупили. Думав, може ти десь замовляв нещодавно.",
        "Я брав ще минулого року, якщо чесно. Можу скинути посилання.",
        "Давай, буду вдячний 🤝",
        "Трохи пізніше скину, як до компа доберусь.",
        "Без проблем, чекаю!"
    ]
]

# ================= КЛАВІАТУРИ =================
def menu_start(uid: int = 0):
    return [
        [Button.inline(_T(uid, 'r1_btn_url_ads'), b"open_accounts_menu")],
        [Button.inline(_T(uid, 'r1_btn_grp_ads'), b"open_group_menu")]
    ]

def menu_accounts(ctx: UserContext):
    uid = ctx.user_id
    return [
        [Button.inline(_T(uid, 'r1_btn_manage_acc'),       b"url_manage_accounts")],
        [Button.inline(_T(uid, 'r1_btn_manage_ad_params'), b"url_manage_params")],
        [Button.inline(_T(uid, 'r1_btn_back_main'),        b"back_to_main")]
    ]

def menu_url_manage_accounts(ctx: UserContext):
    uid = ctx.user_id
    return [
        [Button.inline(_T(uid, 'b_buy_acc_url'),     b"r7_buy_acc_url")],
        [Button.inline(_T(uid, 'r1_btn_proxy'),      b"url_proxy_connect")],
        [Button.inline(_T(uid, 'r1_btn_del_acc'),    b"delete_account")],
        [Button.inline(_T(uid, 'r1_btn_rename'),     b"rename_accounts")],
        [Button.inline(_T(uid, 'r1_btn_del_avatar'), b"delete_avatars")],
        [Button.inline(_T(uid, 'r1_btn_del_users'),  b"delete_usernames")],
        [Button.inline(_T(uid, 'r1_btn_bio'),        b"change_bio")],
        [Button.inline(_T(uid, 'r1_btn_pers_ch'),    b"create_personal_channel")],
        [Button.inline(_T(uid, 'r1_btn_photo'),      b"change_photo")],
        [Button.inline(_T(uid, 'r1_btn_clear_chats'),b"clear_all_chats")],
        [Button.inline(_T(uid, 'r1_btn_back_acc'),   b"back_to_accounts")]
    ]

def menu_url_manage_params(ctx: UserContext):
    uid = ctx.user_id
    return [
        [Button.inline(_T(uid, 'r1_btn_keywords'),   b"set_keywords")],
        [Button.inline(_T(uid, 'r1_btn_styles'),     b"manage_styles")],
        [Button.inline(_T(uid, 'r1_btn_reminders'),  b"manage_reminders")],
        [Button.inline(_T(uid, 'r1_btn_cycle'),      b"manage_cycle")],
        [Button.inline(_T(uid, 'r1_btn_channels'),   b"manage_channels")],
        [Button.inline(_T(uid, 'r1_btn_bot_status'), b"bot_status")],
        [Button.inline(_T(uid, 'r1_btn_search_ch'),  b"search_channels")],
        [Button.inline(_T(uid, 'r1_btn_back_acc'),   b"back_to_accounts")]
    ]

def menu_bot_status(ctx: UserContext):
    uid = ctx.user_id
    status = _T(uid, 'r1_bot_on') if ctx.bot_settings["bot_enabled"] else _T(uid, 'r1_bot_off')
    text = _T(uid, 'r1_bot_status_text').format(status=status)
    buttons = [
        [Button.inline(_T(uid, 'r1_btn_enable'),   b"bot_enable")],
        [Button.inline(_T(uid, 'r1_btn_disable'),  b"bot_disable")],
        [Button.inline(_T(uid, 'r1_btn_back_acc'), b"back_to_accounts")]
    ]
    return text, buttons

# ================= КЛАВІАТУРИ ДЛЯ РЕКЛАМИ У ГРУПАХ =================
def menu_group_accounts(ctx: UserContext):
    uid = ctx.user_id
    return [
        [Button.inline(_T(uid, 'r1_btn_manage_acc'),       b"grp_manage_accounts")],
        [Button.inline(_T(uid, 'r1_btn_manage_ad_params'), b"grp_manage_params")],
        [Button.inline(_T(uid, 'r1_btn_back_main'),        b"back_to_main")]
    ]

def menu_grp_manage_accounts(ctx: UserContext):
    uid = ctx.user_id
    return [
        [Button.inline(_T(uid, 'b_buy_acc_grp'),     b"r7_buy_acc_grp")],
        [Button.inline(_T(uid, 'r1_btn_proxy'),      b"grp_proxy_connect")],
        [Button.inline(_T(uid, 'r1_btn_del_acc'),    b"g_delete_account")],
        [Button.inline(_T(uid, 'r1_btn_rename'),     b"g_rename_accounts")],
        [Button.inline(_T(uid, 'r1_btn_del_avatar'), b"g_delete_avatars")],
        [Button.inline(_T(uid, 'r1_btn_del_users'),  b"g_delete_usernames")],
        [Button.inline(_T(uid, 'r1_btn_bio'),        b"g_change_bio")],
        [Button.inline(_T(uid, 'r1_btn_photo'),      b"g_change_photo")],
        [Button.inline(_T(uid, 'r1_btn_clear_chats'),b"g_clear_all_chats")],
        [Button.inline(_T(uid, 'r1_btn_back_acc'),   b"g_back_to_accounts")]
    ]

def menu_grp_manage_params(ctx: UserContext):
    uid = ctx.user_id
    return [
        [Button.inline(_T(uid, 'r1_btn_monitoring'), b"g_set_monitoring")],
        [Button.inline(_T(uid, 'r1_btn_groups'),     b"g_manage_groups")],
        [Button.inline(_T(uid, 'r1_btn_bot_status'), b"g_bot_status")],
        [Button.inline(_T(uid, 'r1_btn_search_chats'),b"g_search_chats")],
        [Button.inline(_T(uid, 'r1_btn_back_acc'),   b"g_back_to_accounts")]
    ]

def menu_group_bot_status(ctx: UserContext):
    uid = ctx.user_id
    status = _T(uid, 'r1_bot_on') if ctx.group_bot_settings["bot_enabled"] else _T(uid, 'r1_bot_off')
    text = _T(uid, 'r1_grp_bot_status_text').format(status=status)
    buttons = [
        [Button.inline(_T(uid, 'r1_btn_enable'),   b"g_bot_enable")],
        [Button.inline(_T(uid, 'r1_btn_disable'),  b"g_bot_disable")],
        [Button.inline(_T(uid, 'r1_btn_back_acc'), b"g_back_to_accounts")]
    ]
    return text, buttons

# ================= ДОПОМІЖНІ ФУНКЦІЇ =================
async def clear_chat(chat_id):
    ctx = get_ctx(chat_id)
    await ctx.clear_chat(chat_id)

async def send_and_track(chat_id, text, buttons=None):
    ctx = get_ctx(chat_id)
    return await ctx.send_and_track(chat_id, text, buttons)

async def show_start_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = None
    await ctx.show_nav(chat_id, _T(chat_id, 'r1_greeting'), buttons=menu_start(chat_id))

async def show_channels_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = None
    channels = ctx.bot_settings.get("channels", {})
    if channels:
        text = _T(chat_id, 'r1_channels_header')
        for folder_name, links in channels.items():
            text += f"📁 {folder_name}:\n"
            for link in links:
                text += f"  • {link}\n"
    else:
        text = _T(chat_id, 'r1_channels_empty')
    buttons = []
    for folder_name in channels.keys():
        short = folder_name[:28]
        cb = f"view_folder_{folder_name}".encode("utf-8")
        buttons.append([Button.inline(f"📁 {short}", cb)])
    buttons.append([Button.inline(_T(chat_id, 'r1_btn_create_folder'), b"create_folder")])
    buttons.append([Button.inline(_T(chat_id, 'r1_btn_del_folder'), b"delete_folder")])
    buttons.append([Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"back_to_accounts")])
    await ctx.show_nav(chat_id, text, buttons=buttons)

async def show_channels_folder(chat_id, folder_name):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = None
    channels = ctx.bot_settings.get("channels", {}).get(folder_name, [])
    if channels:
        text = _T(chat_id, 'r1_channels_folder_header').format(name=folder_name, count=len(channels))
        for link in channels:
            text += f"  • {link}\n"
    else:
        text = _T(chat_id, 'r1_channels_folder_empty').format(name=folder_name)
    buttons = []
    for link in channels:
        short = link.split("/")[-1][:25]
        cb = f"del_chan_{folder_name}|{link}".encode("utf-8")
        buttons.append([Button.inline(f"❌ {short}", cb)])
    cb_add = f"add_chan_{folder_name}".encode("utf-8")
    buttons.append([Button.inline(_T(chat_id, 'r1_btn_add_channel'), cb_add)])
    buttons.append([Button.inline(_T(chat_id, 'r1_btn_back_channels'), b"manage_channels")])
    await ctx.show_nav(chat_id, text, buttons=buttons)

async def _build_acc_list(chat_id, bots: list) -> str:
    acc_list = ""
    for i, acc in enumerate(bots):
        name = acc.get("name", _T(chat_id, 'r1_unknown'))
        try:
            active = acc["client"].is_connected() and await acc["client"].is_user_authorized()
        except:
            active = False
        icon = "✅" if active else "❌"
        acc_list += f"№{i+1} {name} {icon}\n"
    return acc_list or (_T(chat_id, 'r1_acc_empty') + "\n")

async def show_accounts_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = "WAITING_PHONE"
    # Очищуємо «секцію керування» — щоб наступний back повертав сюди.
    ctx._url_section = None
    acc_list = await _build_acc_list(chat_id, ctx.userbots)
    text = _T(chat_id, 'r1_acc_header') + "\n" + acc_list
    await ctx.show_nav(chat_id, text, buttons=menu_accounts(ctx))

async def show_url_manage_accounts_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = "WAITING_PHONE"
    ctx._url_section = 'acc'
    acc_list = await _build_acc_list(chat_id, ctx.userbots)
    text = _T(chat_id, 'r1_acc_header') + "\n" + acc_list
    await ctx.show_nav(chat_id, text, buttons=menu_url_manage_accounts(ctx))

async def show_url_manage_params_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = "WAITING_PHONE"
    ctx._url_section = 'params'
    acc_list = await _build_acc_list(chat_id, ctx.userbots)
    text = _T(chat_id, 'r1_acc_header') + "\n" + acc_list
    await ctx.show_nav(chat_id, text, buttons=menu_url_manage_params(ctx))

async def show_group_accounts_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = "G_WAITING_PHONE"
    ctx._grp_section = None
    acc_list = await _build_acc_list(chat_id, ctx.group_userbots)
    text = _T(chat_id, 'r1_acc_header') + "\n" + acc_list
    await ctx.show_nav(chat_id, text, buttons=menu_group_accounts(ctx))

async def show_grp_manage_accounts_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = "G_WAITING_PHONE"
    ctx._grp_section = 'acc'
    acc_list = await _build_acc_list(chat_id, ctx.group_userbots)
    text = _T(chat_id, 'r1_acc_header') + "\n" + acc_list
    await ctx.show_nav(chat_id, text, buttons=menu_grp_manage_accounts(ctx))

async def show_grp_manage_params_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = "G_WAITING_PHONE"
    ctx._grp_section = 'params'
    acc_list = await _build_acc_list(chat_id, ctx.group_userbots)
    text = _T(chat_id, 'r1_acc_header') + "\n" + acc_list
    await ctx.show_nav(chat_id, text, buttons=menu_grp_manage_params(ctx))


# ── Помічники: повернутися у попередню «секцію» керування ──────────
async def show_back_url_section(chat_id):
    """Повертає на ту manage-сторінку URL-реклами, з якої прийшли."""
    ctx = get_ctx(chat_id)
    section = getattr(ctx, '_url_section', None)
    if section == 'acc':
        await show_url_manage_accounts_menu(chat_id)
    elif section == 'params':
        await show_url_manage_params_menu(chat_id)
    else:
        await show_accounts_menu(chat_id)


async def show_back_grp_section(chat_id):
    """Повертає на ту manage-сторінку групової реклами, з якої прийшли."""
    ctx = get_ctx(chat_id)
    section = getattr(ctx, '_grp_section', None)
    if section == 'acc':
        await show_grp_manage_accounts_menu(chat_id)
    elif section == 'params':
        await show_grp_manage_params_menu(chat_id)
    else:
        await show_group_accounts_menu(chat_id)

def is_auth(user_id):
    return user_id in authenticated_users

def _settings_path(ctx: UserContext) -> str:
    return os.path.join(USERS_DATA_DIR, str(ctx.user_id), "settings.json")

def save_settings(ctx: UserContext):
    path = _settings_path(ctx)
    data = {
        "bot_settings": {k: v for k, v in ctx.bot_settings.items() if not k.startswith("_")},
        "group_bot_settings": {k: v for k, v in ctx.group_bot_settings.items()
                                if k not in ("monitoring_active",)},
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[save_settings] {ctx.user_id}: {e}")

def load_settings(ctx: UserContext):
    path = _settings_path(ctx)
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if "bot_settings" in data:
            for k, v in data["bot_settings"].items():
                ctx.bot_settings[k] = v
        if "group_bot_settings" in data:
            for k, v in data["group_bot_settings"].items():
                ctx.group_bot_settings[k] = v
    except Exception as e:
        print(f"[load_settings] {ctx.user_id}: {e}")

# ================= РОЗПОДІЛ КАНАЛІВ ТА ПАПОК =================
async def distribute_and_join_all_channels(ctx: UserContext):
    if not ctx.userbots:
        return
    all_regular = []
    all_folders = []

    for f_name, links in ctx.bot_settings["channels"].items():
        for l in links:
            if "t.me/addlist/" in l:
                if l not in all_folders:
                    all_folders.append(l)
            else:
                if l not in all_regular:
                    all_regular.append(l)

    folder_assignments = {acc["phone"]: [] for acc in ctx.userbots}
    for i, f in enumerate(all_folders):
        acc_idx = i % len(ctx.userbots)
        folder_assignments[ctx.userbots[acc_idx]["phone"]].append(f)

    for acc in ctx.userbots:
        client = acc["client"]
        phone = acc["phone"]
        for r in all_regular:
            try:
                await join_channel_and_discussion(client, r)
            except:
                pass
        for f in folder_assignments[phone]:
            try:
                await join_chat_folder(client, f)
            except:
                pass

# ================= ВИХІД З КАНАЛУ/ПАПКИ =================
async def leave_channel_on_all_accounts(ctx: UserContext, link: str):
    """Виходить з каналу на всіх акаунтах"""
    for acc in ctx.userbots:
        client = acc["client"]
        try:
            if "t.me/+" in link or "t.me/joinchat/" in link:
                pass  # Для приватних посилань просто ігноруємо — ентіті не отримати
            else:
                username = link.strip().split("/")[-1].replace("@", "").split("?")[0]
                try:
                    entity = await client.get_entity(username)
                    await client(LeaveChannelRequest(entity))
                    print(f"✅ {acc['phone']} вийшов з {username}")
                except Exception as e:
                    print(f"ℹ️ {acc['phone']} не зміг вийти з {username}: {e}")
        except Exception as e:
            print(f"Помилка виходу з {link}: {e}")
        await asyncio.sleep(0.5)

async def leave_folder_channels_on_all_accounts(ctx: UserContext, links: list):
    """Виходить з усіх каналів у папці на всіх акаунтах"""
    for link in links:
        if "t.me/addlist/" in link:
            print(f"ℹ️ Папку {link} видалено з бота, але авто-вихід з папок TG не підтримується.")
        else:
            await leave_channel_on_all_accounts(ctx, link)

async def join_channel_and_discussion(ubot: TelegramClient, link: str):
    try:
        link = link.strip()
        if "t.me/+" in link or "t.me/joinchat/" in link:
            from telethon.tl.functions.messages import ImportChatInviteRequest
            invite_hash = link.split("/")[-1].replace("+", "")
            await ubot(ImportChatInviteRequest(invite_hash))
        else:
            username = link.split("/")[-1].replace("@", "").split("?")[0]
            channel = await ubot.get_entity(username)
            await ubot(JoinChannelRequest(channel))
        await asyncio.sleep(2)
        try:
            username = link.split("/")[-1].replace("@", "").split("?")[0]
            channel = await ubot.get_entity(username)
            full = await ubot(GetFullChannelRequest(channel))
            if full.full_chat.linked_chat_id:
                discussion = await ubot.get_entity(full.full_chat.linked_chat_id)
                await ubot(JoinChannelRequest(discussion))
        except:
            pass
    except:
        pass

async def join_chat_folder(ubot: TelegramClient, link: str):
    try:
        slug = link.strip().split('/')[-1]
        check = await ubot(CheckChatlistInviteRequest(slug))
        if hasattr(check, 'peers'):
            await ubot(JoinChatlistInviteRequest(slug=slug, peers=check.peers))
            print(f"✅ Успішно додано Telegram-папку {slug}")
    except Exception as e:
        print(f"ℹ️ Папка {link} вже додана або виникла помилка: {e}")

# ================= ВЗАЄМНІ КОНТАКТИ =================
async def init_mutual_contacts(ctx: UserContext):
    if len(ctx.userbots) < 2:
        return
    print("🤝 Ініціалізація взаємних контактів між акаунтами...")
    for acc in ctx.userbots:
        for other in ctx.userbots:
            if acc["phone"] == other["phone"]:
                continue
            phone = other["phone"] if other["phone"].startswith("+") else "+" + other["phone"]
            try:
                await acc["client"](ImportContactsRequest([
                    InputPhoneContact(client_id=0, phone=phone, first_name=other.get("name", "User"), last_name="")
                ]))
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Помилка додавання контакту {phone}: {e}")

# ================= ОЧИЩЕННЯ ЧАТІВ =================
async def clear_account_chats(acc):
    client = acc["client"]
    phone = acc["phone"]
    try:
        dialogs = await client.get_dialogs(limit=500)
        deleted = 0
        for dialog in dialogs:
            try:
                if dialog.is_channel or dialog.is_group:
                    try:
                        await client(LeaveChannelRequest(dialog.input_entity))
                    except:
                        pass
                    try:
                        await client(DeleteHistoryRequest(peer=dialog.input_entity, max_id=0, just_clear=True, revoke=False))
                    except:
                        pass
                else:
                    await client(DeleteHistoryRequest(peer=dialog.input_entity, max_id=0, just_clear=False, revoke=True))
                deleted += 1
                await asyncio.sleep(0.3)
            except:
                pass
        print(f"✅ Акаунт {phone}: очищено {deleted} чатів.")
        return deleted
    except Exception as e:
        print(f"❌ Помилка очищення чатів {phone}: {e}")
        return 0

# ================= КОМАНДА /start =================
@bot.on(events.NewMessage(pattern="/start", from_users=ADMIN_ID))
async def cmd_start(event):
    chat_id = event.chat_id
    ctx = get_ctx(chat_id)
    ctx.messages_to_delete.setdefault(chat_id, []).append(event.id)
    if not is_auth(chat_id):
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_auth_pwd_prompt'))
    else:
        await show_start_menu(chat_id)

# ================= ОБРОБНИК ТЕКСТОВИХ ПОВІДОМЛЕНЬ =================
@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.via_bot_id))
async def text_handler(event):
    if event.sender_id != ADMIN_ID:
        return
    chat_id = event.chat_id
    ctx = get_ctx(chat_id)
    text = event.raw_text.strip()
    ctx.messages_to_delete.setdefault(chat_id, []).append(event.id)

    if not is_auth(chat_id):
        if text == PASSWORD:
            authenticated_users.add(chat_id)
            await ctx.clear_chat(chat_id)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_auth_pwd_ok'))
            await asyncio.sleep(1)
            await show_start_menu(chat_id)
        else:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_auth_pwd_wrong'))
        return

    state = ctx.user_states.get(chat_id)

    import rukla3 as _r3
    if await _r3.handle_text_state(ctx, chat_id, state, text, event): return
    import rukla2 as _r2
    if await _r2.handle_text_state(ctx, chat_id, state, text, event): return

    # ================= ПРОКСІ: URL АКАУНТИ =================
    if state == "WAITING_URL_PROXY":
        ctx.user_states[chat_id] = None
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        parsed = [parse_socks5_proxy(l) for l in lines]
        parsed = [p for p in parsed if p]
        if not parsed:
            await ctx.send_and_track(
                chat_id,
                _T(chat_id, 'r1_proxy_none'),
                [[Button.inline(_T(chat_id, 'r1_btn_proxy'), b"url_proxy_connect"),
                  Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"back_to_accounts")]]
            )
            return
        ctx.url_proxies.clear()
        ctx.url_proxies.extend(parsed)
        if not ctx.userbots:
            await ctx.send_and_track(
                chat_id,
                _T(chat_id, 'r1_proxy_ok').format(info=format_active_proxies(ctx.url_proxies, chat_id)),
                [[Button.inline(_T(chat_id, 'r1_btn_clear_chats'), b"url_proxy_delete_all")],
                 [Button.inline(_T(chat_id, 'r1_btn_back_main'), b"back_to_main")]]
            )
            return
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_del_progress'))
        ok, fail = await apply_proxies_to_accounts(ctx, ctx.userbots, ctx.url_proxies, sessions_dir=ctx._sessions_dir)
        if ok > 0:
            result_text = _T(chat_id, 'r1_proxy_ok').format(
                info=_T(chat_id, 'r1_proxy_result_info').format(ok=ok, fail=fail, proxies=format_active_proxies(ctx.url_proxies, chat_id))
            )
        else:
            result_text = _T(chat_id, 'r1_proxy_none') + f"\n\n{format_active_proxies(ctx.url_proxies, chat_id)}"
        await ctx.send_and_track(
            chat_id, result_text,
            [[Button.inline(_T(chat_id, 'r1_btn_del_avatar'), b"url_proxy_delete_all")],
             [Button.inline(_T(chat_id, 'r1_btn_back_main'), b"back_to_main")]]
        )
        return

    # ================= ПРОКСІ: ГРУПИ =================
    if state == "WAITING_GRP_PROXY":
        ctx.user_states[chat_id] = None
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        parsed = [parse_socks5_proxy(l) for l in lines]
        parsed = [p for p in parsed if p]
        if not parsed:
            await ctx.send_and_track(
                chat_id,
                _T(chat_id, 'r1_proxy_none'),
                [[Button.inline(_T(chat_id, 'r1_btn_proxy'), b"grp_proxy_connect"),
                  Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]]
            )
            return
        ctx.group_proxies.clear()
        ctx.group_proxies.extend(parsed)
        if not ctx.group_userbots:
            await ctx.send_and_track(
                chat_id,
                _T(chat_id, 'r1_proxy_ok').format(info=format_active_proxies(ctx.group_proxies, chat_id)),
                [[Button.inline(_T(chat_id, 'r1_btn_clear_chats'), b"grp_proxy_delete_all")],
                 [Button.inline(_T(chat_id, 'r1_btn_back_main'), b"back_to_main")]]
            )
            return
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_del_progress'))
        ok, fail = await apply_proxies_to_accounts(ctx, ctx.group_userbots, ctx.group_proxies, sessions_dir=ctx._group_sessions_dir)
        if ok > 0:
            result_text = _T(chat_id, 'r1_proxy_ok').format(
                info=_T(chat_id, 'r1_proxy_result_info').format(ok=ok, fail=fail, proxies=format_active_proxies(ctx.group_proxies, chat_id))
            )
        else:
            result_text = _T(chat_id, 'r1_proxy_none') + f"\n\n{format_active_proxies(ctx.group_proxies, chat_id)}"
        await ctx.send_and_track(
            chat_id, result_text,
            [[Button.inline(_T(chat_id, 'r1_btn_del_avatar'), b"grp_proxy_delete_all")],
             [Button.inline(_T(chat_id, 'r1_btn_back_main'), b"back_to_main")]]
        )
        return

    # ================= ВИДАЛЕННЯ АКАУНТІВ (URL) =================
    if state == "WAITING_DELETE_NUM":
        text_stripped = text.strip().lower()
        if text_stripped == "all":
            count = len(ctx.userbots)
            for acc in list(ctx.userbots):
                try:
                    await acc["client"].disconnect()
                    path = os.path.join(ctx._sessions_dir, f"{acc['phone']}.session")
                    if os.path.exists(path):
                        os.remove(path)
                except:
                    pass
            ctx.userbots.clear()
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_all_ok').format(count=count))
            await asyncio.sleep(1)
            await show_back_url_section(chat_id)
        elif "-" in text_stripped:
            parts = text_stripped.split("-")
            try:
                start = int(parts[0].strip()) - 1
                end = int(parts[1].strip()) - 1
                to_delete_indices = sorted(
                    [i for i in range(start, end + 1) if 0 <= i < len(ctx.userbots)],
                    reverse=True
                )
                deleted_count = 0
                for i in to_delete_indices:
                    acc = ctx.userbots.pop(i)
                    try:
                        await acc["client"].disconnect()
                        path = os.path.join(ctx._sessions_dir, f"{acc['phone']}.session")
                        if os.path.exists(path):
                            os.remove(path)
                        deleted_count += 1
                    except:
                        pass
                await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_all_ok').format(count=deleted_count))
            except:
                await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_range_err'))
            await asyncio.sleep(1)
            await show_back_url_section(chat_id)
        else:
            num_str = ''.join(filter(str.isdigit, text))
            if num_str:
                num = int(num_str) - 1
                if 0 <= num < len(ctx.userbots):
                    acc = ctx.userbots.pop(num)
                    try:
                        await acc["client"].disconnect()
                        path = os.path.join(ctx._sessions_dir, f"{acc['phone']}.session")
                        if os.path.exists(path):
                            os.remove(path)
                    except:
                        pass
                    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_one_ok').format(num=num+1))
                    await asyncio.sleep(1)
                    await show_back_url_section(chat_id)
                else:
                    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_no_num'))
        return
    elif state == "WAITING_RENAME":
        for acc in ctx.userbots:
            try:
                await acc["client"](UpdateProfileRequest(first_name=text, last_name=""))
                acc["name"] = text
            except:
                pass
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_rename_ok'))
        await asyncio.sleep(1)
        await show_back_url_section(chat_id)
        return

    elif state == "WAITING_BIO":
        for acc in ctx.userbots:
            try:
                await acc["client"](UpdateProfileRequest(about=text))
            except:
                pass
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_bio_ok'))
        await asyncio.sleep(1)
        await show_back_url_section(chat_id)
        return

    elif state == "WAITING_CHANNEL_NAME":
        ctx.user_states[chat_id] = f"WAITING_CHANNEL_AVATAR"
        ctx.bot_settings["_pending_channel"] = {"name": text}
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_avatar_prompt').format(name=text))
        return

    elif state == "WAITING_CHANNEL_POST":
        pending = ctx.bot_settings.get("_pending_channel", {})
        pending["post_text"] = text
        pending["post_entities"] = event.message.entities
        pending["post_media"] = None
        ctx.bot_settings["_pending_channel"] = pending
        await _execute_create_personal_channel(chat_id)
        return

    # ================= ДОДАВАННЯ АКАУНТІВ (КОД/ПАРОЛЬ) =================
    elif state == "WAITING_PHONE":
        phone = re.sub(r'[^\d\+]', '', text)
        if not phone.startswith("+"):
            phone = "+" + phone
        # Дедуп: якщо акаунт уже доданий — нічого не робимо
        if any(a.get('phone') == phone for a in ctx.userbots):
            await ctx.send_and_track(
                chat_id,
                f"↩️ Акаунт {phone} вже доданий — пропускаю."
            )
            ctx.user_states.pop(chat_id, None)
            return
        ubot = TelegramClient(os.path.join(ctx._sessions_dir, phone), API_ID, API_HASH)
        await ubot.connect()
        try:
            sent = await ubot.send_code_request(phone)
            ctx.auth_sessions[phone] = {"client": ubot, "hash": sent.phone_code_hash}
            ctx.user_states[chat_id] = f"WAITING_CODE_{phone}"
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_code_sent').format(phone=phone))
        except Exception as e:
            await ctx.send_and_track(chat_id, f"❌ {e}")
        return
    elif state and state.startswith("WAITING_CODE_"):
        phone = state.split("_", 2)[2]
        code = re.sub(r'[^\d]', '', text)
        sess = ctx.auth_sessions.get(phone)
        if not sess:
            return
        try:
            await sess["client"].sign_in(phone, code, phone_code_hash=sess["hash"])
            await finalize_auth(ctx, sess["client"], phone, chat_id)
        except SessionPasswordNeededError:
            ctx.user_states[chat_id] = f"WAITING_PASSWORD_{phone}"
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_2fa_prompt'))
        except Exception as e:
            await ctx.send_and_track(chat_id, f"❌ {e}")
        return
    elif state and state.startswith("WAITING_PASSWORD_"):
        phone = state.split("_", 2)[2]
        sess = ctx.auth_sessions.get(phone)
        if not sess:
            return
        try:
            await sess["client"].sign_in(password=text)
            await finalize_auth(ctx, sess["client"], phone, chat_id)
        except Exception as e:
            await ctx.send_and_track(chat_id, f"❌ 2FA: {e}")
        return

    # ================= ГРУПА: ВИДАЛЕННЯ АКАУНТІВ =================
    if state == "G_WAITING_DELETE_NUM":
        text_stripped = text.strip().lower()
        if text_stripped == "all":
            count = len(ctx.group_userbots)
            for acc in list(ctx.group_userbots):
                try:
                    await acc["client"].disconnect()
                    sess_path = os.path.join(ctx._group_sessions_dir, f"{acc['phone']}.session")
                    if os.path.exists(sess_path):
                        os.remove(sess_path)
                except:
                    pass
            ctx.group_userbots.clear()
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_all_ok').format(count=count))
            await asyncio.sleep(1)
            await show_back_grp_section(chat_id)
        elif "-" in text_stripped:
            parts = text_stripped.split("-")
            try:
                start = int(parts[0].strip()) - 1
                end = int(parts[1].strip()) - 1
                to_delete_indices = sorted(
                    [i for i in range(start, end + 1) if 0 <= i < len(ctx.group_userbots)],
                    reverse=True
                )
                deleted_count = 0
                for i in to_delete_indices:
                    acc = ctx.group_userbots.pop(i)
                    try:
                        await acc["client"].disconnect()
                        sess_path = os.path.join(ctx._group_sessions_dir, f"{acc['phone']}.session")
                        if os.path.exists(sess_path):
                            os.remove(sess_path)
                        deleted_count += 1
                    except:
                        pass
                await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_all_ok').format(count=deleted_count))
            except:
                await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_range_err'))
            await asyncio.sleep(1)
            await show_back_grp_section(chat_id)
        else:
            num_str = ''.join(filter(str.isdigit, text))
            if num_str:
                num = int(num_str) - 1
                if 0 <= num < len(ctx.group_userbots):
                    acc = ctx.group_userbots.pop(num)
                    try:
                        await acc["client"].disconnect()
                        sess_path = os.path.join(ctx._group_sessions_dir, f"{acc['phone']}.session")
                        if os.path.exists(sess_path):
                            os.remove(sess_path)
                    except:
                        pass
                    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_one_ok').format(num=num+1))
                    await asyncio.sleep(1)
                    await show_back_grp_section(chat_id)
                else:
                    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_no_num'))
        return

    elif state == "G_WAITING_RENAME_NAMES":
        names = [n.strip() for n in text.split("\n") if n.strip()]
        if not names:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_rename_empty'))
            return
        ctx.group_bot_settings["name_pool"] = names
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_rename_progress').format(n=len(names)))
        changed = 0
        for acc in ctx.group_userbots:
            chosen = random.choice(names)
            acc["name"] = chosen
            try:
                await acc["client"](UpdateProfileRequest(first_name=chosen, last_name=""))
                changed += 1
            except Exception as e:
                print(f"Rename error {acc['phone']}: {e}")
            await asyncio.sleep(0.5)
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_rename_ok').format(changed=changed, total=len(ctx.group_userbots)))
        await asyncio.sleep(1)
        await show_back_grp_section(chat_id)
        return

    elif state == "G_WAITING_BIO":
        for acc in ctx.group_userbots:
            try:
                await acc["client"](UpdateProfileRequest(about=text))
            except:
                pass
            await asyncio.sleep(0.3)
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_bio_ok'))
        await asyncio.sleep(1)
        await show_back_grp_section(chat_id)
        return

    elif state == "G_WAITING_PHONE":
        phone = re.sub(r'[^\d\+]', '', text)
        if not phone.startswith("+"):
            phone = "+" + phone
        # Дедуп: якщо акаунт уже доданий у групову рекламу — нічого не робимо
        if any(a.get('phone') == phone for a in ctx.group_userbots):
            await ctx.send_and_track(
                chat_id,
                f"↩️ Акаунт {phone} вже доданий у групову рекламу — пропускаю."
            )
            ctx.user_states.pop(chat_id, None)
            return
        os.makedirs(ctx._group_sessions_dir, exist_ok=True)
        sess_name = os.path.join(ctx._group_sessions_dir, phone)
        ubot = TelegramClient(sess_name, API_ID, API_HASH)
        await ubot.connect()
        try:
            sent = await ubot.send_code_request(phone)
            ctx.group_auth_sessions[phone] = {"client": ubot, "hash": sent.phone_code_hash}
            ctx.user_states[chat_id] = f"G_WAITING_CODE_{phone}"
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_code_sent').format(phone=phone))
        except Exception as e:
            await ctx.send_and_track(chat_id, f"❌ Помилка: {e}")
        return
    elif state and state.startswith("G_WAITING_CODE_"):
        phone = state.split("_", 3)[3]
        code = re.sub(r'[^\d]', '', text)
        sess = ctx.group_auth_sessions.get(phone)
        if not sess:
            return
        try:
            await sess["client"].sign_in(phone, code, phone_code_hash=sess["hash"])
            await finalize_group_auth(ctx, sess["client"], phone, chat_id)
        except SessionPasswordNeededError:
            ctx.user_states[chat_id] = f"G_WAITING_PASSWORD_{phone}"
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_2fa_prompt'))
        except Exception as e:
            await ctx.send_and_track(chat_id, f"❌ Помилка: {e}")
        return
    elif state and state.startswith("G_WAITING_PASSWORD_"):
        phone = state.split("_", 3)[3]
        sess = ctx.group_auth_sessions.get(phone)
        if not sess:
            return
        try:
            await sess["client"].sign_in(password=text)
            await finalize_group_auth(ctx, sess["client"], phone, chat_id)
        except Exception as e:
            await ctx.send_and_track(chat_id, f"❌ Помилка 2FA: {e}")
        return

    # ================= УПРАВЛІННЯ КАНАЛАМИ: ТЕКСТОВІ СТАНИ =================
    elif state == "WAITING_FOLDER_NAME":
        folder_name = text.strip()
        if not folder_name:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_folder_empty'))
            return
        if folder_name in ctx.bot_settings["channels"]:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_folder_exists').format(name=folder_name))
            return
        ctx.bot_settings["channels"][folder_name] = []
        save_settings(ctx)
        ctx.user_states[chat_id] = None
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_folder_ok').format(name=folder_name))
        await asyncio.sleep(1)
        await show_channels_folder(chat_id, folder_name)
        return

    elif state == "WAITING_DELETE_FOLDER":
        folder_name = text.strip()
        if folder_name in ctx.bot_settings.get("channels", {}):
            del ctx.bot_settings["channels"][folder_name]
            save_settings(ctx)
            ctx.user_states[chat_id] = None
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_folder_del_ok').format(name=folder_name))
        else:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_folder_not_found').format(name=folder_name))
            return
        await asyncio.sleep(1)
        await show_channels_menu(chat_id)
        return

    elif state and state.startswith("WAITING_CHANNEL_LINK_"):
        folder_name = state[len("WAITING_CHANNEL_LINK_"):]
        link = text.strip()
        if not link:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_link_prompt'))
            return
        if folder_name not in ctx.bot_settings["channels"]:
            ctx.bot_settings["channels"][folder_name] = []
        if link not in ctx.bot_settings["channels"][folder_name]:
            ctx.bot_settings["channels"][folder_name].append(link)
            save_settings(ctx)
            ctx.user_states[chat_id] = None
            asyncio.create_task(distribute_and_join_all_channels(ctx))
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_link_added').format(name=folder_name))
        else:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_link_exists').format(name=folder_name))
            ctx.user_states[chat_id] = None
        await asyncio.sleep(1)
        await show_channels_folder(chat_id, folder_name)
        return


# ================= ОБРОБНИК МЕДІА =================
@bot.on(events.NewMessage(func=lambda e: e.is_private and e.file is not None))
async def handle_media(event):
    if event.sender_id != ADMIN_ID:
        return
    chat_id = event.chat_id
    ctx = get_ctx(chat_id)
    if not is_auth(chat_id):
        return
    file_name = getattr(event.file, "name", "") or ""
    mime_type = getattr(event.file, "mime_type", "") or ""
    state = ctx.user_states.get(chat_id)

    is_zip = file_name.lower().endswith(".zip") or "zip" in mime_type.lower()
    is_session = file_name.lower().endswith(".session")

    if is_zip:
        if state == "G_WAITING_CHANGE_PHOTO_ZIP":
            await _handle_group_avatar_zip(ctx, event, chat_id)
        elif state and state.startswith("G_"):
            await _handle_group_zip(ctx, event, chat_id)
        else:
            await _handle_zip(ctx, event, chat_id)
        return

    if is_session:
        is_group_section = state and state.startswith("G_")
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_session_progress'))
        file_path = await event.download_media()
        clean_name = re.sub(r'[^\w\+]', '', file_name.replace(".session", ""))
        if not clean_name:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_session_bad_name'))
            os.remove(file_path)
            return
        if is_group_section:
            os.makedirs(ctx._group_sessions_dir, exist_ok=True)
            dest_path = os.path.join(ctx._group_sessions_dir, f"{clean_name}.session")
        else:
            dest_path = os.path.join(ctx._sessions_dir, f"{clean_name}.session")
        shutil.move(file_path, dest_path)
        try:
            if is_group_section:
                sess_name = os.path.join(ctx._group_sessions_dir, clean_name)
            else:
                sess_name = os.path.join(ctx._sessions_dir, clean_name)
            ubot = TelegramClient(sess_name, API_ID, API_HASH)
            await ubot.connect()
            if await ubot.is_user_authorized():
                if is_group_section:
                    await finalize_group_auth(ctx, ubot, clean_name, chat_id)
                else:
                    await finalize_auth(ctx, ubot, clean_name, chat_id)
            else:
                await ubot.disconnect()
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                await ctx.send_and_track(chat_id, _T(chat_id, 'r1_session_invalid'))
        except Exception as e:
            await ctx.send_and_track(chat_id, f"❌ Помилка: {e}")
        return

    if state == "WAITING_CHANNEL_AVATAR":
        pending = ctx.bot_settings.get("_pending_channel", {})
        file_path = await event.download_media()
        pending["avatar_path"] = file_path
        ctx.bot_settings["_pending_channel"] = pending
        ctx.user_states[chat_id] = "WAITING_CHANNEL_POST"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_avatar_ok'))
        return

    if state == "WAITING_CHANNEL_POST":
        pending = ctx.bot_settings.get("_pending_channel", {})
        file_path = await event.download_media()
        pending["post_text"] = event.message.message or ""
        pending["post_entities"] = event.message.entities
        pending["post_media"] = file_path
        ctx.bot_settings["_pending_channel"] = pending
        await _execute_create_personal_channel(chat_id)
        return

    if state == "WAITING_CHANGE_PHOTO":
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_photo_progress'))
        file_path = await event.download_media()
        success = 0
        for acc in ctx.userbots:
            try:
                uploaded = await acc["client"].upload_file(file_path)
                await acc["client"](UploadProfilePhotoRequest(file=uploaded))
                success += 1
            except Exception as e:
                print(f"Помилка зміни фото {acc['phone']}: {e}")
        os.remove(file_path)
        ctx.user_states[chat_id] = None
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_photo_ok').format(success=success, total=len(ctx.userbots)))
        await asyncio.sleep(1)
        await show_back_url_section(chat_id)
        return

# ================= СТВОРЕННЯ ПЕРСОНАЛЬНОГО КАНАЛУ =================
async def _execute_create_personal_channel(chat_id):
    ctx = get_ctx(chat_id)
    pending = ctx.bot_settings.get("_pending_channel", {})
    channel_name = pending.get("name", "My Channel")
    avatar_path = pending.get("avatar_path")
    post_text = pending.get("post_text", "")
    post_entities = pending.get("post_entities")
    post_media = pending.get("post_media")

    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_create_progress').format(name=channel_name, n=len(ctx.userbots)))
    ctx.user_states[chat_id] = None

    created_count = 0
    for acc in ctx.userbots:
        client = acc["client"]
        phone = acc["phone"]
        try:
            result = await client(CreateChannelRequest(title=channel_name, about="", megagroup=False, broadcast=True))
            channel_entity = result.chats[0]
            base_slug = re.sub(r'[^a-zA-Z0-9]', '', channel_name.lower()) or "channel"
            unique_slug = f"{base_slug}_{random.randint(10000, 99999)}"
            try:
                await client(UpdateUsernameRequest(channel=channel_entity, username=unique_slug))
            except Exception as e:
                print(f"⚠️ Не вдалося встановити username для {phone}: {e}")

            if avatar_path and os.path.exists(avatar_path):
                try:
                    uploaded_photo = await client.upload_file(avatar_path)
                    await client(EditPhotoRequest(channel=channel_entity, photo=uploaded_photo))
                except Exception as e:
                    print(f"⚠️ Аватарка каналу {phone}: {e}")

            await asyncio.sleep(1)
            if post_media and os.path.exists(post_media):
                await client.send_file(channel_entity, post_media, caption=post_text, formatting_entities=post_entities)
            else:
                await client.send_message(channel_entity, post_text, formatting_entities=post_entities)

            try:
                from telethon.tl.functions.account import UpdatePersonalChannelRequest
                await client(UpdatePersonalChannelRequest(channel=channel_entity))
            except Exception as e:
                print(f"⚠️ Особистий канал у профілі {phone}: {e}")

            created_count += 1
            print(f"✅ Канал створено для {phone}")
            await asyncio.sleep(2)
        except Exception as e:
            print(f"❌ Помилка створення каналу для {phone}: {e}")

    if avatar_path and os.path.exists(avatar_path):
        try:
            os.remove(avatar_path)
        except:
            pass
    if post_media and os.path.exists(post_media):
        try:
            os.remove(post_media)
        except:
            pass
    ctx.bot_settings.pop("_pending_channel", None)

    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_create_ok').format(created=created_count, total=len(ctx.userbots)))
    await asyncio.sleep(1)
    await show_back_url_section(chat_id)

# ================= ОБРОБНИК ZIP (URL акаунти) =================
async def _handle_zip(ctx: UserContext, event, chat_id):
    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_zip_progress'))
    file_path = await event.download_media()
    extract_dir = f"temp_sessions_{event.id}"
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        os.remove(file_path)
        loaded = 0
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if not file.endswith(".session"):
                    continue
                source_path = os.path.join(root, file)
                if "bot" in file.lower() or "feedback" in file.lower() or file == "master.session":
                    continue
                if not is_telethon_session(source_path):
                    continue
                clean_name = re.sub(r'[^\w\+]', '', file.replace(".session", ""))
                if not clean_name:
                    continue
                dest_path = os.path.join(ctx._sessions_dir, f"{clean_name}.session")
                shutil.move(source_path, dest_path)
                try:
                    ubot = TelegramClient(os.path.join(ctx._sessions_dir, clean_name), API_ID, API_HASH)
                    await ubot.connect()
                    if await ubot.is_user_authorized():
                        await finalize_auth(ctx, ubot, clean_name, quiet=True)
                        loaded += 1
                    else:
                        await ubot.disconnect()
                        if os.path.exists(dest_path):
                            os.remove(dest_path)
                except:
                    pass
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_zip_ok').format(loaded=loaded))
        await asyncio.sleep(2)
        await show_back_url_section(chat_id)
    except Exception as e:
        await ctx.send_and_track(chat_id, f"❌ Помилка обробки ZIP: {e}")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

# ================= ОБРОБНИК ZIP (акаунти для груп) =================
async def _handle_group_zip(ctx: UserContext, event, chat_id):
    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_zip_progress'))
    file_path = await event.download_media()
    extract_dir = f"temp_group_sessions_{event.id}"
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        os.remove(file_path)
        loaded = 0
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if not file.endswith(".session"):
                    continue
                source_path = os.path.join(root, file)
                if "bot" in file.lower() or "feedback" in file.lower() or file == "master.session":
                    continue
                if not is_telethon_session(source_path):
                    continue
                clean_name = re.sub(r'[^\w\+]', '', file.replace(".session", ""))
                if not clean_name:
                    continue
                dest_path = os.path.join(ctx._group_sessions_dir, f"{clean_name}.session")
                shutil.move(source_path, dest_path)
                try:
                    sess_name = os.path.join(ctx._group_sessions_dir, clean_name)
                    ubot = TelegramClient(sess_name, API_ID, API_HASH)
                    await ubot.connect()
                    if await ubot.is_user_authorized():
                        await finalize_group_auth(ctx, ubot, clean_name, quiet=True)
                        loaded += 1
                    else:
                        await ubot.disconnect()
                        if os.path.exists(dest_path):
                            os.remove(dest_path)
                except:
                    pass
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_zip_ok').format(loaded=loaded))
        await asyncio.sleep(2)
        await show_back_grp_section(chat_id)
    except Exception as e:
        await ctx.send_and_track(chat_id, f"❌ Помилка обробки ZIP: {e}")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

# ================= ОБРОБНИК ZIP АВАТАРОК (для відділу груп) =================
async def _handle_group_avatar_zip(ctx: UserContext, event, chat_id):
    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_avatar_zip_progress'))
    file_path = await event.download_media()
    avatar_dir = os.path.join(ctx._group_sessions_dir, "avatars")
    os.makedirs(avatar_dir, exist_ok=True)
    extract_dir = f"temp_avatars_{event.id}"
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        os.remove(file_path)

        for old in ctx.group_bot_settings["avatar_pool"]:
            try:
                os.remove(old)
            except:
                pass
        ctx.group_bot_settings["avatar_pool"] = []

        count = 0
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                if not file.lower().endswith((".png", ".jpg", ".jpeg")):
                    continue
                src = os.path.join(root, file)
                dest = os.path.join(avatar_dir, f"avatar_{count}_{file}")
                shutil.move(src, dest)
                ctx.group_bot_settings["avatar_pool"].append(dest)
                count += 1
                if count >= 50:
                    break
            if count >= 50:
                break

        if count == 0:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_avatar_zip_no_imgs'))
            return

        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_avatar_zip_ok').format(count=count))
        ctx.user_states[chat_id] = None

        no_photo_count = 0
        photo_count = 0
        for acc in ctx.group_userbots:
            try:
                if random.random() < 0.5:
                    photos = await acc["client"](GetUserPhotosRequest(user_id="me", offset=0, max_id=0, limit=10))
                    if photos.photos:
                        await acc["client"](DeletePhotosRequest(id=photos.photos))
                    no_photo_count += 1
                else:
                    avatar_path = random.choice(ctx.group_bot_settings["avatar_pool"])
                    uploaded = await acc["client"].upload_file(avatar_path)
                    await acc["client"](UploadProfilePhotoRequest(file=uploaded))
                    photo_count += 1
            except Exception as e:
                print(f"Помилка фото {acc.get('phone')}: {e}")
            await asyncio.sleep(0.5)

        await ctx.send_and_track(
            chat_id,
            _T(chat_id, 'r1_avatar_zip_result').format(photo=photo_count, no_photo=no_photo_count)
        )
        await asyncio.sleep(1)
        await show_back_grp_section(chat_id)
    except Exception as e:
        await ctx.send_and_track(chat_id, f"❌ Помилка: {e}")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

# ================= CALLBACK КНОПКИ =================
@bot.on(events.CallbackQuery(func=lambda e: e.sender_id == ADMIN_ID))
async def callback_handler(event):
    chat_id = event.chat_id
    ctx = get_ctx(chat_id)
    if not is_auth(chat_id):
        return
    data = event.data
    await event.answer()

    import rukla3 as _r3
    if await _r3.handle_callback(ctx, chat_id, data, event): return
    import rukla2 as _r2
    if await _r2.handle_callback(ctx, chat_id, data, event): return

    if data == b"noop":
        return
    elif data == b"open_accounts_menu":
        await show_accounts_menu(chat_id)
    elif data == b"url_manage_accounts":
        await show_url_manage_accounts_menu(chat_id)
    elif data == b"url_manage_params":
        await show_url_manage_params_menu(chat_id)
    elif data == b"back_to_main":
        await show_start_menu(chat_id)
    elif data == b"back_to_accounts":
        # Кнопка back на manage-сторінці завжди веде на рівень вище (top URL menu).
        # Повернення на manage-сторінку з sub-action — окремий шлях через
        # show_back_url_section у обробниках стану (post-action).
        await show_accounts_menu(chat_id)
    elif data == b"delete_account":
        ctx.user_states[chat_id] = "WAITING_DELETE_NUM"
        acc_list = ""
        for i, acc in enumerate(ctx.userbots):
            acc_list += f"  №{i+1} — {acc.get('name', acc['phone'])}\n"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_delete_prompt').format(acc_list=acc_list))
    elif data == b"rename_accounts":
        ctx.user_states[chat_id] = "WAITING_RENAME"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_rename_prompt'))
    elif data == b"delete_avatars":
        if not ctx.userbots:
            return
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_avatar_progress'))
        total = 0
        for acc in ctx.userbots:
            try:
                photos = await acc["client"](GetUserPhotosRequest(user_id="me", offset=0, max_id=0, limit=100))
                if photos.photos:
                    await acc["client"](DeletePhotosRequest(id=photos.photos))
                    total += len(photos.photos)
            except:
                pass
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_avatar_ok').format(total=total))
        await asyncio.sleep(1)
        await show_back_url_section(chat_id)
    elif data == b"change_bio":
        ctx.user_states[chat_id] = "WAITING_BIO"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_bio_prompt'))
    elif data == b"create_personal_channel":
        if not ctx.userbots:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_no_accs'))
            return
        ctx.user_states[chat_id] = "WAITING_CHANNEL_NAME"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_name_prompt'))
    elif data == b"change_photo":
        if not ctx.userbots:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_no_accs'))
            return
        ctx.user_states[chat_id] = "WAITING_CHANGE_PHOTO"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_photo_prompt'))
    elif data == b"clear_all_chats":
        if not ctx.userbots:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_no_accs'))
            return
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_clear_chats_progress').format(n=len(ctx.userbots)))
        total_deleted = 0
        for acc in ctx.userbots:
            deleted = await clear_account_chats(acc)
            total_deleted += deleted
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_clear_chats_ok').format(total=total_deleted))
        await asyncio.sleep(2)
        await show_back_url_section(chat_id)
    elif data == b"url_proxy_connect":
        if not SOCKS5_AVAILABLE:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_no_lib'),
                                     [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"back_to_accounts")]])
            return
        ctx.user_states[chat_id] = "WAITING_URL_PROXY"
        current = format_active_proxies(ctx.url_proxies, chat_id)
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_prompt').format(current=current))
    elif data == b"url_proxy_delete_all":
        ctx.url_proxies.clear()
        if ctx.userbots:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_del_progress'))
            ok, fail = await apply_proxies_to_accounts(ctx, ctx.userbots, [], sessions_dir=ctx._sessions_dir)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_del_reconnect_ok').format(ok=ok, fail=fail),
                                     [[Button.inline(_T(chat_id, 'r1_btn_back_main'), b"back_to_main")]])
        else:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_del_ok'), [[Button.inline(_T(chat_id, 'r1_btn_back_main'), b"back_to_main")]])
    elif data == b"grp_proxy_connect":
        if not SOCKS5_AVAILABLE:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_no_lib'),
                                     [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]])
            return
        ctx.user_states[chat_id] = "WAITING_GRP_PROXY"
        current = format_active_proxies(ctx.group_proxies, chat_id)
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_prompt').format(current=current))
    elif data == b"grp_proxy_delete_all":
        ctx.group_proxies.clear()
        if ctx.group_userbots:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_del_progress'))
            ok, fail = await apply_proxies_to_accounts(ctx, ctx.group_userbots, [], sessions_dir=ctx._group_sessions_dir)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_del_reconnect_ok').format(ok=ok, fail=fail),
                                     [[Button.inline(_T(chat_id, 'r1_btn_back_main'), b"back_to_main")]])
        else:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_proxy_del_ok'), [[Button.inline(_T(chat_id, 'r1_btn_back_main'), b"back_to_main")]])
    elif data == b"open_group_menu":
        await show_group_accounts_menu(chat_id)
    elif data == b"grp_manage_accounts":
        await show_grp_manage_accounts_menu(chat_id)
    elif data == b"grp_manage_params":
        await show_grp_manage_params_menu(chat_id)
    elif data == b"g_back_to_accounts":
        # Кнопка back на manage-сторінці групової реклами завжди веде на рівень
        # вище (top group menu). Post-action повертається на manage через
        # show_back_grp_section у обробниках стану.
        await show_group_accounts_menu(chat_id)
    elif data == b"g_delete_account":
        ctx.user_states[chat_id] = "G_WAITING_DELETE_NUM"
        acc_list = ""
        for i, acc in enumerate(ctx.group_userbots):
            acc_list += f"  №{i+1} — {acc.get('name', acc['phone'])}\n"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_delete_prompt').format(acc_list=acc_list))
    elif data == b"g_rename_accounts":
        ctx.user_states[chat_id] = "G_WAITING_RENAME_NAMES"
        pool_info = f"{len(ctx.group_bot_settings['name_pool'])}\n\n" if ctx.group_bot_settings["name_pool"] else ""
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_rename_prompt').format(pool_info=pool_info))
    elif data == b"g_delete_avatars":
        if not ctx.group_userbots:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_no_accs'))
            return
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_del_avatar_progress'))
        total = 0
        for acc in ctx.group_userbots:
            try:
                photos = await acc["client"](GetUserPhotosRequest(user_id="me", offset=0, max_id=0, limit=100))
                if photos.photos:
                    await acc["client"](DeletePhotosRequest(id=photos.photos))
                    total += len(photos.photos)
            except:
                pass
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_avatar_ok').format(total=total))
        await asyncio.sleep(1)
        await show_back_grp_section(chat_id)
    elif data == b"g_change_bio":
        ctx.user_states[chat_id] = "G_WAITING_BIO"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_bio_prompt'))
    elif data == b"g_change_photo":
        if not ctx.group_userbots:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_no_accs'))
            return
        ctx.user_states[chat_id] = "G_WAITING_CHANGE_PHOTO_ZIP"
        pool_info = f"📦 {len(ctx.group_bot_settings['avatar_pool'])}\n\n" if ctx.group_bot_settings["avatar_pool"] else ""
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_avatar_prompt').format(pool_info=pool_info))
    elif data == b"g_clear_all_chats":
        if not ctx.group_userbots:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_no_accs'))
            return
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_clear_chats_progress').format(n=len(ctx.group_userbots)))
        total_deleted = 0
        for acc in ctx.group_userbots:
            deleted = await clear_account_chats(acc)
            total_deleted += deleted
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_clear_chats_ok').format(total=total_deleted))
        await asyncio.sleep(2)
        await show_back_grp_section(chat_id)

    # ================= УПРАВЛІННЯ КАНАЛАМИ =================
    elif data == b"manage_channels":
        await show_channels_menu(chat_id)
    elif data == b"create_folder":
        ctx.user_states[chat_id] = "WAITING_FOLDER_NAME"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_folder_prompt'))
    elif data == b"delete_folder":
        folders = list(ctx.bot_settings.get("channels", {}).keys())
        if not folders:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_no_folders'),
                                     [[Button.inline(_T(chat_id, 'r1_btn_back_short'), b"manage_channels")]])
            return
        ctx.user_states[chat_id] = "WAITING_DELETE_FOLDER"
        folder_list = "\n".join(f"• {f}" for f in folders)
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_del_folder_list').format(folders=folder_list))
    elif data.startswith(b"view_folder_"):
        folder_name = data[len(b"view_folder_"):].decode("utf-8", errors="replace")
        await show_channels_folder(chat_id, folder_name)
    elif data.startswith(b"add_chan_"):
        folder_name = data[len(b"add_chan_"):].decode("utf-8", errors="replace")
        ctx.user_states[chat_id] = f"WAITING_CHANNEL_LINK_{folder_name}"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_ch_add_link_prompt').format(name=folder_name))
    elif data.startswith(b"del_chan_"):
        rest = data[len(b"del_chan_"):].decode("utf-8", errors="replace")
        sep_idx = rest.find("|")
        if sep_idx != -1:
            folder_name = rest[:sep_idx]
            chan_link = rest[sep_idx + 1:]
            ch_list = ctx.bot_settings["channels"].get(folder_name, [])
            if chan_link in ch_list:
                ch_list.remove(chan_link)
                ctx.bot_settings["channels"][folder_name] = ch_list
                save_settings(ctx)
        await show_channels_folder(chat_id, folder_name if sep_idx != -1 else "")

# ================= ШІ ДЛЯ КОМЕНТАРІВ =================
async def generate_ai_reply(ctx: UserContext, post_text):
    _ensure_genai()
    models = ["gemini-1.5-flash-latest", "gemini-1.5-flash", "gemini-1.0-pro"]
    for m in models:
        try:
            model = genai.GenerativeModel(m)
            prompt = (f"Згенеруй короткий коментар для Telegram. Ось пост: '{post_text}'.\n\n"
                      f"Твоє завдання та стиль: {ctx.bot_settings['rules_text']}.\n"
                      f"Пиши тільки текст коментаря, без лапок.")
            resp = await model.generate_content_async(prompt)
            return resp.text.strip()
        except:
            continue
    return ctx.bot_settings["rules_text"]

def post_matches_keywords(ctx: UserContext, text: str) -> bool:
    keywords = ctx.bot_settings.get("keywords", [])
    if not keywords:
        return True
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return True
    return False

# ================= ЦИКЛ НАГАДУВАНЬ =================
async def post_cycle_task(ctx: UserContext, ubot, channel_id, post_id, discussion_chat, discussion_reply_id, last_bot_msg, ai_reply_text):
    current_main_msg = last_bot_msg
    while True:
        if ctx.bot_settings["reminders"]:
            await asyncio.sleep(ctx.bot_settings["reminder_delay"])
            if ctx.latest_channel_posts.get(channel_id) != post_id:
                break
            rem_name = random.choice(list(ctx.bot_settings["reminders"].keys()))
            try:
                await ubot.send_message(discussion_chat, ctx.bot_settings["reminders"][rem_name], reply_to=current_main_msg.id)
            except:
                pass

        if ctx.bot_settings["cycle_delay"] <= 0:
            break
        await asyncio.sleep(ctx.bot_settings["cycle_delay"])
        if ctx.latest_channel_posts.get(channel_id) != post_id:
            break

        try:
            current_main_msg = await ubot.send_message(discussion_chat, ai_reply_text, reply_to=discussion_reply_id)
        except:
            break

def setup_userbot_handler(ctx: UserContext, ubot: TelegramClient, phone: str, my_id: int):
    @ubot.on(events.NewMessage())
    async def auto_reply(event):
        try:
            msg = event.message
            if getattr(msg, "out", False):
                return
            if event.is_channel and not getattr(event, 'is_group', False):
                post_id_str = f"{event.chat_id}_{msg.id}"
                ctx.latest_channel_posts[event.chat_id] = post_id_str

                try:
                    await asyncio.sleep(random.uniform(1.0, 5.0))
                    await ubot.send_read_acknowledge(event.chat_id, max_id=msg.id)
                except Exception as e:
                    print(f"[{phone}] Не вдалося відправити read acknowledge: {e}")

                text = (msg.message or "").strip()

                if not post_matches_keywords(ctx, text):
                    try:
                        await asyncio.sleep(random.uniform(2.0, 10.0))
                        await ubot(SendReactionRequest(
                            peer=await event.get_input_chat(),
                            msg_id=msg.id,
                            reaction=[ReactionEmoji(emoticon=random.choice(["❤", "🙏"]))]
                        ))
                        print(f"[{phone}] Пост {msg.id} не містить ключових слів, надіслана емодзі-реакція")
                    except Exception as e:
                        print(f"[{phone}] Не вдалося поставити реакцію на пост {msg.id}: {e}")
                    return

                try:
                    await asyncio.sleep(random.uniform(2.0, 10.0))
                    await ubot(SendReactionRequest(
                        peer=await event.get_input_chat(),
                        msg_id=msg.id,
                        reaction=[ReactionEmoji(emoticon=random.choice(["❤", "🙏"]))]
                    ))
                except Exception as e:
                    print(f"[{phone}] Не вдалося поставити реакцію на пост {msg.id}: {e}")

                if not ctx.bot_settings["bot_enabled"] or not ctx.userbots:
                    print(f"[{phone}] Бот вимкнений або немає акаунтів")
                    return
                if post_id_str in ctx.processed_posts:
                    print(f"[{phone}] Пост {msg.id} вже оброблено")
                    return
                ctx.processed_posts.add(post_id_str)
                if len(ctx.processed_posts) > 1000:
                    ctx.processed_posts.clear()
                    ctx.processed_posts.add(post_id_str)

                post_text_for_ai = text if text else "цікавий пост"
                ai_reply_text = None
                success = False
                sent_msg = None
                successful_client = None
                discussion_chat = None
                discussion_msg = None

                # Sticky-active: один акаунт працює, поки не впаде; тоді fallback
                # на наступний, і саме він стає новим активним.
                for i in range(len(ctx.userbots)):
                    idx = (ctx.active_commenter_idx + i) % len(ctx.userbots)
                    current_client = ctx.userbots[idx]["client"]
                    bot_phone = ctx.userbots[idx]["phone"]
                    try:
                        discussion = await current_client(GetDiscussionMessageRequest(
                            peer=event.chat_id,
                            msg_id=msg.id
                        ))
                        discussion_msg = discussion.messages[0]
                        discussion_chat = discussion.chats[0]

                        if not ai_reply_text:
                            try:
                                ai_reply_text = await generate_ai_reply(ctx, post_text_for_ai)
                            except Exception as e:
                                print(f"[{bot_phone}] Помилка генерації AI: {e}")
                                ai_reply_text = ctx.bot_settings["rules_text"]

                        await asyncio.sleep(random.uniform(2.0, 6.0))
                        sent_msg = await current_client.send_message(
                            discussion_chat,
                            ai_reply_text,
                            reply_to=discussion_msg.id
                        )
                        # Зберігаємо ЦЕЙ акаунт як активний; зміщуємо лише якщо
                        # довелось робити fallback (i > 0 означає, що
                        # попередньо активний акаунт упав).
                        if i > 0:
                            ctx.active_commenter_idx = idx
                            print(f"[{bot_phone}] Активний акаунт переключено на цього після fallback")
                        success = True
                        successful_client = current_client
                        print(f"[{bot_phone}] Успішно надіслано коментар до поста {msg.id}")
                        break
                    except Exception as e:
                        print(f"[{bot_phone}] Не зміг обробити пост {msg.id}: {e}")

                if success and sent_msg and successful_client and discussion_chat and discussion_msg:
                    asyncio.create_task(post_cycle_task(
                        ctx, successful_client,
                        event.chat_id,
                        post_id_str,
                        discussion_chat,
                        discussion_msg.id,
                        sent_msg,
                        ai_reply_text
                    ))
                else:
                    print(f"[{phone}] Жоден акаунт не зміг надіслати коментар до поста {msg.id} в каналі {event.chat_id}")
        except Exception as e:
            print(f"[{phone}] Критична помилка в auto_reply: {e}")

# ================= СТАТИЧНА ІМІТАЦІЯ ДІАЛОГІВ =================
async def play_static_dialogue(ctx: UserContext, a, b):
    dialogue = random.choice(STATIC_DIALOGUES)
    phone_b = b["phone"] if b["phone"].startswith("+") else "+" + b["phone"]
    phone_a = a["phone"] if a["phone"].startswith("+") else "+" + a["phone"]
    entity_a_sees_b = None
    entity_b_sees_a = None
    try:
        entity_a_sees_b = await a["client"].get_entity(b["id"])
    except:
        try:
            entity_a_sees_b = await a["client"].get_entity(phone_b)
        except Exception as e:
            print(f"Не вдалось отримати entity для {b['phone']} з боку {a['phone']}: {e}")
    try:
        entity_b_sees_a = await b["client"].get_entity(a["id"])
    except:
        try:
            entity_b_sees_a = await b["client"].get_entity(phone_a)
        except Exception as e:
            print(f"Не вдалось отримати entity для {a['phone']} з боку {b['phone']}: {e}")

    if not entity_a_sees_b or not entity_b_sees_a:
        print(f"❌ Неможливо розпочати діалог між {a['phone']} та {b['phone']}: entity не знайдено.")
        return

    print(f"💬 Початок статичного діалогу: {a['phone']} та {b['phone']}")
    try:
        for i, text in enumerate(dialogue):
            sender = a if i % 2 == 0 else b
            entity = entity_a_sees_b if i % 2 == 0 else entity_b_sees_a
            try:
                async with sender["client"].action(entity, 'typing'):
                    await asyncio.sleep(random.uniform(2.0, 5.0))
                await sender["client"].send_message(entity, text)
            except AuthKeyDuplicatedError:
                print(f"❌ [AuthKeyDuplicated] {sender['phone']} — зупиняємо діалог, сесія дублюється!")
                return
            except Exception as e:
                print(f"Помилка надсилання повідомлення в діалозі ({sender['phone']}): {e}")
            await asyncio.sleep(random.uniform(5.0, 15.0))
        print(f"🏁 Статичний діалог між {a['phone']} та {b['phone']} успішно завершено.")
    except AuthKeyDuplicatedError:
        print(f"❌ [AuthKeyDuplicated] Діалог перервано — сесія відкрита в іншому місці!")
    except Exception as e:
        print(f"Помилка під час діалогу: {e}")

async def _check_client_alive(ctx: UserContext, acc: dict) -> bool:
    try:
        if not acc["client"].is_connected():
            await acc["client"].connect()
        await acc["client"].get_me()
        return True
    except AuthKeyDuplicatedError:
        print(f"❌ [AuthKeyDuplicated] Акаунт {acc.get('phone','?')} — сесія відкрита в іншому місці! Відключаємо.")
        try:
            await acc["client"].disconnect()
        except:
            pass
        if acc in ctx.userbots:
            ctx.userbots.remove(acc)
        if acc in ctx.group_userbots:
            ctx.group_userbots.remove(acc)
        return False
    except Exception:
        return False

async def chat_simulation_loop(ctx: UserContext):
    await asyncio.sleep(30)
    while True:
        try:
            alive_bots = []
            for acc in list(ctx.userbots):
                if await _check_client_alive(ctx, acc):
                    alive_bots.append(acc)
            if len(alive_bots) >= 2:
                await init_mutual_contacts(ctx)
                all_pairs = list(itertools.combinations(alive_bots, 2))
                random.shuffle(all_pairs)
                for a, b in all_pairs:
                    await play_static_dialogue(ctx, a, b)
                    await asyncio.sleep(random.randint(60, 120))
        except Exception as e:
            print(f"[ChatSim] Помилка: {e}")
        await asyncio.sleep(random.randint(72000, 86400))

# ================= ПРОКСІ: ПАРСИНГ ТА ПЕРЕПІДКЛЮЧЕННЯ =================
def parse_socks5_proxy(line: str):
    line = line.strip()
    if not line:
        return None
    try:
        if line.lower().startswith("socks5://"):
            line_clean = line[len("socks5://"):]
            if "@" in line_clean:
                creds, hostport = line_clean.rsplit("@", 1)
                username, password = creds.split(":", 1) if ":" in creds else (creds, "")
            else:
                hostport = line_clean
                username = password = ""
            host, port_str = hostport.rsplit(":", 1)
            return {"host": host, "port": int(port_str), "username": username, "password": password, "raw": line}

        parts = line.split(":")
        if len(parts) == 4:
            host, port_str, username, password = parts
            return {"host": host, "port": int(port_str), "username": username, "password": password, "raw": line}
        elif len(parts) == 2:
            host, port_str = parts
            return {"host": host, "port": int(port_str), "username": "", "password": "", "raw": line}
    except Exception as e:
        print(f"[Proxy parse] Помилка '{line}': {e}")
    return None

async def reconnect_account_with_proxy(acc: dict, proxy_dict, sessions_dir=None) -> bool:
    phone = acc["phone"]
    try:
        await acc["client"].disconnect()
    except Exception:
        pass
    proxy = None
    if proxy_dict and SOCKS5_AVAILABLE:
        host = proxy_dict["host"]
        port = proxy_dict["port"]
        user = proxy_dict.get("username", "")
        pwd  = proxy_dict.get("password", "")
        if user:
            proxy = (_socks_module.SOCKS5, host, port, True, user, pwd)
        else:
            proxy = (_socks_module.SOCKS5, host, port)
    sess_name = os.path.join(sessions_dir, phone) if sessions_dir else phone
    try:
        new_client = TelegramClient(sess_name, API_ID, API_HASH, proxy=proxy)
        await new_client.connect()
        if await new_client.is_user_authorized():
            acc["client"] = new_client
            return True
        else:
            await new_client.disconnect()
            return False
    except Exception as e:
        print(f"[Proxy reconnect] {phone}: {e}")
        return False

async def apply_proxies_to_accounts(ctx: UserContext, accounts_list: list, proxies_list: list, sessions_dir=None):
    ok = 0
    fail = 0
    for i, acc in enumerate(accounts_list):
        proxy = proxies_list[i % len(proxies_list)] if proxies_list else None
        success = await reconnect_account_with_proxy(acc, proxy, sessions_dir)
        if success:
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(1)
    return ok, fail

def format_active_proxies(proxies_list: list, uid: int = 0) -> str:
    if not proxies_list:
        return _T(uid, 'r1_no_active_proxies')
    lines = []
    for i, p in enumerate(proxies_list, 1):
        if p.get("username"):
            lines.append(f"№{i} {p['host']}:{p['port']} (user: {p['username']})")
        else:
            lines.append(f"№{i} {p['host']}:{p['port']}")
    return "\n".join(lines)

# ================= ФІНАЛІЗАЦІЯ АКАУНТА (URL) =================
async def finalize_auth(ctx: UserContext, ubot: TelegramClient, phone: str, chat_id=None, quiet=False):
    # Дедуп за номером телефону
    if any(a.get('phone') == phone for a in ctx.userbots):
        if chat_id and not quiet:
            await ctx.send_and_track(
                chat_id,
                f"↩️ Акаунт {phone} вже доданий — пропускаю."
            )
        try:
            await ubot.disconnect()
        except Exception:
            pass
        try:
            sess_path = os.path.join(ctx._sessions_dir, f"{phone}.session")
            if os.path.exists(sess_path):
                os.remove(sess_path)
        except Exception:
            pass
        return False

    if len(ctx.userbots) >= 25:
        if chat_id and not quiet:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_acc_limit'))
        try:
            await ubot.disconnect()
        except Exception:
            pass
        return False
    me = await ubot.get_me()
    # Дедуп за Telegram user id (на випадок, якщо номер змінили, а акаунт той самий)
    if any(a.get('id') == me.id for a in ctx.userbots):
        if chat_id and not quiet:
            await ctx.send_and_track(
                chat_id,
                f"↩️ Акаунт {me.first_name} вже доданий під іншим номером — пропускаю."
            )
        try:
            await ubot.disconnect()
        except Exception:
            pass
        try:
            sess_path = os.path.join(ctx._sessions_dir, f"{phone}.session")
            if os.path.exists(sess_path):
                os.remove(sess_path)
        except Exception:
            pass
        return False
    ctx.userbots.append({"phone": phone, "client": ubot, "name": me.first_name, "id": me.id})
    setup_userbot_handler(ctx, ubot, phone, me.id)
    # Запускаємо отримання подій для цього клієнта
    asyncio.create_task(ubot.run_until_disconnected())
    asyncio.create_task(init_mutual_contacts(ctx))
    await distribute_and_join_all_channels(ctx)
    save_settings(ctx)
    if not quiet and chat_id:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_acc_ok').format(name=me.first_name))
        await asyncio.sleep(1)
        await show_accounts_menu(chat_id)

# ================= ДВИГУН МОНІТОРИНГУ =================
def _setup_monitoring_on_account(ctx: UserContext, acc: dict):
    phone = acc["phone"]
    if phone in ctx._monitoring_handlers_registered:
        return
    ctx._monitoring_handlers_registered.add(phone)
    client = acc["client"]

    async def _join_monitoring_channel():
        mon_ch = ctx.group_bot_settings.get("monitoring_channel")
        if not mon_ch:
            return
        try:
            username = mon_ch.strip().split("/")[-1].lstrip("@")
            if username.startswith("+"):
                from telethon.tl.functions.messages import ImportChatInviteRequest
                await client(ImportChatInviteRequest(username[1:]))
            else:
                entity = await client.get_entity(username)
                await client(JoinChannelRequest(entity))
            print(f"[Monitoring] ✅ {phone} підписався на канал {mon_ch}")
        except Exception as e:
            print(f"[Monitoring] ℹ️ {phone} підписка на канал: {e}")

    asyncio.get_event_loop().create_task(_join_monitoring_channel())

    @client.on(events.NewMessage())
    async def _monitoring_handler(event):
        mon_id = ctx.group_bot_settings.get("monitoring_channel_id")
        if not mon_id:
            return
        if not ctx.group_bot_settings.get("monitoring_active"):
            return
        try:
            event_chat_id = event.chat_id
            mon_id_neg = int(f"-100{abs(mon_id)}") if mon_id > 0 else mon_id
            if event_chat_id != mon_id and event_chat_id != mon_id_neg:
                if abs(event_chat_id) != abs(mon_id):
                    return
        except:
            return
        if getattr(event.message, "out", False):
            return
        msg_text = (event.message.message or "").strip()
        if not msg_text:
            return
        print(f"[Monitoring] 📨 Повідомлення з каналу ({phone}): {msg_text[:80]}")
        asyncio.create_task(_process_monitoring_message(ctx, acc, event.message, msg_text))

def _city_variants(city: str) -> list:
    c = city.lower()
    variants = {c}
    v = c.replace('ї', 'є')
    variants.add(v)
    variants.add(v[:-1] if len(v) > 3 else v)
    variants.add(c.replace('і', 'о'))
    variants.add(c.replace('і', 'а'))
    variants.add(c.replace('и', 'о'))
    if len(c) > 4:
        variants.add(c[:-1])
    if len(c) > 5:
        variants.add(c[:-2])
    return list(variants)

async def _get_chat_entity(acc_client, chat: dict):
    link = chat.get("link", "")
    stored_id = chat.get("id")
    if not ("t.me/+" in link or "t.me/joinchat/" in link):
        uname = link.split("/")[-1].lstrip("@").split("?")[0]
        try:
            entity = await acc_client.get_entity(uname)
            chat["id"] = entity.id
            chat["title"] = entity.title
            return entity
        except Exception as e:
            print(f"[Monitoring] ⚠️ get_entity(username) {uname}: {e}")
    if stored_id:
        for try_id in [stored_id, -stored_id, int(f"-100{abs(stored_id)}")]:
            try:
                entity = await acc_client.get_entity(try_id)
                return entity
            except:
                pass
    if "t.me/+" in link or "t.me/joinchat/" in link:
        invite_hash = link.split("/")[-1].replace("+", "")
        try:
            from telethon.tl.functions.messages import ImportChatInviteRequest
            result = await acc_client(ImportChatInviteRequest(invite_hash))
            if hasattr(result, "chats") and result.chats:
                entity = result.chats[0]
                chat["id"] = entity.id
                chat["title"] = entity.title
                return entity
        except Exception as e:
            if "already" in str(e).lower() or "member" in str(e).lower():
                if stored_id:
                    try:
                        return await acc_client.get_entity(int(f"-100{abs(stored_id)}"))
                    except:
                        pass
                stored_title = chat.get("title", "")
                if stored_title:
                    async for dialog in acc_client.iter_dialogs(limit=300):
                        if dialog.title and dialog.title.lower() == stored_title.lower():
                            chat["id"] = dialog.entity.id
                            return dialog.entity
            print(f"[Monitoring] ⚠️ Не вдалося отримати entity для {link}: {e}")
    return None

async def _repost_to_chats(ctx: UserContext, target_chats: list, message, msg_text: str):
    total = len(target_chats)
    sent = 0
    for i, chat in enumerate(target_chats):
        if not ctx.group_userbots:
            print("[Monitoring] ❌ Немає акаунтів для відправки!")
            break
        acc = ctx.group_userbots[i % len(ctx.group_userbots)]
        entity = await _get_chat_entity(acc["client"], chat)
        if entity is None:
            print(f"[Monitoring] ❌ Пропускаємо {chat.get('title', chat.get('link','?'))} — entity не знайдено")
            continue
        title = chat.get("title", str(entity.id))
        try:
            await acc["client"].forward_messages(entity, message)
            print(f"[Monitoring] ✅ Репост у {title}")
            sent += 1
        except Exception as e:
            try:
                await acc["client"].send_message(entity, msg_text)
                print(f"[Monitoring] ✅ Надіслано текстом у {title}")
                sent += 1
            except Exception as e2:
                print(f"[Monitoring] ❌ {title}: {e2}")
        if i < total - 1:
            await asyncio.sleep(3)
    return sent

async def _process_monitoring_message(ctx: UserContext, sender_acc, message, msg_text: str):
    # Дедуплікація: лише один акаунт обробляє одне повідомлення
    if message.id in ctx._processed_monitoring_msgs:
        return
    ctx._processed_monitoring_msgs.add(message.id)
    if len(ctx._processed_monitoring_msgs) > 200:
        ctx._processed_monitoring_msgs.discard(min(ctx._processed_monitoring_msgs))

    ctx._last_monitoring_msg_id = message.id
    current_msg_id = message.id

    text_lower = msg_text.lower()
    found_oblasts: set[str] = set()
    # Використовуємо варіанти форм міст для розпізнавання відмінків ("полтаву", "харкові" тощо)
    for city_lower, oblast in UA_CITY_TO_REGION.items():
        for variant in _city_variants(city_lower):
            if variant in text_lower:
                found_oblasts.add(oblast)
                break

    all_chats = ctx.group_bot_settings["group_chats"]
    if not all_chats:
        print("[Monitoring] ⚠️ Немає груп у базі для репосту!")
        return

    print(f"[Monitoring] 🔍 Знайдені регіони: {found_oblasts or '(не знайдено — репост всюди)'}")

    if found_oblasts:
        target_chats = []
        for chat in all_chats:
            title_lower = chat.get("title", "").lower()
            link_lower = chat.get("link", "").lower()
            matched = False
            for oblast in found_oblasts:
                for city in UA_REGIONS.get(oblast, []):
                    for variant in _city_variants(city):
                        if variant in title_lower or variant in link_lower:
                            if chat not in target_chats:
                                target_chats.append(chat)
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    break
        if not target_chats:
            print(f"[Monitoring] ℹ️ Груп з назвами регіону не знайдено → репост у всі {len(all_chats)} чатів")
            target_chats = list(all_chats)
        else:
            titles = ", ".join(c.get("title", c.get("link","?"))[:20] for c in target_chats)
            print(f"[Monitoring] 🎯 Знайдено {len(target_chats)} груп: {titles}")
    else:
        target_chats = list(all_chats)
        print(f"[Monitoring] 📢 Репост у всі {len(target_chats)} чатів (регіон не розпізнано)")

    repeat_count = ctx.group_bot_settings.get("repost_repeat", 5)
    interval = ctx.group_bot_settings.get("repost_interval", 180)

    for cycle in range(repeat_count):
        if ctx._last_monitoring_msg_id != current_msg_id:
            print(f"[Monitoring] ⏩ Нове повідомлення в каналі → зупиняємо цикл репостів")
            break
        if cycle > 0:
            print(f"[Monitoring] ⏳ Чекаємо {interval}с перед циклом {cycle+1}/{repeat_count}...")
            await asyncio.sleep(interval)
            if ctx._last_monitoring_msg_id != current_msg_id:
                print(f"[Monitoring] ⏩ Нове повідомлення → зупиняємо цикл")
                break
        sent = await _repost_to_chats(ctx, target_chats, message, msg_text)
        print(f"[Monitoring] 🔄 Цикл {cycle+1}/{repeat_count} завершено (відправлено: {sent}/{len(target_chats)})")

# ================= ФІНАЛІЗАЦІЯ АКАУНТА (реклама у групах) =================
async def finalize_group_auth(ctx: UserContext, ubot: TelegramClient, phone: str, chat_id=None, quiet=False):
    # Дедуп за номером телефону
    if any(a.get('phone') == phone for a in ctx.group_userbots):
        if chat_id and not quiet:
            await ctx.send_and_track(
                chat_id,
                f"↩️ Акаунт {phone} вже доданий у групову рекламу — пропускаю."
            )
        try:
            await ubot.disconnect()
        except Exception:
            pass
        try:
            sess_path = os.path.join(ctx._group_sessions_dir, f"{phone}.session")
            if os.path.exists(sess_path):
                os.remove(sess_path)
        except Exception:
            pass
        return False

    if len(ctx.group_userbots) >= 25:
        if chat_id and not quiet:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r1_acc_limit'))
        try:
            await ubot.disconnect()
        except Exception:
            pass
        return False
    me = await ubot.get_me()
    # Дедуп за Telegram user id
    if any(a.get('id') == me.id for a in ctx.group_userbots):
        if chat_id and not quiet:
            await ctx.send_and_track(
                chat_id,
                f"↩️ Акаунт {me.first_name} вже доданий у групову рекламу під іншим номером — пропускаю."
            )
        try:
            await ubot.disconnect()
        except Exception:
            pass
        try:
            sess_path = os.path.join(ctx._group_sessions_dir, f"{phone}.session")
            if os.path.exists(sess_path):
                os.remove(sess_path)
        except Exception:
            pass
        return False
    acc = {"phone": phone, "client": ubot, "name": me.first_name, "id": me.id}
    ctx.group_userbots.append(acc)
    if ctx.group_bot_settings.get("monitoring_channel_id"):
        _setup_monitoring_on_account(ctx, acc)
        # Запускаємо отримання подій для групового клієнта
        asyncio.create_task(ubot.run_until_disconnected())
        ctx.group_bot_settings["monitoring_active"] = True
        print(f"[GroupAuth] ✅ {phone} підключено до моніторингу каналу {ctx.group_bot_settings.get('monitoring_channel')}")
    if not quiet and chat_id:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_acc_ok').format(name=me.first_name))
        await asyncio.sleep(1)
        await show_group_accounts_menu(chat_id)

# ================= ПЕРЕВІРКА SESSION ФАЙЛУ =================
def is_telethon_session(path: str) -> bool:
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions';")
        result = cursor.fetchone() is not None
        conn.close()
        return result
    except:
        return False

# ================= ЗАПУСК (пошук перенесено у rukla3) =================


# ================= ЗАПУСК =================
async def _load_all_sessions():
    """Завантажує всі сесії всіх користувачів."""
    for user_dir in os.listdir(USERS_DATA_DIR):
        user_path = os.path.join(USERS_DATA_DIR, user_dir)
        if not os.path.isdir(user_path):
            continue
        try:
            uid = int(user_dir)
        except:
            continue
        ctx = get_ctx(uid)
        load_settings(ctx)
        # URL сесії
        url_dir = ctx._sessions_dir
        if os.path.isdir(url_dir):
            for file in os.listdir(url_dir):
                if not file.endswith(".session"):
                    continue
                sess_path = os.path.join(url_dir, file)
                if not is_telethon_session(sess_path):
                    continue
                phone = file.replace(".session", "")
                sess_path = os.path.join(url_dir, file)
                if not can_write(sess_path):
                    print(f"[!] URL session skip (read-only): {sess_path}")
                    continue
                try:
                    ubot = TelegramClient(os.path.join(url_dir, phone), API_ID, API_HASH)
                    await ubot.connect()
                    if await ubot.is_user_authorized():
                        await finalize_auth(ctx, ubot, phone, quiet=True)
                        print(f"[rukla1] User {uid} URL restored: {phone}")
                    else:
                        await ubot.disconnect()
                except Exception as e:
                    print(f"[rukla1] User {uid} URL session {phone}: {e}")

        # Групові сесії
        group_dir = ctx._group_sessions_dir
        if os.path.isdir(group_dir):
            for file in os.listdir(group_dir):
                if not file.endswith(".session"):
                    continue
                sess_path = os.path.join(group_dir, file)
                if not is_telethon_session(sess_path):
                    continue
                phone = file.replace(".session", "")
                try:
                    sess_name = os.path.join(group_dir, phone)
                    ubot = TelegramClient(sess_name, API_ID, API_HASH)
                    await ubot.connect()
                    if await ubot.is_user_authorized():
                        await finalize_group_auth(ctx, ubot, phone, quiet=True)
                        print(f"[rukla1] User {uid} GROUP restored: {phone}")
                    else:
                        await ubot.disconnect()
                except Exception as e:
                    print(f"[rukla1] User {uid} GROUP session {phone}: {e}")

    # Запускаємо цикл симуляції для кожного користувача з акаунтами
    for ctx in user_contexts.values():
        if ctx.userbots:
            asyncio.create_task(chat_simulation_loop(ctx))

async def main():
    print("[rukla1] startup...")
    await _load_all_sessions()
    print("[rukla1] startup complete")
    while True:
        await asyncio.sleep(3600)

# ============================================================
# Інтеграція з rukla.py (telebot)
# ============================================================
import threading as _threading

_loop = None
_loop_thread = None
_telebot_bot = None

def init_async_loop():
    global _loop, _loop_thread
    if _loop is not None:
        return
    _loop = asyncio.new_event_loop()
    def _run():
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(_startup())
        _loop.run_forever()
    _loop_thread = _threading.Thread(target=_run, daemon=True, name="rukla1-loop")
    _loop_thread.start()

async def _startup():
    try:
        await _load_all_sessions()
    except Exception as e:
        print(f"[rukla1] load sessions failed: {e}")
    print(f"[rukla1] startup done")

def _run_on_rukla1_loop(coro):
    if _loop is None or not _loop.is_running():
        raise RuntimeError("rukla1 event loop is not running")
    return asyncio.run_coroutine_threadsafe(coro, _loop)

_RUKLA1_CALLBACKS_EXACT = frozenset({
    "open_accounts_menu", "back_to_main", "back_to_accounts",
    "url_manage_accounts", "url_manage_params",
    "open_group_menu", "g_back_to_accounts",
    "grp_manage_accounts", "grp_manage_params",
    "search_channels", "delete_account", "rename_accounts", "delete_avatars",
    "delete_usernames", "g_delete_usernames",
    "change_bio", "create_personal_channel", "change_photo", "set_keywords",
    "bot_status", "bot_enable", "bot_disable",
    "manage_styles", "create_style", "delete_style",
    "manage_reminders", "create_rem", "delete_rem", "set_rem_delay",
    "manage_cycle", "set_cycle_delay",
    "manage_channels", "create_folder", "delete_folder",
    "clear_all_chats", "url_proxy_connect",
    "g_search_chats", "g_delete_account", "g_rename_accounts", "g_delete_avatars",
    "g_change_bio", "g_change_photo", "g_clear_all_chats",
    "g_set_monitoring", "g_monitoring_stop", "g_monitoring_start",
    "g_manage_groups", "g_bot_status",
    "g_bot_enable", "g_bot_disable",
    "g_add_group", "g_del_group", "g_set_interval", "g_set_repeat",
    "grp_proxy_connect", "grp_proxy_delete_all",
    "url_proxy_delete_all",
})
_RUKLA1_CALLBACK_PREFIXES = ("view_style_", "view_folder_", "add_chan_", "del_chan_", "g_view_group_")

def is_rukla1_callback(data):
    if not data:
        return False
    if data in _RUKLA1_CALLBACKS_EXACT:
        return True
    return any(data.startswith(p) for p in _RUKLA1_CALLBACK_PREFIXES)

_users_in_rukla1 = set()

def has_text_pending(chat_id):
    return chat_id in _users_in_rukla1

def has_file_pending(chat_id):
    return chat_id in _users_in_rukla1

def cancel(chat_id):
    """Reset rukla1 state for a user — called from rukla.py on /start or back navigation."""
    _users_in_rukla1.discard(chat_id)
    if chat_id in user_contexts:
        ctx = user_contexts[chat_id]
        ctx.user_states[chat_id] = None
        ctx.nav_msg_id.pop(chat_id, None)

def _has_file_pending_old(chat_id):
    return chat_id in _users_in_rukla1

class _CallbackEvent:
    def __init__(self, chat_id, data_bytes):
        self.chat_id = chat_id
        self.data = data_bytes
    async def answer(self):
        return

class _TextEvent:
    def __init__(self, msg):
        self.sender_id = msg.from_user.id
        self.chat_id = msg.chat.id
        self.raw_text = msg.text or ""
        self.id = msg.message_id

class _FakeFileInfo:
    def __init__(self, name, mime_type):
        self.name = name
        self.mime_type = mime_type

class _FakeMessageInner:
    def __init__(self, caption, entities):
        self.message = caption or ""
        self.entities = entities or []

class _MediaEvent:
    def __init__(self, telebot_bot, msg):
        self._tb = telebot_bot
        self._msg = msg
        self.sender_id = msg.from_user.id
        self.chat_id = msg.chat.id
        self.id = msg.message_id
        if getattr(msg, "document", None):
            self.file = _FakeFileInfo(msg.document.file_name or "", msg.document.mime_type or "")
            self._file_id = msg.document.file_id
        elif getattr(msg, "photo", None):
            self.file = _FakeFileInfo("", "image/jpeg")
            self._file_id = msg.photo[-1].file_id
        else:
            self.file = _FakeFileInfo("", "")
            self._file_id = None
        self.message = _FakeMessageInner(getattr(msg, "caption", "") or "", getattr(msg, "caption_entities", None) or [])

    async def download_media(self):
        if not self._file_id:
            return None
        info = self._tb.get_file(self._file_id)
        data = self._tb.download_file(info.file_path)
        name = self.file.name or os.path.basename(info.file_path) or "downloaded.bin"
        out = os.path.join(os.getcwd(), f"_tb_{self._msg.message_id}_{name}")
        with open(out, "wb") as f:
            f.write(data)
        return out

def _ensure_auth(uid):
    try:
        authenticated_users.add(uid)
    except Exception:
        pass

def manage_url_ads(bot_tb, uid, message_id=None):
    ctx = get_ctx(uid)
    _ensure_auth(uid)
    _users_in_rukla1.add(uid)
    ctx.user_states[uid] = "WAITING_PHONE"
    if message_id is not None:
        ctx.nav_msg_id[uid] = message_id  # Pre-set so show_nav edits in-place (smooth transition)
    try:
        _run_on_rukla1_loop(show_accounts_menu(uid))
    except Exception as e:
        try: bot_tb.send_message(uid, f"❌ {e}")
        except Exception: pass

def manage_group_ads(bot_tb, uid, message_id=None):
    ctx = get_ctx(uid)
    _ensure_auth(uid)
    _users_in_rukla1.add(uid)
    ctx.user_states[uid] = "G_WAITING_PHONE"
    if message_id is not None:
        ctx.nav_msg_id[uid] = message_id  # Pre-set so show_nav edits in-place (smooth transition)
    try:
        _run_on_rukla1_loop(show_group_accounts_menu(uid))
    except Exception as e:
        try: bot_tb.send_message(uid, f"❌ {e}")
        except Exception: pass

def register_callbacks(bot_tb):
    global _telebot_bot
    _telebot_bot = bot_tb
    bot._set_telebot(bot_tb)

def handle_callback(bot_tb, call):
    uid = call.message.chat.id
    try:
        bot_tb.answer_callback_query(call.id)
    except Exception:
        pass
    data = call.data
    if data == "back_to_main":
        try:
            import rukla as _rukla
            ctx = get_ctx(uid)
            _users_in_rukla1.discard(uid)
            ctx.user_states[uid] = None
            ctx.nav_msg_id.pop(uid, None)
            _run_on_rukla1_loop(ctx.clear_chat(uid))
            _rukla.open_manage_ad_menu(bot_tb, uid, call.message.message_id)
        except Exception as e:
            try: bot_tb.send_message(uid, f"❌ {e}")
            except Exception: pass
        return
    if data == "delete_usernames":
        try:
            ctx = get_ctx(uid)
            _run_on_rukla1_loop(_delete_all_usernames(ctx, uid))
        except Exception as e:
            try: bot_tb.send_message(uid, f"❌ {e}")
            except Exception: pass
        return
    if data == "g_delete_usernames":
        try:
            ctx = get_ctx(uid)
            _run_on_rukla1_loop(_delete_all_group_usernames(ctx, uid))
        except Exception as e:
            try: bot_tb.send_message(uid, f"❌ {e}")
            except Exception: pass
        return
    try:
        ev = _CallbackEvent(uid, data.encode())
        future = _run_on_rukla1_loop(callback_handler(ev))
        def _on_done(f):
            try:
                f.result()
            except Exception as e:
                print(f"[handle_callback] async error for '{data}': {e}")
                try: bot_tb.send_message(uid, f"❌ Помилка: {e}")
                except Exception: pass
        future.add_done_callback(_on_done)
    except Exception as e:
        try: bot_tb.send_message(uid, f"❌ Помилка: {e}")
        except Exception: pass

def handle_text(bot_tb, message):
    try:
        ev = _TextEvent(message)
        future = _run_on_rukla1_loop(text_handler(ev))
        def _on_done(f):
            try:
                f.result()
            except Exception as e:
                print(f"[handle_text] async error: {e}")
                try: bot_tb.send_message(message.chat.id, f"❌ Помилка тексту: {e}")
                except Exception: pass
        future.add_done_callback(_on_done)
    except Exception as e:
        try: bot_tb.send_message(message.chat.id, f"❌ Помилка тексту: {e}")
        except Exception: pass

def handle_file(bot_tb, message):
    try:
        ev = _MediaEvent(bot_tb, message)
        _run_on_rukla1_loop(handle_media(ev))
    except Exception as e:
        try: bot_tb.send_message(message.chat.id, f"❌ Помилка файлу: {e}")
        except Exception: pass

async def _delete_all_usernames(ctx: UserContext, chat_id):
    if not ctx.userbots:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_no_accs'))
        return
    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_users_progress').format(n=len(ctx.userbots)))
    cleared = skipped = failed = 0
    for acc in ctx.userbots:
        client = acc.get("client")
        if client is None:
            failed += 1
            continue
        try:
            me = await client.get_me()
            if not getattr(me, "username", None):
                skipped += 1
                continue
            await client(_AccUpdUsername(username=""))
            cleared += 1
        except Exception as e:
            failed += 1
            print(f"[delete_usernames] {acc.get('phone')}: {e}")
    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_users_ok').format(cleared=cleared, skipped=skipped, failed=failed))
    await asyncio.sleep(2)
    await show_accounts_menu(chat_id)

async def _delete_all_group_usernames(ctx: UserContext, chat_id):
    if not ctx.group_userbots:
        await ctx.send_and_track(chat_id, _T(chat_id, 'r1_no_accs'))
        return
    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_grp_del_users_progress').format(n=len(ctx.group_userbots)))
    cleared = skipped = failed = 0
    for acc in ctx.group_userbots:
        client = acc.get("client")
        if client is None:
            failed += 1
            continue
        try:
            me = await client.get_me()
            if not getattr(me, "username", None):
                skipped += 1
                continue
            await client(_AccUpdUsername(username=""))
            cleared += 1
        except Exception as e:
            failed += 1
            print(f"[g_delete_usernames] {acc.get('phone')}: {e}")
    await ctx.send_and_track(chat_id, _T(chat_id, 'r1_del_users_ok').format(cleared=cleared, skipped=skipped, failed=failed))
    await asyncio.sleep(2)
    await show_group_accounts_menu(chat_id)

if __name__ == "__main__":
    asyncio.run(main())
