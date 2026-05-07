import telebot
from telebot import types
import time
import threading
import re
import asyncio
import signal
import sys
import json
import os
import os, sys
from datetime import datetime, timezone, timedelta

# КРИТИЧНО: коли rukla.py запускається як __main__, sub-модулі (rukla1, rukla2,
# rukla3, rukla6, ruklaInfo) роблять `import rukla as _r` — без цього Python
# створив би другу копію модуля з окремим users_db, через що зміна мови та
# інші стани не синхронізувалися б між модулями.
sys.modules['rukla'] = sys.modules[__name__]

KYIV_TZ = timezone(timedelta(hours=3))

# ---------- Завантаження rukla1 ----------
try:
    import rukla1
    rukla1.init_async_loop()
    RUKLA1_OK = True
    asyncio_loop = None  # rukla1 manages its own loop via rukla1._loop
except Exception as e:
    print(f"[rukla1 import error]: {e}")
    RUKLA1_OK = False
    asyncio_loop = None

TOKEN = '8722480786:AAHlyfnr8pDROAmyu02Ubx0WJf7YiH3J6HE'
ADMIN_ID = 6326560451

bot = telebot.TeleBot(TOKEN)

# ---------- База даних ----------
users_db = {}
db_lock = threading.Lock()
DB_FILE = 'user_data.json'

def save_db():
    """Зберігає лише ключові дані (баланс, підписки, мову) у JSON."""
    with db_lock:
        serializable = {}
        for uid, data in users_db.items():
            serializable[str(uid)] = {
                'lang': data.get('lang', 'uk'),
                'lang_set': data.get('lang_set', False),
                'balance': data.get('balance', 0),
                'sub_url_until': data.get('sub_url_until', 0),
                'sub_groups_until': data.get('sub_groups_until', 0),
                'sub_tiktok_until': data.get('sub_tiktok_until', 0),
            }
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)

def load_db():
    """Завантажує дані з JSON, відновлює тимчасові поля за замовчуванням."""
    global users_db
    if not os.path.exists(DB_FILE):
        return
    with db_lock:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        for uid_str, fields in raw.items():
            uid = int(uid_str)
            users_db[uid] = {
                'lang': fields.get('lang', 'uk'),
                'lang_set': fields.get('lang_set', False),
                'balance': fields.get('balance', 0),
                'sub_url_until': fields.get('sub_url_until', 0),
                'sub_groups_until': fields.get('sub_groups_until', 0),
                'sub_tiktok_until': fields.get('sub_tiktok_until', 0),
                'support_state': None,
                'support_admin_msg_id': None,
                'support_chat_id': None,
                'pending_payment': None,
            }
        if ADMIN_ID not in users_db:
            pass

def get_user_data(user_id):
    if user_id not in users_db:
        users_db[user_id] = {
            'lang': 'uk',
            'lang_set': False,
            'balance': 0,
            'sub_url_until': 'lifetime' if user_id == ADMIN_ID else 0,
            'sub_groups_until': 'lifetime' if user_id == ADMIN_ID else 0,
            'sub_tiktok_until': 'lifetime' if user_id == ADMIN_ID else 0,
            'support_state': None,
            'support_admin_msg_id': None,
            'support_chat_id': None,
            'pending_payment': None,
        }
    return users_db[user_id]

# ---------- Глобальні змінні (виділено у sub-модулі) ----------
# admin_input_pending → rukladmin.is_admin_inputting()
# admin_current_ticket / pending_tickets → ruklateh


# ---------- Мультимовні тексти (повні) ----------
TEXT_START = "Welcome to the channel advertising bot. Please select a language:"

TEXTS = {
    'uk': {
        'greeting': "❕Вас вітає бот для реклами власного каналу.",
        'locked': "❌ Наразі у вас заблокована ця функція. Для того щоб розблокувати дану функцію поповніть баланс для придбання.",
        'profile': (
            "Профіль користувача:\n"
            "{name} ({uid}) {uname}\n\n"
            "💵 Баланс боту: {balance}$\n\n"
            "┏  📣 Ваша підписка на рекламу URL активна до: {sub_url}\n"
            "┣ 💬 Ваша підписка на рекламу по групах активна до: {sub_groups}\n"
            "┗ 🛩 Ваша підписка на рекламу у TikTok активна до: {sub_tiktok}"
        ),
        'balance': (
            "💸 Ваш поточний баланс: {balance}$.\n"
            "Для того щоб поповнити баланс боту виберіть одну з запропонованих клавіш:\n"
            "‼️ Важливо: Поповнення вашого балансу працює виключно з 10:00 до 22:00 за Київським часом. Якщо ви здійсните платіж в неробочий час підтримки - доведеться чекати початку зміни."
        ),
        'support': "💻 Технічна підтримка: натисніть кнопку нижче, щоб написати.",
        'support_intro': (
            "👋 Вітаємо вас у технічній підтримці нашого проекту.\n\n"
            "⏰ Години роботи підтримки: 10:00 - 22:00 за Київським часом.\n\n"
            "📝 Для того щоб розпочати діалог, натисніть на клавішу:"
        ),
        'support_start_chat': "⬇️ Напишіть ваше запитання. Середній час відповіді від технічної підтримки становить до 30 хвилин.",
        'support_msg_sent': "Ваше повідомлення надіслано! Очікуйте відповіді.",
        'support_accepted': "Ваша заявка прийнята технічною підтримкою. Можете розпочинати діалог. Якщо ви захочете зупинити діалог, надішліть /close.",
        'support_rejected': "Ваша заявка відхилена технічною підтримкою.",
        'support_closed': "Діалог завершено.",
        'support_ticket_new': (
            "❕Новий тікет.\n{text}\n\n"
            "Від: {name} ({uid}) {uname}"
        ),
        'support_btn_accept': "✅ Прийняти тікет",
        'support_btn_reject': "❌ Відхилити",
        'support_btn_start': "✏️ Розпочати діалог",
        'support_btn_again': "🔄 Зв'язатися повторно",
        'b_profile':  "👤 Профіль",
        'acc_shop_greeting': (
            "👋 Вітаю в меню купівлі акаунтів/проксі для ваших ботів.\n"
            "Для продовження роботи, оберіть що вам потрібно:"
        ),
        'acc_shop_btn_tg':    "📞 Акаунти телеграм",
        'acc_shop_btn_tt':    "📱 Акаунти Tik-Tok",
        'acc_shop_btn_proxy': "🌐 Проксі",
        'acc_shop_locked': "⛔️ Наразі у вас заблокована можливість переглядати дану сторінку. Для її перегляду необхідно мати щонайменше одну активну підписку.",
        'shop_greeting': "👋 Вітаємо вас у магазині додаткових функцій котрі доступні для купівлі у боті:",
        'tiktok_menu_text': "➕ Додайте акаунт. Надішліть одну або більше Cookies для додавання акаунту/акаунтів.\n\nНаявні акаунти в базі:",
        'tiktok_no_accounts': "Жодного акаунту не додано.",
        'tiktok_btn_add': "➕ Додати акаунт (Cookie)",
        'tiktok_ask_cookie': "📋 Надішліть Cookie рядок(и) для TikTok акаунту.\nКожен акаунт — окремим повідомленням або всі через новий рядок.",
        'tiktok_btn_cancel': "⬅️ Скасувати",
        'tiktok_checking': "⏳ Перевіряю акаунт(и)...",
        'tiktok_added': "✅ Успішно додано: {added}",
        'tiktok_failed': "❌ Без доступу (перевірте cookie): {failed}",
        'b_url':      "📣 Керувати URL рекламою",
        'b_grp':      "💬 Керувати рекламою у групах",
        'b_tiktok':   "🛩 Реклама у TikTok",
        'b_balance':  "💵 Поповнити баланс боту",
        'b_shop':     "🏪 Магазин додаткових функцій",
        'b_buy_acc':  "📲 Купити акаунти та проксі",
        'b_manage_ad': "📢 Керувати рекламою",
        'manage_ad_greeting': "Вітаємо вас у меню керування рекламою вашого блогу. Для продовження роботи виберіть одну з запропонованих функцій:",
        'b_manage_accounts': "📝 Керувати акаунтами",
        'b_manage_ad_params': "🔗 Керувати параметрами реклами",
        'b_buy_acc_url': "📱 Купити акаунти для URL реклами",
        'b_buy_acc_grp': "📱 Купити акаунти для реклами у групах",
        'b_buy_acc_tt':  "📱 Купити акаунти для реклами у TikTok",
        'b_buy_proxy_url': "🌍 Купити проксі для URL реклами",
        'b_buy_proxy_grp': "🌍 Купити проксі для реклами у групах",
        'b_buy_proxy_tt':  "🌍 Купити проксі для реклами у TikTok",
        'buy_acc_greeting': "👋 Вітаємо у меню купівлі акаунтів.",
        'b_back_prev': "⬅️ Повернутися на попередню сторінку",
        'r7_ctx_url':    "URL реклами",
        'r7_ctx_grp':    "реклами по групах",
        'r7_ctx_tiktok': "реклами у TikTok",
        'r7_kind_acc':   "акаунти",
        'r7_kind_proxy': "проксі",
        'r7_menu_greeting': "👋 Вітаємо у меню купівлі акаунтів.",
        'r7_ask_qty': "💵 Ціна за один {kind} 0.50$.\n\nВведіть кількість {kind} для {label}:",
        'r7_qty_invalid': "❌ Невірне число. Введіть ціле число від 1 до 1000.",
        'r7_checkout': (
            "🧾 <b>Чек:</b>\n\n"
            "📦 {kind} для {label}\n"
            "🔢 Кількість: {qty}\n"
            "💵 Ціна: {price}$ × {qty} = <b>{total}$</b>\n\n"
            "💳 Ваш баланс: {balance}$\n\n"
            "Оберіть спосіб оплати:"
        ),
        'r7_pay_balance': "💰 Сплатити з балансу",
        'r7_pay_card':    "💳 Сплатити карткою",
        'r7_pay_crypto':  "🪙 Сплатити криптою",
        'r7_pay_external_dev': "ℹ️ Оплата карткою/криптою тимчасово недоступна. Скористайтеся балансом або зверніться у підтримку.",
        'r7_paid_wait': "⏱ Очікуйте відповіді від адміністрації.",
        'r7_admin_new_order': (
            "🛒 <b>Нове замовлення #{oid}</b>\n\n"
            "👤 Користувач {name} ({uid}) {uname} здійснив оплату на суму {total}$ "
            "для купівлі {qty}× {kind} для {label}.\n\n"
            "Оберіть дію:"
        ),
        'r7_admin_approve': "✅ Схвалити оплату",
        'r7_admin_reject':  "❌ Відхилити оплату",
        'r7_admin_contact': "💬 Зв'язатися з користувачем",
        'r7_admin_send_n': "📦 Надішліть {qty}× файлів ({ext}) для замовлення #{oid}.\nКоли закінчите — надішліть /done.",
        'r7_delivery_progress': "📥 Отримано {got}/{need}",
        'r7_delivery_short': "⚠️ Отримано {got}/{need}. Будь ласка, надішліть ще {need} файлів.",
        'r7_delivery_done': "✅ Замовлення #{oid} виконано: переслано {n} файлів користувачу.",
        'r7_user_delivered': "✅ Замовлення #{oid} виконано! Ви отримали {qty}× {kind} для {label}.",
        'r7_user_rejected':  "❌ Ваше замовлення #{oid} відхилено. Кошти ({total}$) повернуто на баланс.",
        'r7_admin_contact_open': "💬 Дiалог з користувачем {uid} (#{oid}) розпочато. /close щоб завершити.",
        'r7_user_contact_open':  "💬 Адміністрація зв'язалася з вами стосовно замовлення #{oid}. /close щоб завершити.",
        'r7_contact_closed': "✅ Діалог завершено.",
        'r1_acc_limit': "⛔️ Ліміт акаунтів. Для того щоб додати новий акаунт - видаліть старий. Ліміт на акаунти становить 25 одиниць.",
        'b_manage_users': "📓 Керувати користувачами",
        'b_send_msg_to_user': "📨 Надіслати повідомлення користувачу",
        'send_msg_ask_uid': "Введіть ID користувача, якому надіслати повідомлення:",
        'send_msg_ask_text': "Введіть текст повідомлення (можна з фото — надішліть фото з підписом):",
        'send_msg_user_not_found': "❌ Користувача з таким ID не знайдено.",
        'send_msg_sent': "✅ Повідомлення надіслано користувачу {uid}.",
        'send_msg_failed': "❌ Не вдалося надіслати повідомлення: {err}",
        'btn_attach_ask': "Додати кнопку до повідомлення?",
        'btn_attach_create_new': "➕ Створити нову кнопку",
        'btn_attach_pick_existing': "🔘 Вибрати кнопку з боту",
        'btn_attach_none': "🚫 Без кнопки",
        'btn_create_ask_text': "Введіть текст кнопки:",
        'btn_create_ask_url': "Введіть URL кнопки (https://...):",
        'b_support':  "💻 Зв'язок з технічною підтримкою",
        'b_lang':     "🌐 Змінити мову боту",
        'b_discount': "👥 Отримати знижку на купівлю (тимчасово не працює)",
        'b_back':     "⬅️ Повернутися на попередню сторінку",
        'b_topup':    "💵 Поповнити баланс боту",
        'buy_from_balance': "💰 Купити за балансом",
        'not_enough_balance': "❌ Недостатньо коштів на балансі. Ваш баланс: {balance}$, потрібно: {price}$.",
        'bought_with_balance': "✅ Підписку успішно придбано за {price}$ з балансу!",
        'buy_url_m':  "📣 Купити місячну підписку на рекламу URL ~ 99$",
        'buy_grp_m':  "💬 Купити місячну підписку на рекламу по групах ~ 99$",
        'buy_url_y':  "📣 Купити річну підписку на рекламу URL ~ 1099$",
        'buy_grp_y':  "💬 Купити річну підписку на рекламу по групах ~ 1099$",
        'buy_mix_m':  "💭 Купити місячну підписку на рекламу URL х рекламу по групах ~ 149$",
        'buy_mix_y':  "🗯 Купити річну підписку на рекламу URL х рекламу по групах ~ 1399$",
        'buy_tiktok_m': "📱 Купити міс. підписку на рекламу у Tik-Tok ~ 79$",
        'buy_tiktok_y': "📲 Купити річну підписку на рекламу у Tik-Tok ~ 869$",
        'buy_all':      "🔋 Купити підписку на усі сервіси ~ 1999$",
        'pay_from_balance': "💰 Оплатити з балансу",
        'buy_custom': "💵 Поповнити баланс на зазначену суму",
        'payment_prompt': "💳 До сплати: {amount}$.\nВиберіть один з запропонованих методів оплати:",
        'custom_amount_prompt': "💳 Вкажіть суму на яку ви хочете поповнити баланс (мінімум 10$):",
        'min_amount_error': "Сума не може бути меншою за 10$.",
        'invalid_amount_error': "❌ Помилка. Введіть число.",
        'wallet_info': (
            "💳 До сплати: {amount}$.\n"
            "‼️ Важливо: усю комісію мережі на яку ви здійснюєте переказ покриваєте ви!\n\n"
            "Адреса для переказу ({name}):\n{address}\n\n"
            "Після переказу коштів натисніть кнопку «Я сплатив»."
        ),
        'i_paid': "✅ Я сплатив",
        'send_screenshot': "📃 Надішліть квитанцію, або скріншот переказу котрий підтверджує оплату:\n‼️ Важливо, щоб квитанція/скріншот були у гарній якості.",
        'not_screenshot': "Це не скріншот. Спробуйте ще раз через меню.",
        'payment_wait': "⏳ Очікуйте підтвердження від адміністратора.",
        'rukla1_missing': "❌ Модуль rukla1.py не знайдено поруч.",
        'sub_expired': "‼️ Термін дії вашої підписки на {type} закінчився. Для поновлення підписки натисніть на \"Купити підписку\".",
        'sub_btn_buy': "💵 Купити підписку",
        # адмін-кнопки
        'adm_info_btn': "🔦 Інформація про користувачів",
        'adm_give_sub_btn': "➕ Видати підписку користувачу",
        'adm_del_sub_btn': "➖ Видалити підписку у користувача",
        'adm_add_bal_btn': "💸 Поповнити баланс користувачу",
        'adm_rem_bal_btn': "❌ Зняти з балансу користувача",
        'adm_broadcast_btn': "🌐 Розіслати повідомлення всім",
        'adm_enter_id_amount': "Введіть ID та суму через пробіл (напр: 123456789 50):",
        'adm_bal_added': "✅ Баланс {uid} поповнено на {amount}$.",
        'adm_user_bal_added': "✅ Ваш баланс поповнено на {amount}$!",
        'adm_enter_id_remove': "Введіть ID та суму для зняття:",
        'adm_bal_removed': "✅ З балансу {uid} знято {amount}$.",
        'adm_enter_id_sub': "Введіть айді користувача котрому потрібно видати підписку:",
        'adm_sub_type': "Виберіть тип підписки:",
        'adm_sub_url': "📣 URL",
        'adm_sub_grp': "💬 Групи",
        'adm_sub_tiktok': "🛩 TikTok",
        'adm_sub_mix': "💭 URL + Групи",
        'adm_sub_all': "🌐 URL + Групи + TikTok",
        'adm_enter_term': "Виберіть час на який буде видано підписку:\n(Наприклад: 10 min, 10 hour, 10 day, 10 month, 10 years)",
        'adm_sub_given': "✅ Підписку успішно видано користувачу {uid}.",
        'adm_sub_notify': "✅ Вам видано підписку! Відкрийте головне меню.",
        'adm_del_sub_confirm': "Введіть ID для видалення всіх підписок:",
        'adm_del_sub_done': "✅ Підписки {uid} видалено.",
        'adm_broadcast_prompt': "Введіть текст, фото або документ для розсилки:",
        'adm_broadcast_result': "✅ Надіслано: {sent} | Помилок: {errors}",
        'adm_payment_confirm': "Для підтвердження операції надішліть слово \"Так\".",
        'payment_approved': "✅ Платіж підтверджено. Вашу підписку активовано!",
        'payment_rejected': "❌ Операцію відхилено. Для оскарження ви можете звернутися у технічну підтримку.",
        # rukla1 menu
        'r1_acc_header': "➕ Додайте акаунт. Надішліть ZIP з .session файлами або самі .session файли.\n\nНаявні акаунти в базі:",
        'r1_acc_empty': "Порожньо",
        'r1_btn_url_ads': "📣 Керувати URL рекламою",
        'r1_btn_grp_ads': "💬 Керувати рекламою у групах",
        'r1_btn_proxy': "🌍 Підключити проксі",
        'r1_btn_del_acc': "❌ Видалити акаунт",
        'r1_btn_rename': "💬 Замінити нікнейми акаунтам",
        'r1_btn_del_avatar': "🗑 Видалити аватарку/и",
        'r1_btn_del_users': "🐶 Видалити @users на усіх акаунтах",
        'r1_btn_bio': "📃 Змінити опис",
        'r1_btn_pers_ch': "🌟 Створити персональний канал",
        'r1_btn_photo': "👤 Змінити фото",
        'r1_btn_keywords': "ℹ️ Встановити ключові слова",
        'r1_btn_styles': "⌚ Керувати стилями повідомлень",
        'r1_btn_reminders': "📩 Керувати стилем нагадувань",
        'r1_btn_cycle': "✏️ Повторення циклу",
        'r1_btn_channels': "➕ Керування каналами",
        'r1_btn_clear_chats': "🗑 Очистити акаунти від чатів",
        'r1_btn_bot_status': "🤔 Стан боту",
        'r1_btn_search_ch': "🪽 Пошук каналів",
        'r1_btn_search_chats': "🪽 Пошук чатів",
        'r1_btn_manage_acc': "📝 Керувати акаунтами",
        'r1_btn_manage_ad_params': "🔗 Керувати параметрами реклами",
        'r1_btn_back_main': "⬅️ Повернутися у головне меню",
        'r1_btn_back_acc': "⬅️ Повернутися на попередню сторінку",
        'r1_btn_back_short': "⬅️ Назад",
        'r1_btn_enable': "🟢 Увімкнути",
        'r1_btn_disable': "🔴 Вимкнути",
        'r1_bot_on': "🟢 увімкнений",
        'r1_bot_off': "🔴 вимкнений",
        'r1_bot_status_text': "📝 Стан боту в якому він знаходиться:\n\n{status}",
        'r1_grp_bot_status_text': "📝 Стан боту (реклама у групах):\n\n{status}",
        'r1_btn_monitoring': "📘 Встановити канал для читання",
        'r1_btn_groups': "➕ Керування групами",
        'r1_greeting': "❕Вас вітає бот для реклами власного каналу.",
        'r1_btn_create_folder': "➕ Створити папку каналів",
        'r1_btn_del_folder': "🗑 Видалити папку каналів",
        'r1_btn_add_channel': "➕ Додати канал/папку",
        'r1_btn_back_channels': "⬅️ Назад до каналів",
        'r1_channels_header': "➕ Керування каналами (канали та папки t.me/addlist/...):\n\n",
        'r1_channels_empty': "➕ Керування каналами\n\nПоки що немає жодної папки каналів.\nСтворіть папку та додайте посилання на канали.",
        'r1_auth_pwd_prompt': "🔒 Бот заблоковано. Введіть пароль:",
        'r1_auth_pwd_ok': "✅ Пароль прийнято!",
        'r1_auth_pwd_wrong': "❌ Невірний пароль.",
        'r1_code_sent': "✅ Код надіслано на {phone}. Введіть код:",
        'r1_2fa_prompt': "🔐 Введіть пароль 2FA:",
        'r1_acc_ok': "✅ Акаунт {name} успішно підключено!",
        'r1_no_accs': "❌ Немає підключених акаунтів.",
        'r1_del_all_ok': "✅ Видалено всіх акаунтів: {count}!",
        'r1_del_one_ok': "✅ Акаунт №{num} видалено!",
        'r1_del_range_err': "❌ Невірний формат діапазону. Приклад: 1-5",
        'r1_del_no_num': "❌ Немає такого номера.",
        'r1_rename_prompt': "Надішліть новий нікнейм:",
        'r1_rename_ok': "✅ Ніки змінено!",
        'r1_grp_rename_prompt': "💬 {pool_info}Надішліть список імен (по одному на рядок).\nКожен акаунт отримає випадкове ім'я.\n\nПриклад:\nОлексій\nМарія\nДмитро",
        'r1_grp_rename_ok': "✅ Нікнейми оновлено на {changed}/{total} акаунтах!",
        'r1_grp_rename_empty': "❌ Список імен порожній. Надішліть хоча б одне ім'я.",
        'r1_grp_rename_progress': "⏳ Отримано {n} імен. Призначаю випадкові нікнейми...",
        'r1_bio_prompt': "📃 Введіть новий опис (біо) для всіх акаунтів:",
        'r1_bio_ok': "✅ Опис змінено на всіх акаунтах!",
        'r1_grp_bio_prompt': "📃 Введіть новий опис (біо) для всіх акаунтів відділу груп:",
        'r1_grp_bio_ok': "✅ Опис змінено на всіх акаунтах відділу груп!",
        'r1_del_avatar_progress': "⏳ Видаляю аватарки...",
        'r1_grp_del_avatar_progress': "⏳ Видаляю аватарки (відділ груп)...",
        'r1_del_avatar_ok': "✅ Видалено аватарок: {total}",
        'r1_clear_chats_progress': "⏳ Очищаю чати на {n} акаунтах... Це може зайняти час.",
        'r1_grp_clear_chats_progress': "⏳ Очищаю чати на {n} акаунтах (відділ груп)...",
        'r1_clear_chats_ok': "✅ Готово! Видалено чатів загалом: {total}",
        'r1_photo_prompt': "👤 Надішліть нове фото для всіх акаунтів:",
        'r1_photo_progress': "⏳ Змінюю фото на всіх акаунтах...",
        'r1_photo_ok': "✅ Фото змінено на {success}/{total} акаунтах!",
        'r1_del_users_progress': "⏳ Видаляю @username на {n} акаунтах...",
        'r1_grp_del_users_progress': "⏳ Видаляю @username на {n} акаунтах груп...",
        'r1_del_users_ok': "✅ Готово!\n• Очищено: {cleared}\n• Без @username: {skipped}\n• Помилок: {failed}",
        'r1_zip_progress': "⏳ Обробляю ZIP-архів...",
        'r1_grp_zip_progress': "⏳ Обробляю ZIP-архів (відділ груп)...",
        'r1_zip_ok': "✅ Успішно підключено акаунтів: {loaded}",
        'r1_grp_zip_ok': "✅ Успішно підключено акаунтів (групи): {loaded}",
        'r1_session_progress': "⏳ Обробляю .session файл...",
        'r1_session_bad_name': "❌ Некоректна назва файлу.",
        'r1_session_invalid': "❌ Сесія недійсна або протермінована.",
        'r1_proxy_no_lib': "❌ Бібліотека PySocks не встановлена!\n<code>pip install PySocks</code>",
        'r1_proxy_prompt': "🌍 Надайте ваші проксі у форматі SOCKS5\n(якщо кілька — кожен з нового рядка):\n\nФормати:\n• <code>socks5://user:pass@host:port</code>\n• <code>host:port:user:pass</code>\n• <code>host:port</code> (без авторизації)\n\nПоточні проксі:\n{current}",
        'r1_grp_proxy_prompt': "🌍 Надайте ваші проксі для акаунтів ГРУП у форматі SOCKS5\n(якщо кілька — кожен з нового рядка):\n\nФормати:\n• <code>socks5://user:pass@host:port</code>\n• <code>host:port:user:pass</code>\n• <code>host:port</code> (без авторизації)\n\nПоточні проксі:\n{current}",
        'r1_proxy_none': "❌ Не вдалося розпізнати жодного проксі. Перевірте формат.",
        'r1_proxy_ok': "✅ Проксі успішно додано!\n{info}",
        'r1_proxy_result_info': "Акаунти: {ok} успішно, {fail} невдало.\n\n{proxies}",
        'r1_no_active_proxies': "Немає активних проксі.",
        'r1_unknown': "Невідомо",
        'r1_proxy_del_progress': "⏳ Видаляю проксі та перепідключаю акаунти без проксі...",
        'r1_proxy_del_ok': "✅ Всі проксі видалено.",
        'r1_proxy_del_reconnect_ok': "✅ Всі проксі видалено. Акаунти перепідключено без проксі ({ok} успішно, {fail} невдало).",
        'r1_ch_folder_prompt': "📁 Введіть назву нової папки каналів:",
        'r1_ch_folder_empty': "❌ Назва не може бути порожньою. Введіть назву папки:",
        'r1_ch_folder_exists': "❌ Папка '{name}' вже існує. Введіть іншу назву:",
        'r1_ch_folder_ok': "✅ Папку '{name}' створено!\nТепер додайте до неї канали.",
        'r1_ch_folder_del_ok': "✅ Папку '{name}' видалено!",
        'r1_ch_folder_not_found': "❌ Папки '{name}' не існує. Спробуйте ще раз:",
        'r1_ch_no_folders': "❌ Немає папок для видалення.",
        'r1_ch_del_folder_list': "🗑 Введіть точну назву папки для видалення:\n\n{folders}",
        'r1_ch_add_link_prompt': "📎 Надішліть посилання на канал або папку для '{name}':\n\nФормати:\n• https://t.me/channelname\n• https://t.me/+inviteHash\n• https://t.me/addlist/... (папка TG)",
        'r1_channels_folder_header': "📁 Папка: {name}\n\nКанали ({count}):\n",
        'r1_channels_folder_empty': "📁 Папка: {name}\n\nПоки що немає каналів.\nДодайте посилання на канал.",
        'r1_delete_prompt': "❌ Видалення акаунтів:\n\n{acc_list}Варіанти:\n• Один акаунт: введіть номер (наприклад: <b>2</b>)\n• Діапазон: введіть <b>1-5</b>\n• Всі акаунти: введіть <b>all</b>",
        'r1_grp_delete_prompt': "❌ Видалення акаунтів (відділ груп):\n\n{acc_list}Варіанти:\n• Один акаунт: введіть номер (наприклад: <b>2</b>)\n• Діапазон: введіть <b>1-5</b>\n• Всі акаунти: введіть <b>all</b>",
        'r1_avatar_zip_result': "✅ Готово!\n👤 Отримали аватарку: {photo} акаунтів\n🚫 Залишились без аватарки: {no_photo} акаунтів",
        'r1_grp_acc_ok': "✅ Акаунт {name} підключено до відділу груп!",
        'r1_ch_link_prompt': "❌ Посилання не може бути порожнім. Надішліть посилання:",
        'r1_ch_link_added': "✅ Канал додано до папки '{name}'!\n⏳ Акаунти підписуються у фоні...",
        'r1_ch_link_exists': "ℹ️ Цей канал вже є в папці '{name}'.",
        'r1_ch_name_prompt': "🌟 Введіть назву каналу:",
        'r1_ch_avatar_prompt': "✅ Назва: {name}\n\n📸 Надішліть квадратне фото для аватарки каналу:",
        'r1_ch_avatar_ok': "✅ Аватарка збережена!\n\n📝 Надішліть перший пост для каналу (може містити фото та форматування):",
        'r1_ch_create_progress': "⏳ Створюю канал '{name}' на {n} акаунтах...",
        'r1_ch_create_ok': "✅ Канали створено на {created}/{total} акаунтах!",
        'r1_avatar_zip_progress': "⏳ Обробляю ZIP з аватарками...",
        'r1_avatar_zip_no_imgs': "❌ У ZIP не знайдено жодного PNG/JPG файлу.",
        'r1_avatar_zip_ok': "✅ Завантажено {count} аватарок. Застосовую (50/50)...",
        'r1_grp_avatar_prompt': "👤 {pool_info}Надішліть ZIP-файл з аватарками (PNG/JPG, до 50 штук).\n\n⚖️ Логіка призначення:\n• 50% акаунтів — залишаться БЕЗ аватарки\n• 50% акаунтів — отримають ВИПАДКОВУ аватарку з ZIP",
        'r6_in_dev': "🔧 Розділ у розробці.",
        'r3_search_ch_header': "Завершив пошук каналів ({total} з чатом):\n\n",
        'r3_search_grp_header': "Знайдено груп/чатів ({total}):\n\n",
        'r3_search_cont': "(продовження)\n\n",
        'r3_ch_collecting': "🔍 Збираю список каналів...",
        'r3_ch_not_found': "❌ За цими ключовими словами каналів не знайдено.",
        'r3_ch_checking': "✅ Знайдено кандидатів: {total}\n⏳ Перевіряю наявність чату коментарів...",
        'r3_ch_progress': "⏳ Перевірено {checked}/{total}, знайдено з чатом: {found}...",
        'r3_ch_no_chat': "❌ Серед {total} знайдених каналів жоден не має чату коментарів.",
        'r3_grp_no_acc': "❌ Немає підключених акаунтів у відділі груп.",
        'r3_grp_collecting': "🔍 Збираю список чатів/груп з бірж та Telegram...",
        'r3_grp_not_found': "❌ За цими ключовими словами чатів/груп не знайдено.",
        'r3_grp_checking': "✅ Знайдено кандидатів: {total}\n⏳ Перевіряю типи чатів...",
        'r3_grp_progress': "⏳ Перевірено {checked}/{total}, знайдено груп: {found}...",
        'r3_grp_no_groups': "❌ Серед {total} кандидатів жодної публічної групи не знайдено.",
        'r3_searching_ch': "⏳ Виконую пошук... Це може зайняти кілька хвилин.",
        'r3_searching_grp': "⏳ Виконую пошук чатів... Це може зайняти кілька хвилин.",
        'r3_kw_prompt_ch': "🪽 Введіть ключові слова для пошуку каналів (через кому):",
        'r3_kw_prompt_grp': "🪽 Введіть ключові слова для пошуку чатів/груп (через кому):\nПриклад: Чат Київ, Обговорення, Форум",
        'r2_btn_create_style': "➕ Створити стиль",
        'r2_btn_del_style': "🗑 Видалити стиль",
        'r2_btn_create_rem': "➕ Створити нагадування",
        'r2_btn_del_rem': "🗑 Видалити нагадування",
        'r2_btn_set_delay': "⏱ Встановити затримку",
        'r2_btn_set_cycle': "⏱ Встановити час повторення",
        'r2_btn_add_group': "➕ Додати групу/чат",
        'r2_btn_del_group': "➖ Видалити групу",
        'r2_btn_interval': "⏱ Інтервал між циклами",
        'r2_btn_repeat': "🔁 Кількість повторень",
        'r2_btn_add_chan': "➕ Додати канал",
        'r2_btn_del_chan': "➖ Вилучити канал",
        'r2_not_set': "не встановлено",
        'r2_mon_active': "🟢 активний",
        'r2_mon_stopped': "🔴 зупинений",
        'r2_grp_empty': "(порожньо)",
        'r2_styles_empty': "Немає збережених стилів.",
        'r2_styles_header': "⌚ Керувати стилями повідомлень:\n\n{styles}",
        'r2_rems_empty': "Немає збережених нагадувань.",
        'r2_rems_header': "📩 Керувати стилем нагадувань:\n\n{rems}\n\n⏱ Затримка: {delay} сек.",
        'r2_cycle_off': "Вимкнено",
        'r2_cycle_header': "✏️ Повторення циклу:\n\nЗатримка: {state}\n(0 - вимкнути).",
        'r2_grp_menu_header': "➕ Керування групами для репостів\n\n📘 Канал моніторингу: {chan}\nСтан моніторингу: {status}\n⏱ Інтервал між циклами: {interval} сек.\n🔁 Кількість повторень: {repeat}\n\nГрупи в базі:\n{chats}",
        'r2_kw_prompt': "ℹ️ Поточні ключові слова: {kw}\n\nВведіть ключові слова через кому.\nЯкщо список порожній — бот коментує всі пости.\nПриклад: Новини, Рецепт, Політик, Президент",
        'r2_kw_empty': "порожньо",
        'r2_kw_ok': "✅ Ключові слова встановлено:\n{kw}\n\nЯкщо список порожній — бот коментує всі пости.",
        'r2_style_name_prompt': "📝 Назва стилю:",
        'r2_style_name_ok': "✅ Назва стилю: {name}\n\n📝 Надішліть текст самого стилю:",
        'r2_style_saved': "✅ Стиль '{name}' збережено!",
        'r2_style_deleted': "🗑 Стиль видалено!",
        'r2_style_active': "✅ Активний стиль: '{name}'",
        'r2_rem_name_prompt': "📝 Назва нагадування:",
        'r2_rem_name_ok': "✅ Назва нагадування: {name}\n\n📝 Надішліть текст нагадування:",
        'r2_rem_saved': "✅ Нагадування збережено!",
        'r2_rem_deleted': "🗑 Нагадування видалено!",
        'r2_del_name_prompt': "Введіть назву для видалення:",
        'r2_delay_prompt': "⏱ Введіть затримку у секундах:",
        'r2_rem_delay_ok': "✅ Затримка нагадувань: {secs} сек.",
        'r2_cycle_delay_prompt': "⏱ Затримка між циклами (сек):",
        'r2_cycle_delay_ok': "✅ Затримка циклу: {secs} сек.",
        'r2_folder_name_prompt': "📁 Назва папки:",
        'r2_folder_name_ok': "✅ Назва папки: {name}\n\n🔗 Надішліть посилання на канали (кожне з нового рядка):",
        'r2_folder_saving': "⏳ Зберігаю канали та папки...",
        'r2_folder_saved': "✅ Завершено!",
        'r2_folder_deleting': "⏳ Видаляю папку та виходжу з каналів...",
        'r2_folder_deleted': "🗑 Папку видалено!",
        'r2_folder_view': "📁 '{name}':\n\n{links}",
        'r2_add_chan_prompt': "Надішліть посилання (можна і папки addlist):",
        'r2_del_chan_prompt': "Надішліть посилання для вилучення:",
        'r2_chan_adding': "✅ Додано. Вступаю...",
        'r2_chan_removing': "⏳ Вилучаю та виходжу з каналу...",
        'r2_chan_removed': "✅ Вилучено.",
        'r2_mon_prompt': "📘 Встановити канал для читання\n\nПоточний канал: {chan}\nСтатус: {status}\n\nВведіть назву країни для фільтрації\n(наприклад: Україна):",
        'r2_mon_country_ok': "✅ Країна: {country}\n\n📎 Надішліть посилання на канал для читання (наприклад: https://t.me/channel):",
        'r2_mon_set_ok': "✅ Канал встановлено: {link}\n🟢 Моніторинг активований!\n\nКраїна фільтрації: {country}\nГруп у базі: {grps}\nІнтервал репосту: {interval} сек.",
        'r2_mon_set_warn': "⚠️ Канал збережено, але не вдалося підключитись: {e}\nСпробуйте після підключення акаунтів.",
        'r2_mon_set_no_acc': "⚠️ Канал збережено. Підключіть акаунти — тоді моніторинг активується автоматично.",
        'r2_mon_stopped_msg': "🔴 Моніторинг зупинено.",
        'r2_mon_started_msg': "🟢 Моніторинг активовано!",
        'r2_mon_not_ready': "❌ Спочатку встановіть канал та підключіть акаунти.",
        'r2_interval_prompt': "⏱ Поточний інтервал між циклами: {cur} сек.\n\nВведіть нове значення в секундах (наприклад: 180):",
        'r2_interval_ok': "✅ Інтервал між циклами встановлено: {secs} сек.",
        'r2_interval_err': "❌ Невірне значення. Введіть ціле число секунд.",
        'r2_repeat_prompt': "🔁 Поточна кількість повторень: {cur}\n\nВведіть нове значення (наприклад: 5):",
        'r2_repeat_ok': "✅ Кількість повторень встановлено: {n}",
        'r2_repeat_err': "❌ Невірне значення. Введіть ціле число.",
        'r2_grp_empty_db': "❌ База груп порожня.",
        'r2_del_group_prompt': "➖ Введіть номер групи для видалення:\n\n{list}",
        'r2_grp_deleted': "🗑 Видалено: {title}",
        'r2_grp_del_no_num': "❌ Немає групи з таким номером.",
        'r2_grp_enter_num': "❌ Введіть номер групи.",
        'r2_add_group_prompt': "➕ Додати групи/чати\n\nНадішліть посилання (по одному на рядок).\nПублічні: https://t.me/username\nПриватні: https://t.me/+invitehash\n\n⚠️ Для приватних (по заявках) бот надішле заявку і чекатиме підтвердження.",
        'r2_grp_no_link': "❌ Не знайдено жодного посилання.",
        'r2_grp_processing': "⏳ Обробляю {n} посилань...",
        'r2_grp_added': "✅ Додано груп: {added}",
        'r2_grp_add_warn': "\n⚠️ Не вдалося вступити / заявка очікується: {n}",
        'r2_view_group': "📌 Група №{n}\nНазва: {title}\nПосилання: {link}\nID: {id}",
    },
    'en': {
        'greeting': "❕Welcome to the channel advertising bot.",
        'locked': "❌ This feature is locked. Top up your balance to purchase a subscription.",
        'info': "Important information (add full text)...",
        'profile': (
            "User profile:\n"
            "{name} ({uid}) {uname}\n\n"
            "💵 Bot balance: {balance}$\n\n"
            "┏  📣 URL advertising active until: {sub_url}\n"
            "┣ 💬 Group advertising active until: {sub_groups}\n"
            "┗ 🛩 TikTok advertising active until: {sub_tiktok}"
        ),
        'balance': (
            "💸 Your current balance: {balance}$.\n"
            "To top up your bot balance, select one of the options below:\n"
            "‼️ Important: Top-ups are processed from 10:00 to 22:00 Kyiv time. Payments made outside these hours will be processed at the start of the next shift."
        ),
        'support_intro': (
            "👋 Welcome to the technical support of our project.\n\n"
            "⏰ Support hours: 10:00 - 22:00 Kyiv time.\n\n"
            "📝 To start a conversation, click the button below:"
        ),
        'support_start_chat': "⬇️ Write your question. Average response time is up to 30 minutes.",
        'support_accepted': "Your ticket accepted.",
        'support_rejected': "Ticket rejected.",
        'support_closed': "Chat closed.",
        'b_profile': "👤 Profile",
        'acc_shop_greeting': (
            "👋 Welcome to the accounts/proxies shop for your bots.\n"
            "Please select what you need:"
        ),
        'acc_shop_btn_tg':    "📞 Telegram accounts",
        'acc_shop_btn_tt':    "📱 TikTok accounts",
        'acc_shop_btn_proxy': "🌐 Proxies",
        'acc_shop_locked': "⛔️ This page is locked. You need at least one active subscription to access it.",
        'shop_greeting': "👋 Welcome to the additional features shop:",
        'tiktok_menu_text': "➕ Add an account. Send one or more Cookies to add account(s).\n\nAccounts in the database:",
        'tiktok_no_accounts': "No accounts added.",
        'tiktok_btn_add': "➕ Add account (Cookie)",
        'tiktok_ask_cookie': "📋 Send Cookie string(s) for the TikTok account.\nOne account per message or all on separate lines.",
        'tiktok_btn_cancel': "⬅️ Cancel",
        'tiktok_checking': "⏳ Checking account(s)...",
        'tiktok_added': "✅ Successfully added: {added}",
        'tiktok_failed': "❌ No access (check cookie): {failed}",
        'b_url': "📣 Manage URL advertising",
        'b_grp': "💬 Manage group advertising",
        'b_balance': "💵 Top up balance",
        'b_buy_acc': "📲 Buy accounts & proxies",
        'b_manage_ad': "📢 Manage advertising",
        'manage_ad_greeting': "Welcome to your blog's advertising management menu. Please select one of the available features:",
        'b_manage_accounts': "📝 Manage accounts",
        'b_manage_ad_params': "🔗 Manage ad parameters",
        'b_buy_acc_url': "📱 Buy accounts for URL ads",
        'b_buy_acc_grp': "📱 Buy accounts for group ads",
        'b_buy_acc_tt':  "📱 Buy accounts for TikTok ads",
        'b_buy_proxy_url': "🌍 Buy proxies for URL ads",
        'b_buy_proxy_grp': "🌍 Buy proxies for group ads",
        'b_buy_proxy_tt':  "🌍 Buy proxies for TikTok ads",
        'buy_acc_greeting': "👋 Welcome to the accounts purchase menu.",
        'b_back_prev': "⬅️ Back to previous page",
        'r7_ctx_url':    "URL ads",
        'r7_ctx_grp':    "group ads",
        'r7_ctx_tiktok': "TikTok ads",
        'r7_kind_acc':   "accounts",
        'r7_kind_proxy': "proxies",
        'r7_menu_greeting': "👋 Welcome to the accounts purchase menu.",
        'r7_ask_qty': "💵 Price per {kind} is 0.50$.\n\nEnter the number of {kind} for {label}:",
        'r7_qty_invalid': "❌ Invalid number. Enter integer between 1 and 1000.",
        'r7_checkout': (
            "🧾 <b>Receipt:</b>\n\n"
            "📦 {kind} for {label}\n"
            "🔢 Quantity: {qty}\n"
            "💵 Price: {price}$ × {qty} = <b>{total}$</b>\n\n"
            "💳 Your balance: {balance}$\n\n"
            "Choose payment method:"
        ),
        'r7_pay_balance': "💰 Pay from balance",
        'r7_pay_card':    "💳 Pay by card",
        'r7_pay_crypto':  "🪙 Pay with crypto",
        'r7_pay_external_dev': "ℹ️ Card/crypto payment temporarily unavailable. Use balance or contact support.",
        'r7_paid_wait': "⏱ Please wait for the administrator's response.",
        'r7_admin_new_order': (
            "🛒 <b>New order #{oid}</b>\n\n"
            "👤 User {name} ({uid}) {uname} paid {total}$ "
            "for {qty}× {kind} for {label}.\n\n"
            "Choose action:"
        ),
        'r7_admin_approve': "✅ Approve",
        'r7_admin_reject':  "❌ Reject",
        'r7_admin_contact': "💬 Contact user",
        'r7_admin_send_n': "📦 Send {qty}× files ({ext}) for order #{oid}.\nWhen done — send /done.",
        'r7_delivery_progress': "📥 Received {got}/{need}",
        'r7_delivery_short': "⚠️ Received {got}/{need}. Please send {need} more files.",
        'r7_delivery_done': "✅ Order #{oid} done: forwarded {n} files to the user.",
        'r7_user_delivered': "✅ Order #{oid} fulfilled! You received {qty}× {kind} for {label}.",
        'r7_user_rejected':  "❌ Your order #{oid} was rejected. Funds ({total}$) refunded.",
        'r7_admin_contact_open': "💬 Dialog with user {uid} (#{oid}) started. /close to end.",
        'r7_user_contact_open':  "💬 The administrator contacted you regarding order #{oid}. /close to end.",
        'r7_contact_closed': "✅ Dialog ended.",
        'r1_acc_limit': "⛔️ Account limit reached. Delete an old account before adding a new one. The account limit is 25.",
        'b_manage_users': "📓 Manage users",
        'b_send_msg_to_user': "📨 Send message to user",
        'send_msg_ask_uid': "Enter the user ID to send a message to:",
        'send_msg_ask_text': "Enter the message text (you can attach a photo with caption):",
        'send_msg_user_not_found': "❌ User with this ID not found.",
        'send_msg_sent': "✅ Message sent to user {uid}.",
        'send_msg_failed': "❌ Failed to send message: {err}",
        'btn_attach_ask': "Attach a button to the message?",
        'btn_attach_create_new': "➕ Create a new button",
        'btn_attach_pick_existing': "🔘 Pick a bot button",
        'btn_attach_none': "🚫 No button",
        'btn_create_ask_text': "Enter button text:",
        'btn_create_ask_url': "Enter button URL (https://...):",
        'b_support': "💻 Technical support",
        'b_lang': "🌐 Change language",
        'b_discount': "👥 Get discount",
        'b_back': "⬅️ Go back",
        'b_topup': "💵 Top up balance",
        'buy_url_m': "📣 Month URL ~ $99",
        'buy_grp_m': "💬 Month Groups ~ $99",
        'buy_url_y': "📣 Year URL ~ $1099",
        'buy_grp_y': "💬 Year Groups ~ $1099",
        'buy_mix_m': "💭 Month URL+Groups ~ $149",
        'buy_mix_y': "🗯 Year URL+Groups ~ $1399",
        'buy_tiktok_m': "📱 Month TikTok ~ $79",
        'buy_tiktok_y': "📲 Year TikTok ~ $869",
        'buy_all':      "🔋 All services ~ $1999",
        'pay_from_balance': "💰 Pay from balance",
        'buy_custom': "💵 Custom amount",
        'payment_prompt': "💳 To pay: ${amount}.\nChoose method:",
        'custom_amount_prompt': "💳 Enter amount (min $10):",
        'min_amount_error': "Amount cannot be less than $10.",
        'invalid_amount_error': "❌ Error. Enter a number.",
        'wallet_info': (
            "💳 To pay: ${amount}.\n"
            "‼️ Network fee covered by sender!\n\n"
            "Address ({name}):\n{address}\n\n"
            "After sending click «I paid»."
        ),
        'i_paid': "✅ I paid",
        'send_screenshot': "📃 Send screenshot of payment:\n‼️ Good quality required.",
        'not_screenshot': "Not a screenshot. Try again.",
        'payment_wait': "⏳ Waiting for admin confirmation.",
        'rukla1_missing': "❌ rukla1.py module not found.",
        'sub_expired': "‼️ Your {type} subscription has expired. Click \"Buy subscription\" to renew.",
        'sub_btn_buy': "💵 Buy subscription",
        'adm_info_btn': "🔦 User info",
        'adm_give_sub_btn': "➕ Give subscription",
        'adm_del_sub_btn': "➖ Remove subscription",
        'adm_add_bal_btn': "💸 Add balance",
        'adm_rem_bal_btn': "❌ Deduct balance",
        'adm_broadcast_btn': "🌐 Broadcast",
        'adm_enter_id_amount': "Enter ID and amount (e.g. 123456789 50):",
        'adm_bal_added': "✅ Added {amount}$ to {uid}.",
        'adm_user_bal_added': "✅ Your balance topped up by {amount}$!",
        'adm_enter_id_remove': "Enter ID and amount to deduct:",
        'adm_bal_removed': "✅ Deducted {amount}$ from {uid}.",
        'adm_enter_id_sub': "Enter user ID:",
        'adm_sub_type': "Subscription type:",
        'adm_sub_url': "📣 URL",
        'adm_sub_grp': "💬 Groups",
        'adm_sub_tiktok': "🛩 TikTok",
        'adm_sub_mix': "💭 URL + Groups",
        'adm_sub_all': "🌐 URL + Groups + TikTok",
        'b_tiktok': "🛩 TikTok Advertising",
        'b_shop': "🏪 Additional Features Shop",
        'buy_from_balance': "💰 Buy from balance",
        'not_enough_balance': "❌ Insufficient funds. Balance: {balance}$, required: {price}$.",
        'bought_with_balance': "✅ Subscription purchased for {price}$ from balance!",
        'adm_enter_term': "Enter term (e.g. 10 min, 10 day, lifetime):",
        'adm_sub_given': "✅ Subscription granted to {uid}.",
        'adm_sub_notify': "✅ Subscription granted!",
        'adm_del_sub_confirm': "Enter ID to delete all subscriptions:",
        'adm_del_sub_done': "✅ Subscriptions of {uid} removed.",
        'adm_broadcast_prompt': "Send text, photo or document for broadcast:",
        'adm_broadcast_result': "✅ Sent: {sent} | Errors: {errors}",
        'adm_payment_confirm': "To confirm, send \"Yes\".",
        'payment_approved': "✅ Payment confirmed. Subscription activated!",
        'payment_rejected': "❌ Payment rejected. Contact support.",
        # rukla1 menu
        'r1_acc_header': "➕ Add an account. Send a ZIP with .session files or the .session files directly.\n\nAccounts in the database:",
        'r1_acc_empty': "Empty",
        'r1_btn_url_ads': "📣 Manage URL advertising",
        'r1_btn_grp_ads': "💬 Manage group advertising",
        'r1_btn_proxy': "🌍 Connect proxy",
        'r1_btn_del_acc': "❌ Delete account",
        'r1_btn_rename': "💬 Rename accounts",
        'r1_btn_del_avatar': "🗑 Delete avatar(s)",
        'r1_btn_del_users': "🐶 Remove @usernames from all accounts",
        'r1_btn_bio': "📃 Change bio",
        'r1_btn_pers_ch': "🌟 Create personal channel",
        'r1_btn_photo': "👤 Change photo",
        'r1_btn_keywords': "ℹ️ Set keywords",
        'r1_btn_styles': "⌚ Manage message styles",
        'r1_btn_reminders': "📩 Manage reminder style",
        'r1_btn_cycle': "✏️ Cycle repetition",
        'r1_btn_channels': "➕ Manage channels",
        'r1_btn_clear_chats': "🗑 Clear accounts from chats",
        'r1_btn_bot_status': "🤔 Bot status",
        'r1_btn_search_ch': "🪽 Search channels",
        'r1_btn_search_chats': "🪽 Search chats",
        'r1_btn_manage_acc': "📝 Manage accounts",
        'r1_btn_manage_ad_params': "🔗 Manage ad settings",
        'r1_btn_back_main': "⬅️ Return to main menu",
        'r1_btn_back_acc': "⬅️ Go back",
        'r1_btn_back_short': "⬅️ Back",
        'r1_btn_enable': "🟢 Enable",
        'r1_btn_disable': "🔴 Disable",
        'r1_bot_on': "🟢 enabled",
        'r1_bot_off': "🔴 disabled",
        'r1_bot_status_text': "📝 Current bot status:\n\n{status}",
        'r1_grp_bot_status_text': "📝 Bot status (group advertising):\n\n{status}",
        'r1_btn_monitoring': "📘 Set monitoring channel",
        'r1_btn_groups': "➕ Manage groups",
        'r1_greeting': "❕Welcome to the channel advertising bot.",
        'r1_btn_create_folder': "➕ Create channel folder",
        'r1_btn_del_folder': "🗑 Delete channel folder",
        'r1_btn_add_channel': "➕ Add channel/folder",
        'r1_btn_back_channels': "⬅️ Back to channels",
        'r1_channels_header': "➕ Manage channels (channels & folders t.me/addlist/...):\n\n",
        'r1_channels_empty': "➕ Manage channels\n\nNo channel folders yet.\nCreate a folder and add channel links.",
        'r1_auth_pwd_prompt': "🔒 Bot is locked. Enter password:",
        'r1_auth_pwd_ok': "✅ Password accepted!",
        'r1_auth_pwd_wrong': "❌ Incorrect password.",
        'r1_code_sent': "✅ Code sent to {phone}. Enter the code:",
        'r1_2fa_prompt': "🔐 Enter your 2FA password:",
        'r1_acc_ok': "✅ Account {name} successfully connected!",
        'r1_no_accs': "❌ No connected accounts.",
        'r1_del_all_ok': "✅ All accounts deleted: {count}!",
        'r1_del_one_ok': "✅ Account №{num} deleted!",
        'r1_del_range_err': "❌ Invalid range format. Example: 1-5",
        'r1_del_no_num': "❌ No account with that number.",
        'r1_rename_prompt': "Send the new nickname:",
        'r1_rename_ok': "✅ Nicknames changed!",
        'r1_grp_rename_prompt': "💬 {pool_info}Send a list of names (one per line).\nEach account will get a random name.\n\nExample:\nAlexander\nMaria\nDmitry",
        'r1_grp_rename_ok': "✅ Nicknames updated on {changed}/{total} accounts!",
        'r1_grp_rename_empty': "❌ Name list is empty. Send at least one name.",
        'r1_grp_rename_progress': "⏳ Received {n} names. Assigning random nicknames...",
        'r1_bio_prompt': "📃 Enter a new bio for all accounts:",
        'r1_bio_ok': "✅ Bio updated on all accounts!",
        'r1_grp_bio_prompt': "📃 Enter a new bio for all group accounts:",
        'r1_grp_bio_ok': "✅ Bio updated on all group accounts!",
        'r1_del_avatar_progress': "⏳ Removing avatars...",
        'r1_grp_del_avatar_progress': "⏳ Removing avatars (group accounts)...",
        'r1_del_avatar_ok': "✅ Avatars removed: {total}",
        'r1_clear_chats_progress': "⏳ Clearing chats on {n} accounts... This may take a while.",
        'r1_grp_clear_chats_progress': "⏳ Clearing chats on {n} group accounts...",
        'r1_clear_chats_ok': "✅ Done! Chats deleted total: {total}",
        'r1_photo_prompt': "👤 Send a new photo for all accounts:",
        'r1_photo_progress': "⏳ Changing photo on all accounts...",
        'r1_photo_ok': "✅ Photo changed on {success}/{total} accounts!",
        'r1_del_users_progress': "⏳ Removing @username on {n} accounts...",
        'r1_grp_del_users_progress': "⏳ Removing @username on {n} group accounts...",
        'r1_del_users_ok': "✅ Done!\n• Cleared: {cleared}\n• No @username: {skipped}\n• Errors: {failed}",
        'r1_zip_progress': "⏳ Processing ZIP archive...",
        'r1_grp_zip_progress': "⏳ Processing ZIP archive (group accounts)...",
        'r1_zip_ok': "✅ Successfully connected accounts: {loaded}",
        'r1_grp_zip_ok': "✅ Successfully connected accounts (groups): {loaded}",
        'r1_session_progress': "⏳ Processing .session file...",
        'r1_session_bad_name': "❌ Invalid filename.",
        'r1_session_invalid': "❌ Session is invalid or expired.",
        'r1_proxy_no_lib': "❌ PySocks library not installed!\n<code>pip install PySocks</code>",
        'r1_proxy_prompt': "🌍 Provide your proxies in SOCKS5 format\n(multiple — one per line):\n\nFormats:\n• <code>socks5://user:pass@host:port</code>\n• <code>host:port:user:pass</code>\n• <code>host:port</code> (no auth)\n\nCurrent proxies:\n{current}",
        'r1_grp_proxy_prompt': "🌍 Provide proxies for GROUP accounts in SOCKS5 format\n(multiple — one per line):\n\nFormats:\n• <code>socks5://user:pass@host:port</code>\n• <code>host:port:user:pass</code>\n• <code>host:port</code> (no auth)\n\nCurrent proxies:\n{current}",
        'r1_proxy_none': "❌ Could not parse any proxies. Check the format.",
        'r1_proxy_ok': "✅ Proxies successfully added!\n{info}",
        'r1_proxy_result_info': "Accounts: {ok} success, {fail} failed.\n\n{proxies}",
        'r1_no_active_proxies': "No active proxies.",
        'r1_unknown': "Unknown",
        'r1_proxy_del_progress': "⏳ Removing proxies and reconnecting accounts...",
        'r1_proxy_del_ok': "✅ All proxies removed.",
        'r1_proxy_del_reconnect_ok': "✅ All proxies removed. Accounts reconnected without proxies ({ok} success, {fail} failed).",
        'r1_ch_folder_prompt': "📁 Enter a name for the new channel folder:",
        'r1_ch_folder_empty': "❌ Name cannot be empty. Enter a folder name:",
        'r1_ch_folder_exists': "❌ Folder '{name}' already exists. Enter a different name:",
        'r1_ch_folder_ok': "✅ Folder '{name}' created!\nNow add channels to it.",
        'r1_ch_folder_del_ok': "✅ Folder '{name}' deleted!",
        'r1_ch_folder_not_found': "❌ Folder '{name}' not found. Try again:",
        'r1_ch_no_folders': "❌ No folders to delete.",
        'r1_ch_del_folder_list': "🗑 Enter the exact folder name to delete:\n\n{folders}",
        'r1_ch_add_link_prompt': "📎 Send a channel or folder link for '{name}':\n\nFormats:\n• https://t.me/channelname\n• https://t.me/+inviteHash\n• https://t.me/addlist/... (TG folder)",
        'r1_channels_folder_header': "📁 Folder: {name}\n\nChannels ({count}):\n",
        'r1_channels_folder_empty': "📁 Folder: {name}\n\nNo channels yet.\nAdd a channel link.",
        'r1_delete_prompt': "❌ Delete accounts:\n\n{acc_list}Options:\n• Single account: enter number (e.g. <b>2</b>)\n• Range: enter <b>1-5</b>\n• All accounts: enter <b>all</b>",
        'r1_grp_delete_prompt': "❌ Delete accounts (group section):\n\n{acc_list}Options:\n• Single account: enter number (e.g. <b>2</b>)\n• Range: enter <b>1-5</b>\n• All accounts: enter <b>all</b>",
        'r1_avatar_zip_result': "✅ Done!\n👤 Got avatar: {photo} accounts\n🚫 Stayed without avatar: {no_photo} accounts",
        'r1_grp_acc_ok': "✅ Account {name} connected to group section!",
        'r1_ch_link_prompt': "❌ Link cannot be empty. Send a link:",
        'r1_ch_link_added': "✅ Channel added to folder '{name}'!\n⏳ Accounts subscribing in background...",
        'r1_ch_link_exists': "ℹ️ This channel is already in folder '{name}'.",
        'r1_ch_name_prompt': "🌟 Enter the channel name:",
        'r1_ch_avatar_prompt': "✅ Name: {name}\n\n📸 Send a square photo for the channel avatar:",
        'r1_ch_avatar_ok': "✅ Avatar saved!\n\n📝 Send the first post for the channel (can contain photos and formatting):",
        'r1_ch_create_progress': "⏳ Creating channel '{name}' on {n} accounts...",
        'r1_ch_create_ok': "✅ Channels created on {created}/{total} accounts!",
        'r1_avatar_zip_progress': "⏳ Processing avatar ZIP...",
        'r1_avatar_zip_no_imgs': "❌ No PNG/JPG files found in the ZIP.",
        'r1_avatar_zip_ok': "✅ Loaded {count} avatars. Applying (50/50)...",
        'r1_grp_avatar_prompt': "👤 {pool_info}Send a ZIP with avatars (PNG/JPG, up to 50).\n\n⚖️ Assignment:\n• 50% accounts — NO avatar\n• 50% accounts — RANDOM avatar from ZIP",
        'r6_in_dev': "🔧 Section is under development.",
        'r3_search_ch_header': "Channel search complete ({total} with chats):\n\n",
        'r3_search_grp_header': "Groups/chats found ({total}):\n\n",
        'r3_search_cont': "(continued)\n\n",
        'r3_ch_collecting': "🔍 Collecting channel list...",
        'r3_ch_not_found': "❌ No channels found for these keywords.",
        'r3_ch_checking': "✅ Found candidates: {total}\n⏳ Checking for comment chats...",
        'r3_ch_progress': "⏳ Checked {checked}/{total}, found with chat: {found}...",
        'r3_ch_no_chat': "❌ None of the {total} found channels have a comment chat.",
        'r3_grp_no_acc': "❌ No connected accounts in the groups department.",
        'r3_grp_collecting': "🔍 Collecting chats/groups from exchanges and Telegram...",
        'r3_grp_not_found': "❌ No chats/groups found for these keywords.",
        'r3_grp_checking': "✅ Found candidates: {total}\n⏳ Checking chat types...",
        'r3_grp_progress': "⏳ Checked {checked}/{total}, found groups: {found}...",
        'r3_grp_no_groups': "❌ No public groups found among {total} candidates.",
        'r3_searching_ch': "⏳ Running search... This may take a few minutes.",
        'r3_searching_grp': "⏳ Running chat search... This may take a few minutes.",
        'r3_kw_prompt_ch': "🪽 Enter keywords to search channels (comma-separated):",
        'r3_kw_prompt_grp': "🪽 Enter keywords to search chats/groups (comma-separated):\nExample: Kyiv Chat, Discussion, Forum",
        'r2_btn_create_style': "➕ Create style",
        'r2_btn_del_style': "🗑 Delete style",
        'r2_btn_create_rem': "➕ Create reminder",
        'r2_btn_del_rem': "🗑 Delete reminder",
        'r2_btn_set_delay': "⏱ Set delay",
        'r2_btn_set_cycle': "⏱ Set cycle time",
        'r2_btn_add_group': "➕ Add group/chat",
        'r2_btn_del_group': "➖ Delete group",
        'r2_btn_interval': "⏱ Cycle interval",
        'r2_btn_repeat': "🔁 Repeat count",
        'r2_btn_add_chan': "➕ Add channel",
        'r2_btn_del_chan': "➖ Remove channel",
        'r2_not_set': "not set",
        'r2_mon_active': "🟢 active",
        'r2_mon_stopped': "🔴 stopped",
        'r2_grp_empty': "(empty)",
        'r2_styles_empty': "No saved styles.",
        'r2_styles_header': "⌚ Manage message styles:\n\n{styles}",
        'r2_rems_empty': "No saved reminders.",
        'r2_rems_header': "📩 Manage reminders:\n\n{rems}\n\n⏱ Delay: {delay} sec.",
        'r2_cycle_off': "Disabled",
        'r2_cycle_header': "✏️ Cycle repetition:\n\nDelay: {state}\n(0 — disable).",
        'r2_grp_menu_header': "➕ Manage groups for reposts\n\n📘 Monitoring channel: {chan}\nMonitoring status: {status}\n⏱ Cycle interval: {interval} sec.\n🔁 Repeat count: {repeat}\n\nGroups in DB:\n{chats}",
        'r2_kw_prompt': "ℹ️ Current keywords: {kw}\n\nEnter keywords separated by commas.\nIf the list is empty — the bot comments all posts.\nExample: News, Recipe, Politics, President",
        'r2_kw_empty': "empty",
        'r2_kw_ok': "✅ Keywords set:\n{kw}\n\nIf the list is empty — the bot comments all posts.",
        'r2_style_name_prompt': "📝 Style name:",
        'r2_style_name_ok': "✅ Style name: {name}\n\n📝 Send the style text:",
        'r2_style_saved': "✅ Style '{name}' saved!",
        'r2_style_deleted': "🗑 Style deleted!",
        'r2_style_active': "✅ Active style: '{name}'",
        'r2_rem_name_prompt': "📝 Reminder name:",
        'r2_rem_name_ok': "✅ Reminder name: {name}\n\n📝 Send the reminder text:",
        'r2_rem_saved': "✅ Reminder saved!",
        'r2_rem_deleted': "🗑 Reminder deleted!",
        'r2_del_name_prompt': "Enter name to delete:",
        'r2_delay_prompt': "⏱ Enter delay in seconds:",
        'r2_rem_delay_ok': "✅ Reminder delay: {secs} sec.",
        'r2_cycle_delay_prompt': "⏱ Cycle delay (sec):",
        'r2_cycle_delay_ok': "✅ Cycle delay: {secs} sec.",
        'r2_folder_name_prompt': "📁 Folder name:",
        'r2_folder_name_ok': "✅ Folder name: {name}\n\n🔗 Send channel links (one per line):",
        'r2_folder_saving': "⏳ Saving channels and folders...",
        'r2_folder_saved': "✅ Done!",
        'r2_folder_deleting': "⏳ Removing folder and leaving channels...",
        'r2_folder_deleted': "🗑 Folder deleted!",
        'r2_folder_view': "📁 '{name}':\n\n{links}",
        'r2_add_chan_prompt': "Send a link (addlist folders are also supported):",
        'r2_del_chan_prompt': "Send the link to remove:",
        'r2_chan_adding': "✅ Added. Joining...",
        'r2_chan_removing': "⏳ Removing and leaving channel...",
        'r2_chan_removed': "✅ Removed.",
        'r2_mon_prompt': "📘 Set monitoring channel\n\nCurrent channel: {chan}\nStatus: {status}\n\nEnter the country name for filtering\n(e.g. Ukraine):",
        'r2_mon_country_ok': "✅ Country: {country}\n\n📎 Send the channel link for monitoring (e.g. https://t.me/channel):",
        'r2_mon_set_ok': "✅ Channel set: {link}\n🟢 Monitoring activated!\n\nFilter country: {country}\nGroups in DB: {grps}\nRepost interval: {interval} sec.",
        'r2_mon_set_warn': "⚠️ Channel saved, but failed to connect: {e}\nTry after connecting accounts.",
        'r2_mon_set_no_acc': "⚠️ Channel saved. Connect accounts — monitoring will activate automatically.",
        'r2_mon_stopped_msg': "🔴 Monitoring stopped.",
        'r2_mon_started_msg': "🟢 Monitoring activated!",
        'r2_mon_not_ready': "❌ First set the channel and connect accounts.",
        'r2_interval_prompt': "⏱ Current cycle interval: {cur} sec.\n\nEnter new value in seconds (e.g. 180):",
        'r2_interval_ok': "✅ Cycle interval set: {secs} sec.",
        'r2_interval_err': "❌ Invalid value. Enter a whole number of seconds.",
        'r2_repeat_prompt': "🔁 Current repeat count: {cur}\n\nEnter new value (e.g. 5):",
        'r2_repeat_ok': "✅ Repeat count set: {n}",
        'r2_repeat_err': "❌ Invalid value. Enter a whole number.",
        'r2_grp_empty_db': "❌ Group database is empty.",
        'r2_del_group_prompt': "➖ Enter group number to delete:\n\n{list}",
        'r2_grp_deleted': "🗑 Removed: {title}",
        'r2_grp_del_no_num': "❌ No group with that number.",
        'r2_grp_enter_num': "❌ Enter a group number.",
        'r2_add_group_prompt': "➕ Add groups/chats\n\nSend links (one per line).\nPublic: https://t.me/username\nPrivate: https://t.me/+invitehash\n\n⚠️ For private groups the bot will send a join request and wait for approval.",
        'r2_grp_no_link': "❌ No links found.",
        'r2_grp_processing': "⏳ Processing {n} links...",
        'r2_grp_added': "✅ Groups added: {added}",
        'r2_grp_add_warn': "\n⚠️ Failed to join / request pending: {n}",
        'r2_view_group': "📌 Group №{n}\nName: {title}\nLink: {link}\nID: {id}",
    },
    'ru': {
        'greeting': "❕Добро пожаловать в бот для рекламы вашего канала.",
        'locked': "❌ Функция заблокирована. Пополните баланс для покупки подписки.",
        'info': "Важная информация... (добавьте полный текст)",
        'profile': (
            "Профиль пользователя:\n"
            "{name} ({uid}) {uname}\n\n"
            "💵 Баланс бота: {balance}$\n\n"
            "┏  📣 Подписка на URL рекламу активна до: {sub_url}\n"
            "┣ 💬 Подписка на рекламу в группах активна до: {sub_groups}\n"
            "┗ 🛩 Подписка на рекламу в TikTok активна до: {sub_tiktok}"
        ),
        'balance': (
            "💸 Ваш текущий баланс: {balance}$.\n"
            "Для пополнения баланса выберите один из вариантов:\n"
            "‼️ Важно: Пополнение баланса работает с 10:00 до 22:00 по Киевскому времени. Платежи в нерабочее время будут обработаны в начале следующей смены."
        ),
        'support_intro': (
            "👋 Добро пожаловать в техническую поддержку нашего проекта.\n\n"
            "⏰ Часы работы поддержки: 10:00 - 22:00 по Киевскому времени.\n\n"
            "📝 Чтобы начать диалог, нажмите кнопку:"
        ),
        'support_start_chat': "⬇️ Напишите ваш вопрос. Среднее время ответа технической поддержки — до 30 минут.",
        'support_accepted': "Заявка принята.",
        'support_rejected': "Заявка отклонена.",
        'support_closed': "Диалог завершен.",
        'b_profile': "👤 Профиль",
        'acc_shop_greeting': (
            "👋 Добро пожаловать в меню покупки аккаунтов/прокси для ваших ботов.\n"
            "Выберите что вам нужно:"
        ),
        'acc_shop_btn_tg':    "📞 Аккаунты Telegram",
        'acc_shop_btn_tt':    "📱 Аккаунты Tik-Tok",
        'acc_shop_btn_proxy': "🌐 Прокси",
        'acc_shop_locked': "⛔️ Данная страница заблокирована. Для доступа необходима хотя бы одна активная подписка.",
        'shop_greeting': "👋 Добро пожаловать в магазин дополнительных функций:",
        'tiktok_menu_text': "➕ Добавьте аккаунт. Отправьте один или несколько Cookie для добавления аккаунта.\n\nАккаунты в базе:",
        'tiktok_no_accounts': "Аккаунтов нет.",
        'tiktok_btn_add': "➕ Добавить аккаунт (Cookie)",
        'tiktok_ask_cookie': "📋 Отправьте Cookie строку(и) для TikTok аккаунта.\nКаждый аккаунт — отдельным сообщением или через новую строку.",
        'tiktok_btn_cancel': "⬅️ Отмена",
        'tiktok_checking': "⏳ Проверяю аккаунт(ы)...",
        'tiktok_added': "✅ Успешно добавлено: {added}",
        'tiktok_failed': "❌ Нет доступа (проверьте cookie): {failed}",
        'b_url': "📣 Управление URL рекламой",
        'b_grp': "💬 Управление рекламой в группах",
        'b_balance': "💵 Пополнить баланс",
        'b_buy_acc': "📲 Купить аккаунты и прокси",
        'b_manage_ad': "📢 Управление рекламой",
        'manage_ad_greeting': "Добро пожаловать в меню управления рекламой вашего блога. Выберите одну из доступных функций:",
        'b_manage_accounts': "📝 Управление аккаунтами",
        'b_manage_ad_params': "🔗 Управление параметрами рекламы",
        'b_buy_acc_url': "📱 Купить аккаунты для URL рекламы",
        'b_buy_acc_grp': "📱 Купить аккаунты для рекламы в группах",
        'b_buy_acc_tt':  "📱 Купить аккаунты для рекламы в TikTok",
        'b_buy_proxy_url': "🌍 Купить прокси для URL рекламы",
        'b_buy_proxy_grp': "🌍 Купить прокси для рекламы в группах",
        'b_buy_proxy_tt':  "🌍 Купить прокси для рекламы в TikTok",
        'buy_acc_greeting': "👋 Добро пожаловать в меню покупки аккаунтов.",
        'b_back_prev': "⬅️ Вернуться на предыдущую страницу",
        'r7_ctx_url':    "URL рекламы",
        'r7_ctx_grp':    "рекламы в группах",
        'r7_ctx_tiktok': "рекламы в TikTok",
        'r7_kind_acc':   "аккаунты",
        'r7_kind_proxy': "прокси",
        'r7_menu_greeting': "👋 Добро пожаловать в меню покупки аккаунтов.",
        'r7_ask_qty': "💵 Цена за один {kind} 0.50$.\n\nВведите количество {kind} для {label}:",
        'r7_qty_invalid': "❌ Неверное число. Введите целое число от 1 до 1000.",
        'r7_checkout': (
            "🧾 <b>Чек:</b>\n\n"
            "📦 {kind} для {label}\n"
            "🔢 Количество: {qty}\n"
            "💵 Цена: {price}$ × {qty} = <b>{total}$</b>\n\n"
            "💳 Ваш баланс: {balance}$\n\n"
            "Выберите способ оплаты:"
        ),
        'r7_pay_balance': "💰 Оплатить с баланса",
        'r7_pay_card':    "💳 Оплатить картой",
        'r7_pay_crypto':  "🪙 Оплатить криптой",
        'r7_pay_external_dev': "ℹ️ Оплата картой/криптой временно недоступна. Используйте баланс или обратитесь в поддержку.",
        'r7_paid_wait': "⏱ Ожидайте ответа от администрации.",
        'r7_admin_new_order': (
            "🛒 <b>Новый заказ #{oid}</b>\n\n"
            "👤 Пользователь {name} ({uid}) {uname} оплатил {total}$ "
            "для покупки {qty}× {kind} для {label}.\n\n"
            "Выберите действие:"
        ),
        'r7_admin_approve': "✅ Подтвердить оплату",
        'r7_admin_reject':  "❌ Отклонить оплату",
        'r7_admin_contact': "💬 Связаться с пользователем",
        'r7_admin_send_n': "📦 Пришлите {qty}× файлов ({ext}) для заказа #{oid}.\nКогда закончите — /done.",
        'r7_delivery_progress': "📥 Получено {got}/{need}",
        'r7_delivery_short': "⚠️ Получено {got}/{need}. Пришлите ещё {need} файлов.",
        'r7_delivery_done': "✅ Заказ #{oid} выполнен: переслано {n} файлов пользователю.",
        'r7_user_delivered': "✅ Заказ #{oid} выполнен! Вы получили {qty}× {kind} для {label}.",
        'r7_user_rejected':  "❌ Ваш заказ #{oid} отклонён. Средства ({total}$) возвращены на баланс.",
        'r7_admin_contact_open': "💬 Диалог с пользователем {uid} (#{oid}) начат. /close чтобы завершить.",
        'r7_user_contact_open':  "💬 Администрация связалась с вами по заказу #{oid}. /close чтобы завершить.",
        'r7_contact_closed': "✅ Диалог завершён.",
        'r1_acc_limit': "⛔️ Лимит аккаунтов. Чтобы добавить новый аккаунт - удалите старый. Лимит аккаунтов составляет 25 единиц.",
        'b_manage_users': "📓 Управление пользователями",
        'b_send_msg_to_user': "📨 Отправить сообщение пользователю",
        'send_msg_ask_uid': "Введите ID пользователя, которому отправить сообщение:",
        'send_msg_ask_text': "Введите текст сообщения (можно прикрепить фото с подписью):",
        'send_msg_user_not_found': "❌ Пользователь с таким ID не найден.",
        'send_msg_sent': "✅ Сообщение отправлено пользователю {uid}.",
        'send_msg_failed': "❌ Не удалось отправить сообщение: {err}",
        'btn_attach_ask': "Прикрепить кнопку к сообщению?",
        'btn_attach_create_new': "➕ Создать новую кнопку",
        'btn_attach_pick_existing': "🔘 Выбрать кнопку бота",
        'btn_attach_none': "🚫 Без кнопки",
        'btn_create_ask_text': "Введите текст кнопки:",
        'btn_create_ask_url': "Введите URL кнопки (https://...):",
        'b_support': "💻 Связь с поддержкой",
        'b_lang': "🌐 Изменить язык",
        'b_discount': "👥 Получить скидку",
        'b_back': "⬅️ Назад",
        'b_topup': "💵 Пополнить баланс",
        'buy_url_m': "📣 Месяц URL ~ 99$",
        'buy_grp_m': "💬 Месяц группы ~ 99$",
        'buy_url_y': "📣 Год URL ~ 1099$",
        'buy_grp_y': "💬 Год группы ~ 1099$",
        'buy_mix_m': "💭 Месяц URL+Группы ~ 149$",
        'buy_mix_y': "🗯 Год URL+Группы ~ 1399$",
        'buy_tiktok_m': "📱 Месяц TikTok ~ 79$",
        'buy_tiktok_y': "📲 Год TikTok ~ 869$",
        'buy_all':      "🔋 Все сервисы ~ 1999$",
        'pay_from_balance': "💰 Оплатить с баланса",
        'buy_custom': "💵 Произвольная сумма",
        'payment_prompt': "💳 К оплате: {amount}$.\nВыберите способ:",
        'custom_amount_prompt': "💳 Укажите сумму (минимум 10$):",
        'min_amount_error': "Сумма не может быть меньше 10$.",
        'invalid_amount_error': "❌ Ошибка. Введите число.",
        'wallet_info': (
            "💳 К оплате: {amount}$.\n"
            "‼️ Комиссия сети покрывается отправителем!\n\n"
            "Адрес ({name}):\n{address}\n\n"
            "После перевода нажмите «Я оплатил»."
        ),
        'i_paid': "✅ Я оплатил",
        'send_screenshot': "📃 Отправьте скриншот оплаты:\n‼️ Хорошее качество обязательно.",
        'not_screenshot': "Это не скриншот. Попробуйте снова.",
        'payment_wait': "⏳ Ожидайте подтверждения администратора.",
        'rukla1_missing': "❌ Модуль rukla1.py не найден.",
        'sub_expired': "‼️ Срок действия вашей подписки на {type} истёк. Для продления нажмите «Купить подписку».",
        'sub_btn_buy': "💵 Купить подписку",
        'adm_info_btn': "🔦 Информация о пользователях",
        'adm_give_sub_btn': "➕ Выдать подписку",
        'adm_del_sub_btn': "➖ Удалить подписку",
        'adm_add_bal_btn': "💸 Пополнить баланс",
        'adm_rem_bal_btn': "❌ Снять с баланса",
        'adm_broadcast_btn': "🌐 Рассылка",
        'adm_enter_id_amount': "Введите ID и сумму (напр: 123456789 50):",
        'adm_bal_added': "✅ Баланс {uid} пополнен на {amount}$.",
        'adm_user_bal_added': "✅ Ваш баланс пополнен на {amount}$!",
        'adm_enter_id_remove': "Введите ID и сумму для снятия:",
        'adm_bal_removed': "✅ С баланса {uid} снято {amount}$.",
        'adm_enter_id_sub': "Введите ID пользователя:",
        'adm_sub_type': "Тип подписки:",
        'adm_sub_url': "📣 URL",
        'adm_sub_grp': "💬 Группы",
        'adm_sub_tiktok': "🛩 TikTok",
        'adm_sub_mix': "💭 URL + Группы",
        'adm_sub_all': "🌐 URL + Группы + TikTok",
        'b_tiktok': "🛩 Реклама в TikTok",
        'b_shop': "🏪 Магазин дополнительных функций",
        'buy_from_balance': "💰 Купить с баланса",
        'not_enough_balance': "❌ Недостаточно средств. Баланс: {balance}$, нужно: {price}$.",
        'bought_with_balance': "✅ Подписка куплена за {price}$ с баланса!",
        'adm_enter_term': "Введите срок (напр: 10 min, 10 day, lifetime):",
        'adm_sub_given': "✅ Подписка выдана пользователю {uid}.",
        'adm_sub_notify': "✅ Вам выдана подписка!",
        'adm_del_sub_confirm': "Введите ID для удаления всех подписок:",
        'adm_del_sub_done': "✅ Подписки {uid} удалены.",
        'adm_broadcast_prompt': "Отправьте текст, фото или документ для рассылки:",
        'adm_broadcast_result': "✅ Отправлено: {sent} | Ошибок: {errors}",
        'adm_payment_confirm': "Для подтверждения отправьте \"Да\".",
        'payment_approved': "✅ Платёж подтвержден. Подписка активирована!",
        'payment_rejected': "❌ Платёж отклонен. Обратитесь в поддержку.",
        # rukla1 menu
        'r1_acc_header': "➕ Добавьте аккаунт. Отправьте ZIP с .session файлами или сами .session файлы.\n\nАккаунты в базе:",
        'r1_acc_empty': "Пусто",
        'r1_btn_url_ads': "📣 Управление URL рекламой",
        'r1_btn_grp_ads': "💬 Управление рекламой в группах",
        'r1_btn_proxy': "🌍 Подключить прокси",
        'r1_btn_del_acc': "❌ Удалить аккаунт",
        'r1_btn_rename': "💬 Переименовать аккаунты",
        'r1_btn_del_avatar': "🗑 Удалить аватар(ы)",
        'r1_btn_del_users': "🐶 Удалить @username на всех аккаунтах",
        'r1_btn_bio': "📃 Изменить описание",
        'r1_btn_pers_ch': "🌟 Создать персональный канал",
        'r1_btn_photo': "👤 Изменить фото",
        'r1_btn_keywords': "ℹ️ Установить ключевые слова",
        'r1_btn_styles': "⌚ Управление стилями сообщений",
        'r1_btn_reminders': "📩 Управление стилем напоминаний",
        'r1_btn_cycle': "✏️ Повторение цикла",
        'r1_btn_channels': "➕ Управление каналами",
        'r1_btn_clear_chats': "🗑 Очистить аккаунты от чатов",
        'r1_btn_bot_status': "🤔 Статус бота",
        'r1_btn_search_ch': "🪽 Поиск каналов",
        'r1_btn_search_chats': "🪽 Поиск чатов",
        'r1_btn_manage_acc': "📝 Управление аккаунтами",
        'r1_btn_manage_ad_params': "🔗 Настройки рекламы",
        'r1_btn_back_main': "⬅️ Вернуться в главное меню",
        'r1_btn_back_acc': "⬅️ Вернуться назад",
        'r1_btn_back_short': "⬅️ Назад",
        'r1_btn_enable': "🟢 Включить",
        'r1_btn_disable': "🔴 Выключить",
        'r1_bot_on': "🟢 включён",
        'r1_bot_off': "🔴 выключен",
        'r1_bot_status_text': "📝 Текущий статус бота:\n\n{status}",
        'r1_grp_bot_status_text': "📝 Статус бота (реклама в группах):\n\n{status}",
        'r1_btn_monitoring': "📘 Установить канал для чтения",
        'r1_btn_groups': "➕ Управление группами",
        'r1_greeting': "❕Добро пожаловать в бот для рекламы вашего канала.",
        'r1_btn_create_folder': "➕ Создать папку каналов",
        'r1_btn_del_folder': "🗑 Удалить папку каналов",
        'r1_btn_add_channel': "➕ Добавить канал/папку",
        'r1_btn_back_channels': "⬅️ Назад к каналам",
        'r1_channels_header': "➕ Управление каналами (каналы и папки t.me/addlist/...):\n\n",
        'r1_channels_empty': "➕ Управление каналами\n\nПока нет папок каналов.\nСоздайте папку и добавьте ссылки на каналы.",
        'r1_auth_pwd_prompt': "🔒 Бот заблокирован. Введите пароль:",
        'r1_auth_pwd_ok': "✅ Пароль принят!",
        'r1_auth_pwd_wrong': "❌ Неверный пароль.",
        'r1_code_sent': "✅ Код отправлен на {phone}. Введите код:",
        'r1_2fa_prompt': "🔐 Введите пароль 2FA:",
        'r1_acc_ok': "✅ Аккаунт {name} успешно подключён!",
        'r1_no_accs': "❌ Нет подключённых аккаунтов.",
        'r1_del_all_ok': "✅ Удалено всех аккаунтов: {count}!",
        'r1_del_one_ok': "✅ Аккаунт №{num} удалён!",
        'r1_del_range_err': "❌ Неверный формат диапазона. Пример: 1-5",
        'r1_del_no_num': "❌ Нет аккаунта с таким номером.",
        'r1_rename_prompt': "Отправьте новый никнейм:",
        'r1_rename_ok': "✅ Ники изменены!",
        'r1_grp_rename_prompt': "💬 {pool_info}Отправьте список имён (по одному на строку).\nКаждый аккаунт получит случайное имя.\n\nПример:\nАлексей\nМария\nДмитрий",
        'r1_grp_rename_ok': "✅ Никнеймы обновлены на {changed}/{total} аккаунтах!",
        'r1_grp_rename_empty': "❌ Список имён пуст. Отправьте хотя бы одно имя.",
        'r1_grp_rename_progress': "⏳ Получено {n} имён. Назначаю случайные никнеймы...",
        'r1_bio_prompt': "📃 Введите новое описание (bio) для всех аккаунтов:",
        'r1_bio_ok': "✅ Описание изменено на всех аккаунтах!",
        'r1_grp_bio_prompt': "📃 Введите новое описание (bio) для всех аккаунтов группового отдела:",
        'r1_grp_bio_ok': "✅ Описание изменено на всех аккаунтах группового отдела!",
        'r1_del_avatar_progress': "⏳ Удаляю аватарки...",
        'r1_grp_del_avatar_progress': "⏳ Удаляю аватарки (групповой отдел)...",
        'r1_del_avatar_ok': "✅ Удалено аватарок: {total}",
        'r1_clear_chats_progress': "⏳ Очищаю чаты на {n} аккаунтах... Это может занять время.",
        'r1_grp_clear_chats_progress': "⏳ Очищаю чаты на {n} аккаунтах (групповой отдел)...",
        'r1_clear_chats_ok': "✅ Готово! Удалено чатов всего: {total}",
        'r1_photo_prompt': "👤 Отправьте новое фото для всех аккаунтов:",
        'r1_photo_progress': "⏳ Меняю фото на всех аккаунтах...",
        'r1_photo_ok': "✅ Фото изменено на {success}/{total} аккаунтах!",
        'r1_del_users_progress': "⏳ Удаляю @username на {n} аккаунтах...",
        'r1_grp_del_users_progress': "⏳ Удаляю @username на {n} аккаунтах групп...",
        'r1_del_users_ok': "✅ Готово!\n• Очищено: {cleared}\n• Без @username: {skipped}\n• Ошибок: {failed}",
        'r1_zip_progress': "⏳ Обрабатываю ZIP-архив...",
        'r1_grp_zip_progress': "⏳ Обрабатываю ZIP-архив (групповой отдел)...",
        'r1_zip_ok': "✅ Успешно подключено аккаунтов: {loaded}",
        'r1_grp_zip_ok': "✅ Успешно подключено аккаунтов (группы): {loaded}",
        'r1_session_progress': "⏳ Обрабатываю .session файл...",
        'r1_session_bad_name': "❌ Некорректное имя файла.",
        'r1_session_invalid': "❌ Сессия недействительна или истекла.",
        'r1_proxy_no_lib': "❌ Библиотека PySocks не установлена!\n<code>pip install PySocks</code>",
        'r1_proxy_prompt': "🌍 Предоставьте прокси в формате SOCKS5\n(несколько — каждый с новой строки):\n\nФорматы:\n• <code>socks5://user:pass@host:port</code>\n• <code>host:port:user:pass</code>\n• <code>host:port</code> (без авторизации)\n\nТекущие прокси:\n{current}",
        'r1_grp_proxy_prompt': "🌍 Предоставьте прокси для аккаунтов ГРУПП в формате SOCKS5\n(несколько — каждый с новой строки):\n\nФорматы:\n• <code>socks5://user:pass@host:port</code>\n• <code>host:port:user:pass</code>\n• <code>host:port</code> (без авторизации)\n\nТекущие прокси:\n{current}",
        'r1_proxy_none': "❌ Не удалось распознать ни одного прокси. Проверьте формат.",
        'r1_proxy_ok': "✅ Прокси успешно добавлены!\n{info}",
        'r1_proxy_result_info': "Аккаунты: {ok} успешно, {fail} неудачно.\n\n{proxies}",
        'r1_no_active_proxies': "Нет активных прокси.",
        'r1_unknown': "Неизвестно",
        'r1_proxy_del_progress': "⏳ Удаляю прокси и переподключаю аккаунты без прокси...",
        'r1_proxy_del_ok': "✅ Все прокси удалены.",
        'r1_proxy_del_reconnect_ok': "✅ Все прокси удалены. Аккаунты переподключены без прокси ({ok} успешно, {fail} неудачно).",
        'r1_ch_folder_prompt': "📁 Введите название новой папки каналов:",
        'r1_ch_folder_empty': "❌ Название не может быть пустым. Введите название папки:",
        'r1_ch_folder_exists': "❌ Папка '{name}' уже существует. Введите другое название:",
        'r1_ch_folder_ok': "✅ Папка '{name}' создана!\nТеперь добавьте в неё каналы.",
        'r1_ch_folder_del_ok': "✅ Папка '{name}' удалена!",
        'r1_ch_folder_not_found': "❌ Папки '{name}' не существует. Попробуйте ещё раз:",
        'r1_ch_no_folders': "❌ Нет папок для удаления.",
        'r1_ch_del_folder_list': "🗑 Введите точное название папки для удаления:\n\n{folders}",
        'r1_ch_add_link_prompt': "📎 Отправьте ссылку на канал или папку для '{name}':\n\nФорматы:\n• https://t.me/channelname\n• https://t.me/+inviteHash\n• https://t.me/addlist/... (папка TG)",
        'r1_channels_folder_header': "📁 Папка: {name}\n\nКаналы ({count}):\n",
        'r1_channels_folder_empty': "📁 Папка: {name}\n\nПока каналов нет.\nДобавьте ссылку на канал.",
        'r1_delete_prompt': "❌ Удаление аккаунтов:\n\n{acc_list}Варианты:\n• Один аккаунт: введите номер (например: <b>2</b>)\n• Диапазон: введите <b>1-5</b>\n• Все аккаунты: введите <b>all</b>",
        'r1_grp_delete_prompt': "❌ Удаление аккаунтов (групповой отдел):\n\n{acc_list}Варианты:\n• Один аккаунт: введите номер (например: <b>2</b>)\n• Диапазон: введите <b>1-5</b>\n• Все аккаунты: введите <b>all</b>",
        'r1_avatar_zip_result': "✅ Готово!\n👤 Получили аватарку: {photo} аккаунтов\n🚫 Остались без аватарки: {no_photo} аккаунтов",
        'r1_grp_acc_ok': "✅ Аккаунт {name} подключён к групповому отделу!",
        'r1_ch_link_prompt': "❌ Ссылка не может быть пустой. Отправьте ссылку:",
        'r1_ch_link_added': "✅ Канал добавлен в папку '{name}'!\n⏳ Аккаунты подписываются в фоне...",
        'r1_ch_link_exists': "ℹ️ Этот канал уже есть в папке '{name}'.",
        'r1_ch_name_prompt': "🌟 Введите название канала:",
        'r1_ch_avatar_prompt': "✅ Название: {name}\n\n📸 Отправьте квадратное фото для аватарки канала:",
        'r1_ch_avatar_ok': "✅ Аватарка сохранена!\n\n📝 Отправьте первый пост для канала (может содержать фото и форматирование):",
        'r1_ch_create_progress': "⏳ Создаю канал '{name}' на {n} аккаунтах...",
        'r1_ch_create_ok': "✅ Каналы созданы на {created}/{total} аккаунтах!",
        'r1_avatar_zip_progress': "⏳ Обрабатываю ZIP с аватарками...",
        'r1_avatar_zip_no_imgs': "❌ В ZIP не найдено ни одного PNG/JPG файла.",
        'r1_avatar_zip_ok': "✅ Загружено {count} аватарок. Применяю (50/50)...",
        'r1_grp_avatar_prompt': "👤 {pool_info}Отправьте ZIP с аватарками (PNG/JPG, до 50 штук).\n\n⚖️ Назначение:\n• 50% аккаунтов — БЕЗ аватарки\n• 50% аккаунтов — СЛУЧАЙНАЯ аватарка из ZIP",
        'r6_in_dev': "🔧 Раздел в разработке.",
        'r3_search_ch_header': "Поиск каналов завершён ({total} с чатом):\n\n",
        'r3_search_grp_header': "Найдено групп/чатов ({total}):\n\n",
        'r3_search_cont': "(продолжение)\n\n",
        'r3_ch_collecting': "🔍 Собираю список каналов...",
        'r3_ch_not_found': "❌ По этим ключевым словам каналов не найдено.",
        'r3_ch_checking': "✅ Найдено кандидатов: {total}\n⏳ Проверяю наличие чата комментариев...",
        'r3_ch_progress': "⏳ Проверено {checked}/{total}, найдено с чатом: {found}...",
        'r3_ch_no_chat': "❌ Среди {total} найденных каналов ни один не имеет чата комментариев.",
        'r3_grp_no_acc': "❌ Нет подключённых аккаунтов в отделе групп.",
        'r3_grp_collecting': "🔍 Собираю список чатов/групп с бирж и Telegram...",
        'r3_grp_not_found': "❌ По этим ключевым словам чатов/групп не найдено.",
        'r3_grp_checking': "✅ Найдено кандидатов: {total}\n⏳ Проверяю типы чатов...",
        'r3_grp_progress': "⏳ Проверено {checked}/{total}, найдено групп: {found}...",
        'r3_grp_no_groups': "❌ Среди {total} кандидатов публичных групп не найдено.",
        'r3_searching_ch': "⏳ Выполняю поиск... Это может занять несколько минут.",
        'r3_searching_grp': "⏳ Выполняю поиск чатов... Это может занять несколько минут.",
        'r3_kw_prompt_ch': "🪽 Введите ключевые слова для поиска каналов (через запятую):",
        'r3_kw_prompt_grp': "🪽 Введите ключевые слова для поиска чатов/групп (через запятую):\nПример: Чат Киев, Обсуждение, Форум",
        'r2_btn_create_style': "➕ Создать стиль",
        'r2_btn_del_style': "🗑 Удалить стиль",
        'r2_btn_create_rem': "➕ Создать напоминание",
        'r2_btn_del_rem': "🗑 Удалить напоминание",
        'r2_btn_set_delay': "⏱ Установить задержку",
        'r2_btn_set_cycle': "⏱ Установить время цикла",
        'r2_btn_add_group': "➕ Добавить группу/чат",
        'r2_btn_del_group': "➖ Удалить группу",
        'r2_btn_interval': "⏱ Интервал между циклами",
        'r2_btn_repeat': "🔁 Количество повторений",
        'r2_btn_add_chan': "➕ Добавить канал",
        'r2_btn_del_chan': "➖ Удалить канал",
        'r2_not_set': "не установлено",
        'r2_mon_active': "🟢 активный",
        'r2_mon_stopped': "🔴 остановлен",
        'r2_grp_empty': "(пусто)",
        'r2_styles_empty': "Нет сохранённых стилей.",
        'r2_styles_header': "⌚ Управление стилями сообщений:\n\n{styles}",
        'r2_rems_empty': "Нет сохранённых напоминаний.",
        'r2_rems_header': "📩 Управление напоминаниями:\n\n{rems}\n\n⏱ Задержка: {delay} сек.",
        'r2_cycle_off': "Выключено",
        'r2_cycle_header': "✏️ Повторение цикла:\n\nЗадержка: {state}\n(0 — выключить).",
        'r2_grp_menu_header': "➕ Управление группами для репостов\n\n📘 Канал мониторинга: {chan}\nСтатус мониторинга: {status}\n⏱ Интервал между циклами: {interval} сек.\n🔁 Количество повторений: {repeat}\n\nГруппы в базе:\n{chats}",
        'r2_kw_prompt': "ℹ️ Текущие ключевые слова: {kw}\n\nВведите ключевые слова через запятую.\nЕсли список пуст — бот комментирует все посты.\nПример: Новости, Рецепт, Политика, Президент",
        'r2_kw_empty': "пусто",
        'r2_kw_ok': "✅ Ключевые слова установлены:\n{kw}\n\nЕсли список пуст — бот комментирует все посты.",
        'r2_style_name_prompt': "📝 Название стиля:",
        'r2_style_name_ok': "✅ Название стиля: {name}\n\n📝 Отправьте текст стиля:",
        'r2_style_saved': "✅ Стиль '{name}' сохранён!",
        'r2_style_deleted': "🗑 Стиль удалён!",
        'r2_style_active': "✅ Активный стиль: '{name}'",
        'r2_rem_name_prompt': "📝 Название напоминания:",
        'r2_rem_name_ok': "✅ Название напоминания: {name}\n\n📝 Отправьте текст напоминания:",
        'r2_rem_saved': "✅ Напоминание сохранено!",
        'r2_rem_deleted': "🗑 Напоминание удалено!",
        'r2_del_name_prompt': "Введите название для удаления:",
        'r2_delay_prompt': "⏱ Введите задержку в секундах:",
        'r2_rem_delay_ok': "✅ Задержка напоминаний: {secs} сек.",
        'r2_cycle_delay_prompt': "⏱ Задержка между циклами (сек):",
        'r2_cycle_delay_ok': "✅ Задержка цикла: {secs} сек.",
        'r2_folder_name_prompt': "📁 Название папки:",
        'r2_folder_name_ok': "✅ Название папки: {name}\n\n🔗 Отправьте ссылки на каналы (каждая с новой строки):",
        'r2_folder_saving': "⏳ Сохраняю каналы и папки...",
        'r2_folder_saved': "✅ Готово!",
        'r2_folder_deleting': "⏳ Удаляю папку и выхожу из каналов...",
        'r2_folder_deleted': "🗑 Папка удалена!",
        'r2_folder_view': "📁 '{name}':\n\n{links}",
        'r2_add_chan_prompt': "Отправьте ссылку (папки addlist также поддерживаются):",
        'r2_del_chan_prompt': "Отправьте ссылку для удаления:",
        'r2_chan_adding': "✅ Добавлено. Вступаю...",
        'r2_chan_removing': "⏳ Удаляю и выхожу из канала...",
        'r2_chan_removed': "✅ Удалено.",
        'r2_mon_prompt': "📘 Установить канал мониторинга\n\nТекущий канал: {chan}\nСтатус: {status}\n\nВведите название страны для фильтрации\n(например: Украина):",
        'r2_mon_country_ok': "✅ Страна: {country}\n\n📎 Отправьте ссылку на канал для чтения (например: https://t.me/channel):",
        'r2_mon_set_ok': "✅ Канал установлен: {link}\n🟢 Мониторинг активирован!\n\nСтрана фильтрации: {country}\nГрупп в базе: {grps}\nИнтервал репоста: {interval} сек.",
        'r2_mon_set_warn': "⚠️ Канал сохранён, но не удалось подключиться: {e}\nПопробуйте после подключения аккаунтов.",
        'r2_mon_set_no_acc': "⚠️ Канал сохранён. Подключите аккаунты — мониторинг активируется автоматически.",
        'r2_mon_stopped_msg': "🔴 Мониторинг остановлен.",
        'r2_mon_started_msg': "🟢 Мониторинг активирован!",
        'r2_mon_not_ready': "❌ Сначала установите канал и подключите аккаунты.",
        'r2_interval_prompt': "⏱ Текущий интервал между циклами: {cur} сек.\n\nВведите новое значение в секундах (например: 180):",
        'r2_interval_ok': "✅ Интервал между циклами установлен: {secs} сек.",
        'r2_interval_err': "❌ Неверное значение. Введите целое число секунд.",
        'r2_repeat_prompt': "🔁 Текущее количество повторений: {cur}\n\nВведите новое значение (например: 5):",
        'r2_repeat_ok': "✅ Количество повторений установлено: {n}",
        'r2_repeat_err': "❌ Неверное значение. Введите целое число.",
        'r2_grp_empty_db': "❌ База групп пуста.",
        'r2_del_group_prompt': "➖ Введите номер группы для удаления:\n\n{list}",
        'r2_grp_deleted': "🗑 Удалено: {title}",
        'r2_grp_del_no_num': "❌ Нет группы с таким номером.",
        'r2_grp_enter_num': "❌ Введите номер группы.",
        'r2_add_group_prompt': "➕ Добавить группы/чаты\n\nОтправьте ссылки (по одной на строку).\nПубличные: https://t.me/username\nПриватные: https://t.me/+invitehash\n\n⚠️ Для приватных (по заявкам) бот отправит заявку и будет ждать подтверждения.",
        'r2_grp_no_link': "❌ Ссылок не найдено.",
        'r2_grp_processing': "⏳ Обрабатываю {n} ссылок...",
        'r2_grp_added': "✅ Добавлено групп: {added}",
        'r2_grp_add_warn': "\n⚠️ Не удалось вступить / заявка ожидается: {n}",
        'r2_view_group': "📌 Группа №{n}\nНазвание: {title}\nСсылка: {link}\nID: {id}",
    }
}

def T(user_id, key):
    lang = get_user_data(user_id).get('lang', 'uk')
    return TEXTS.get(lang, TEXTS['uk']).get(key, key)

def format_sub_time(user_id, timestamp):
    if timestamp == 'lifetime':
        return "безстроково"
    if timestamp == 0:
        return "-"
    dt = datetime.fromtimestamp(timestamp, tz=KYIV_TZ)
    return dt.strftime("%d.%m.%Y %H:%M") + " (Київ)"

def is_sub_active(timestamp):
    if timestamp == 'lifetime':
        return True
    if timestamp == 0:
        return False
    return time.time() < timestamp

def parse_duration(text):
    text = text.strip().lower()
    match = re.match(r'(\d+)\s*(min|hour|hours|day|days|month|months|year|years|s|m|h|d|y)', text)
    if not match:
        return None
    num = int(match.group(1))
    unit = match.group(2)
    multipliers = {
        's': 1,
        'm': 60, 'min': 60,
        'h': 3600, 'hour': 3600, 'hours': 3600,
        'd': 86400, 'day': 86400, 'days': 86400,
        'month': 2592000, 'months': 2592000,
        'year': 31536000, 'years': 31536000, 'y': 31536000,
    }
    secs = num * multipliers.get(unit, 0)
    return secs if secs > 0 else None

def get_subscription_end_text(sub_type, duration_str):
    if duration_str == 'lifetime':
        return 'lifetime'
    secs = parse_duration(duration_str)
    if secs is None:
        return None
    return time.time() + secs

# ---------- Скидання стану rukla1 ----------
def reset_rukla1_state(chat_id):
    """Безпечно очищає стан rukla1 для користувача, щоб уникнути зависань."""
    if RUKLA1_OK:
        try:
            if hasattr(rukla1, 'cancel'):
                rukla1.cancel(chat_id)
            elif hasattr(rukla1, 'clear_pending'):
                rukla1.clear_pending(chat_id)
        except Exception:
            pass

# ---------- Клавіатури ----------
def get_main_menu(user_id):
    if _ruklaInfo is not None:
        info_btn_text = _ruklaInfo.T(user_id, 'b_info')
    else:
        info_btn_text = "ℹ️ ВАЖЛИВО: прочитати перед купівлею"
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(T(user_id,'b_profile'), callback_data="m_profile"),
        types.InlineKeyboardButton(info_btn_text, callback_data="m_info"),
        types.InlineKeyboardButton(T(user_id,'b_manage_ad'), callback_data="m_manage_ad"),
        types.InlineKeyboardButton(T(user_id,'b_balance'), callback_data="m_balance"),
        types.InlineKeyboardButton(T(user_id,'b_support'), callback_data="m_support"),
        types.InlineKeyboardButton(T(user_id,'b_lang'), callback_data="m_lang"),
        types.InlineKeyboardButton(T(user_id,'b_discount'), callback_data="m_dummy"),
    )
    if user_id == ADMIN_ID:
        markup.add(
            types.InlineKeyboardButton(T(user_id,'adm_info_btn'), callback_data="adm_info"),
            types.InlineKeyboardButton(T(user_id,'b_manage_users'), callback_data="adm_manage_users"),
            types.InlineKeyboardButton(T(user_id,'b_send_msg_to_user'), callback_data="adm_send_msg"),
            types.InlineKeyboardButton(T(user_id,'adm_broadcast_btn'), callback_data="adm_broadcast"),
        )
    return markup

def get_back_btn(user_id, target="m_main"):
    return types.InlineKeyboardButton(T(user_id,'b_back'), callback_data=target)

# ---------- rukla1 інтеграція ----------
if RUKLA1_OK:
    rukla1.register_callbacks(bot)

try:
    import rukla5
    rukla5.register_callbacks(bot)
except Exception as _e:
    print(f"[rukla5 import error]: {_e}")

try:
    import rukla6
    rukla6.register_callbacks(bot)
except Exception as _e:
    print(f"[rukla6 import error]: {_e}")

try:
    import rukla7
    rukla7.register_callbacks(bot)
except Exception as _e:
    print(f"[rukla7 import error]: {_e}")

_ruklaInfo = None
try:
    import ruklaInfo as _ruklaInfo
    _ruklaInfo.register_callbacks(bot)
except Exception as _e:
    print(f"[ruklaInfo import error]: {_e}")

# Нові виділені модулі (підтримка / баланс / адмін).
try:
    import ruklateh
    ruklateh.register(bot)
except Exception as _e:
    print(f"[ruklateh import error]: {_e}")

try:
    import ruklabalnce
    ruklabalnce.register(bot)
except Exception as _e:
    print(f"[ruklabalnce import error]: {_e}")

try:
    import rukladmin
    rukladmin.register(bot)
except Exception as _e:
    print(f"[rukladmin import error]: {_e}")

@bot.message_handler(
    func=lambda msg: RUKLA1_OK
                     and rukla1.has_text_pending(msg.chat.id)
                     and not (rukladmin.is_admin_inputting() and msg.from_user.id == ADMIN_ID)
                     and not ruklateh.is_in_active_chat(msg.chat.id)
                     and not (msg.text and msg.text.startswith('/')),
    content_types=['text']
)
def _rukla1_msg_router(message):
    rukla1.handle_text(bot, message)

@bot.message_handler(
    func=lambda msg: RUKLA1_OK
                     and rukla1.has_file_pending(msg.chat.id)
                     and not (rukladmin.is_admin_inputting() and msg.from_user.id == ADMIN_ID)
                     and not ruklateh.is_in_active_chat(msg.chat.id),
    content_types=['document', 'photo']
)
def _rukla1_media_router(message):
    rukla1.handle_file(bot, message)

# ---------- /start ----------
@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.chat.id
    data = get_user_data(uid)
    reset_rukla1_state(uid)
    if data.get('lang_set'):
        bot.send_message(uid, T(uid, 'greeting'), reply_markup=get_main_menu(uid))
    else:
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
            types.InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"),
            types.InlineKeyboardButton("💩 Русский", callback_data="lang_ru"),
        )
        bot.send_message(uid, TEXT_START, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def set_lang(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    lang = call.data.split('_')[1]
    if lang not in ('uk', 'en', 'ru'):
        return
    data = get_user_data(uid)
    data['lang'] = lang
    data['lang_set'] = True
    save_db()
    try:
        markup  = get_main_menu(uid)
        greeting = T(uid, 'greeting')
        try:
            bot.edit_message_text(greeting, uid, call.message.message_id,
                                  reply_markup=markup)
        except Exception:
            bot.send_message(uid, greeting, reply_markup=markup)
    except Exception as e:
        print(f"[set_lang] uid={uid} lang={lang} err={e}")

@bot.callback_query_handler(func=lambda call: call.data == 'm_lang')
def change_lang_menu(call):
    uid = call.message.chat.id
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
        types.InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"),
        types.InlineKeyboardButton("💩 Русский", callback_data="lang_ru"),
        get_back_btn(uid),
    )
    bot.edit_message_text("Select language / Оберіть мову / Выберите язык:",
                          uid, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'm_main')
def back_to_main(call):
    uid = call.message.chat.id
    reset_rukla1_state(uid)
    bot.edit_message_text(T(uid,'greeting'), uid, call.message.message_id,
                          reply_markup=get_main_menu(uid))

@bot.callback_query_handler(func=lambda call: call.data == 'm_profile')
def show_profile(call):
    uid = call.from_user.id
    data = get_user_data(uid)
    uname = f"@{call.from_user.username}" if call.from_user.username else ""
    sub_url = format_sub_time(uid, data['sub_url_until'])
    sub_groups = format_sub_time(uid, data['sub_groups_until'])
    sub_tiktok = format_sub_time(uid, data.get('sub_tiktok_until', 0))
    text = T(uid,'profile').format(
        name=call.from_user.first_name, uid=uid, uname=uname,
        balance=data['balance'], sub_url=sub_url, sub_groups=sub_groups,
        sub_tiktok=sub_tiktok
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(T(uid,'b_topup'), callback_data="m_balance"),
        get_back_btn(uid),
    )
    bot.edit_message_text(text, uid, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'm_info')
def show_info(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    if _ruklaInfo is not None:
        _ruklaInfo.open_info_menu(bot, uid, call.message.message_id)
    else:
        bot.edit_message_text("❌ Модуль ruklaInfo недоступний.", uid, call.message.message_id)

# ---------- Підтримка ----------

# ---------- Рекламні кнопки ----------
def open_manage_ad_menu(bot_tb, uid: int, message_id: int):
    """Відкриває меню 'Керувати рекламою'. Викликається з rukla1 при натисканні Back."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(T(uid, 'b_shop'),      callback_data="m_shop"),
        types.InlineKeyboardButton(T(uid, 'b_url'),       callback_data="m_manage_url"),
        types.InlineKeyboardButton(T(uid, 'b_grp'),       callback_data="m_manage_grp"),
        types.InlineKeyboardButton(T(uid, 'b_tiktok'),    callback_data="m_manage_tiktok"),
        types.InlineKeyboardButton(T(uid, 'b_back_prev'), callback_data="m_main"),
    )
    try:
        bot_tb.edit_message_text(T(uid, 'manage_ad_greeting'), uid, message_id, reply_markup=markup)
    except Exception:
        bot_tb.send_message(uid, T(uid, 'manage_ad_greeting'), reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == 'm_manage_ad')
def show_manage_ad(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(T(uid, 'b_shop'),   callback_data="m_shop"),
        types.InlineKeyboardButton(T(uid, 'b_url'),    callback_data="m_manage_url"),
        types.InlineKeyboardButton(T(uid, 'b_grp'),    callback_data="m_manage_grp"),
        types.InlineKeyboardButton(T(uid, 'b_tiktok'), callback_data="m_manage_tiktok"),
        types.InlineKeyboardButton(T(uid, 'b_back_prev'), callback_data="m_main"),
    )
    try:
        bot.edit_message_text(T(uid, 'manage_ad_greeting'), uid, call.message.message_id,
                              reply_markup=markup)
    except Exception:
        bot.send_message(uid, T(uid, 'manage_ad_greeting'), reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in ['m_manage_url', 'm_manage_grp', 'm_manage_tiktok'])
def open_management(call):
    uid = call.message.chat.id
    data = get_user_data(uid)
    if call.data == 'm_manage_url':
        if not is_sub_active(data['sub_url_until']):
            bot.answer_callback_query(call.id, T(uid,'locked'), show_alert=True)
            return
        bot.answer_callback_query(call.id)
        if RUKLA1_OK:
            rukla1.manage_url_ads(bot, uid, message_id=call.message.message_id)
        else:
            bot.edit_message_text(T(uid,'rukla1_missing'), uid, call.message.message_id)
    elif call.data == 'm_manage_grp':
        if not is_sub_active(data['sub_groups_until']):
            bot.answer_callback_query(call.id, T(uid,'locked'), show_alert=True)
            return
        bot.answer_callback_query(call.id)
        if RUKLA1_OK:
            rukla1.manage_group_ads(bot, uid, message_id=call.message.message_id)
        else:
            bot.edit_message_text(T(uid,'rukla1_missing'), uid, call.message.message_id)
    else:  # m_manage_tiktok
        if not is_sub_active(data.get('sub_tiktok_until', 0)):
            bot.answer_callback_query(call.id, T(uid,'locked'), show_alert=True)
            return
        bot.answer_callback_query(call.id)
        # Меню керування акаунтами + параметри реклами вже об'єднані у rukla5
        # (один parent-екран). Відкриваємо його напряму.
        try:
            import rukla5
            rukla5.open_main_menu(bot, uid, call.message.message_id)
        except Exception as e:
            bot.edit_message_text(f"❌ Модуль rukla5 недоступний: {e}",
                                  uid, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == 'm_tiktok_accounts')
def tiktok_accounts_menu(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    try:
        import rukla5
        rukla5.open_tiktok_menu(bot, uid, call.message.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Модуль rukla5 недоступний: {e}", uid, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == 'm_tiktok_params')
def tiktok_params_menu(call):
    """Backwards-compat alias — старі повідомлення можуть містити цю кнопку.
    Відкриває об'єднаний parent menu (де параметри + керування акаунтами)."""
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    try:
        import rukla5
        rukla5.open_main_menu(bot, uid, call.message.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Модуль rukla5 недоступний: {e}", uid, call.message.message_id)

# ---------- Магазин додаткових функцій ----------
@bot.callback_query_handler(func=lambda call: call.data == 'm_shop')
def open_shop(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    try:
        import rukla4
        rukla4.open_shop(bot, uid, call.message.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Модуль rukla4 недоступний: {e}", uid, call.message.message_id)

# ---------- Магазин акаунтів ----------
@bot.callback_query_handler(func=lambda call: call.data == 'm_buy_accounts')
def open_buy_accounts(call):
    uid = call.message.chat.id
    data = get_user_data(uid)
    has_sub = (
        is_sub_active(data['sub_url_until'])
        or is_sub_active(data['sub_groups_until'])
        or is_sub_active(data.get('sub_tiktok_until', 0))
    )
    if not has_sub:
        bot.answer_callback_query(call.id, T(uid, 'acc_shop_locked'), show_alert=True)
        return
    bot.answer_callback_query(call.id)
    try:
        import rukla6
        rukla6.open_accounts_shop(bot, uid, call.message.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Модуль rukla6 недоступний: {e}", uid, call.message.message_id)

# ---------- Заглушки ----------
@bot.callback_query_handler(func=lambda call: call.data == 'm_dummy')
def dummy_buttons(call):
    bot.answer_callback_query(call.id, "Ця функція тимчасова не працює.", show_alert=True)

# ================== ОБРОБНИК CALLBACK'ів ВІД rukla1 ==================
if RUKLA1_OK:
    @bot.callback_query_handler(func=lambda call: rukla1.is_rukla1_callback(call.data))
    def rukla1_callback_forward(call):
        try:
            rukla1.handle_callback(bot, call)
        except Exception as e:
            bot.answer_callback_query(call.id, f"Помилка: {e}")

# ---------- Перевірка завершення підписок ----------
def _expired_markup(uid):
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton(T(uid, 'sub_btn_buy'), callback_data='m_balance'),
        types.InlineKeyboardButton(T(uid, 'b_back'), callback_data='m_main'),
    )
    return m

def check_expired_subs():
    while True:
        now = time.time()
        for uid, data in list(users_db.items()):
            if uid == ADMIN_ID:
                continue
            changed = False
            if isinstance(data['sub_url_until'], (int, float)) and data['sub_url_until'] != 0 and now > data['sub_url_until']:
                try:
                    bot.send_message(uid, T(uid, 'sub_expired').format(type="URL рекламу"),
                                     reply_markup=_expired_markup(uid))
                    data['sub_url_until'] = 0
                    changed = True
                except: pass
            if isinstance(data['sub_groups_until'], (int, float)) and data['sub_groups_until'] != 0 and now > data['sub_groups_until']:
                try:
                    bot.send_message(uid, T(uid, 'sub_expired').format(type="рекламу по групах"),
                                     reply_markup=_expired_markup(uid))
                    data['sub_groups_until'] = 0
                    changed = True
                except: pass
            tiktok_until = data.get('sub_tiktok_until', 0)
            if isinstance(tiktok_until, (int, float)) and tiktok_until != 0 and now > tiktok_until:
                try:
                    bot.send_message(uid, T(uid, 'sub_expired').format(type="рекламу у TikTok"),
                                     reply_markup=_expired_markup(uid))
                    data['sub_tiktok_until'] = 0
                    changed = True
                except: pass
            if changed:
                save_db()
        time.sleep(60)

# ---------- Запуск ----------
if __name__ == '__main__':
    load_db()
    get_user_data(ADMIN_ID)

    def graceful_exit(signum, frame):
        print("\n🔴 Завершення роботи...")
        if RUKLA1_OK and rukla1._loop is not None:
            rukla1._loop.call_soon_threadsafe(rukla1._loop.stop)
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    threading.Thread(target=check_expired_subs, daemon=True).start()
    print("✅ Бот запущено!")
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        graceful_exit(None, None)
