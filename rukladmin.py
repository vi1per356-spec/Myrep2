"""
rukladmin.py — модуль адміністратора (виділено з rukla.py).

Усі callback'и: adm_info, adm_add_bal, adm_rem_bal, adm_give_sub,
adm_del_sub, admsub_*, adm_manage_users, adm_send_msg, adm_broadcast,
adm_btn_none / adm_btn_create / adm_btn_pick / adm_btn_use_*.

Тримає власні структури стану: _admin_pending_msg та _custom_buttons
(збережено у custom_buttons.json).
"""

from __future__ import annotations

import json
import os

from telebot import types

import rukla as _r


def _T(uid, key):
    return _r.T(uid, key)


def _back_btn(uid, target='m_main'):
    return _r.get_back_btn(uid, target)


# ── Стан -----------------------------------------------------------------
admin_input_pending: bool = False  # глобальний прапор «адмін зараз вводить дані»
_admin_pending_msg: dict = {}      # ADMIN_ID -> dict стану надсилання
_custom_buttons: list[dict] = []   # список кнопок [{'text', 'url'}, ...]
CUSTOM_BTNS_FILE = 'custom_buttons.json'


def _load_custom_btns() -> None:
    global _custom_buttons
    if os.path.exists(CUSTOM_BTNS_FILE):
        try:
            with open(CUSTOM_BTNS_FILE, 'r', encoding='utf-8') as f:
                _custom_buttons = json.load(f)
        except Exception:
            _custom_buttons = []


def _save_custom_btns() -> None:
    with open(CUSTOM_BTNS_FILE, 'w', encoding='utf-8') as f:
        json.dump(_custom_buttons, f, ensure_ascii=False, indent=2)


def is_admin_inputting() -> bool:
    """rukla.py message router запитує цей прапор, щоб не перехоплювати ввід."""
    return admin_input_pending


# ── Реєстрація хендлерів ------------------------------------------------
def register(bot):
    _load_custom_btns()

    @bot.callback_query_handler(func=lambda call: call.data == 'adm_info')
    def admin_info(call):
        if call.from_user.id != _r.ADMIN_ID:
            return
        lines = []
        for uid, d in _r.users_db.items():
            if (d['balance'] > 0 or d['sub_url_until'] != 0
                    or d['sub_groups_until'] != 0
                    or d.get('sub_tiktok_until', 0) != 0):
                try:
                    user = bot.get_chat(uid)
                    name = user.first_name
                    uname = f"@{user.username}" if user.username else ""
                except Exception:
                    name = str(uid)
                    uname = ""
                lines.append(
                    f"{name} ({uid}) {uname}\n"
                    f"┏ Баланс: {d['balance']}$\n"
                    f"┣ URL до: {_r.format_sub_time(uid, d['sub_url_until'])}\n"
                    f"┣ Групи до: {_r.format_sub_time(uid, d['sub_groups_until'])}\n"
                    f"┗ TikTok до: {_r.format_sub_time(uid, d.get('sub_tiktok_until', 0))}"
                )
        if not lines:
            lines = ["Немає активних користувачів."]
        markup = types.InlineKeyboardMarkup()
        markup.add(_back_btn(_r.ADMIN_ID))
        bot.edit_message_text("\n\n".join(lines)[:4000], _r.ADMIN_ID,
                              call.message.message_id, reply_markup=markup)

    # ── Додати баланс ----------------------------------------------------
    @bot.callback_query_handler(func=lambda call: call.data == 'adm_add_bal')
    def admin_add_bal(call):
        global admin_input_pending
        if call.from_user.id != _r.ADMIN_ID:
            return
        admin_input_pending = True
        msg = bot.send_message(_r.ADMIN_ID,
            "Введіть айді користувача якому потрібно поповнити баланс:")
        bot.register_next_step_handler(msg, _adm_add_bal_uid)

    def _adm_add_bal_uid(message):
        global admin_input_pending
        if message.from_user.id != _r.ADMIN_ID:
            admin_input_pending = False
            return
        try:
            u_id = int(message.text.strip())
        except ValueError:
            admin_input_pending = False
            bot.send_message(_r.ADMIN_ID, "❌ Невірний ID. Введіть число.")
            return
        _r.get_user_data(_r.ADMIN_ID)['admin_temp_bal_uid'] = u_id
        msg = bot.send_message(_r.ADMIN_ID,
            f"Введіть суму для поповнення балансу користувача {u_id}:")
        bot.register_next_step_handler(msg, _adm_add_bal_fin)

    def _adm_add_bal_fin(message):
        global admin_input_pending
        admin_input_pending = False
        if message.from_user.id != _r.ADMIN_ID:
            return
        try:
            amount = int(message.text.strip())
            u_id = _r.get_user_data(_r.ADMIN_ID).get('admin_temp_bal_uid')
            if not u_id:
                bot.send_message(_r.ADMIN_ID, "❌ Помилка: не знайдено ID користувача.")
                return
            _r.get_user_data(u_id)['balance'] += amount
            _r.save_db()
            bot.send_message(_r.ADMIN_ID,
                _T(_r.ADMIN_ID, 'adm_bal_added').format(uid=u_id, amount=amount))
            try:
                bot.send_message(u_id,
                    _T(u_id, 'adm_user_bal_added').format(amount=amount))
            except Exception:
                pass
        except Exception as e:
            bot.send_message(_r.ADMIN_ID, f"❌ Помилка введення: {e}")

    # ── Зняти баланс -----------------------------------------------------
    @bot.callback_query_handler(func=lambda call: call.data == 'adm_rem_bal')
    def admin_rem_bal(call):
        global admin_input_pending
        if call.from_user.id != _r.ADMIN_ID:
            return
        admin_input_pending = True
        msg = bot.send_message(_r.ADMIN_ID,
            "Введіть айді користувача у якого потрібно зняти баланс:")
        bot.register_next_step_handler(msg, _adm_rem_bal_uid)

    def _adm_rem_bal_uid(message):
        global admin_input_pending
        if message.from_user.id != _r.ADMIN_ID:
            admin_input_pending = False
            return
        try:
            u_id = int(message.text.strip())
        except ValueError:
            admin_input_pending = False
            bot.send_message(_r.ADMIN_ID, "❌ Невірний ID. Введіть число.")
            return
        _r.get_user_data(_r.ADMIN_ID)['admin_temp_rem_uid'] = u_id
        msg = bot.send_message(_r.ADMIN_ID,
            f"Введіть суму для зняття з балансу користувача {u_id}:")
        bot.register_next_step_handler(msg, _adm_rem_bal_fin)

    def _adm_rem_bal_fin(message):
        global admin_input_pending
        admin_input_pending = False
        if message.from_user.id != _r.ADMIN_ID:
            return
        try:
            amount = int(message.text.strip())
            u_id = _r.get_user_data(_r.ADMIN_ID).get('admin_temp_rem_uid')
            if not u_id:
                bot.send_message(_r.ADMIN_ID, "❌ Помилка: не знайдено ID користувача.")
                return
            _r.get_user_data(u_id)['balance'] -= amount
            _r.save_db()
            bot.send_message(_r.ADMIN_ID,
                _T(_r.ADMIN_ID, 'adm_bal_removed').format(uid=u_id, amount=amount))
        except Exception as e:
            bot.send_message(_r.ADMIN_ID, f"❌ Помилка введення: {e}")

    # ── Видати підписку --------------------------------------------------
    @bot.callback_query_handler(func=lambda call: call.data == 'adm_give_sub')
    def admin_give_sub(call):
        global admin_input_pending
        if call.from_user.id != _r.ADMIN_ID:
            return
        admin_input_pending = True
        msg = bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'adm_enter_id_sub'))
        bot.register_next_step_handler(msg, _adm_give_sub_type)

    def _adm_give_sub_type(message):
        global admin_input_pending
        if message.from_user.id != _r.ADMIN_ID:
            admin_input_pending = False
            return
        uid = message.text.strip()
        admin_input_pending = False
        data = _r.get_user_data(_r.ADMIN_ID)
        data['admin_temp_uid'] = uid
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(_T(_r.ADMIN_ID, 'adm_sub_url'),    callback_data="admsub_url"),
            types.InlineKeyboardButton(_T(_r.ADMIN_ID, 'adm_sub_grp'),    callback_data="admsub_grp"),
            types.InlineKeyboardButton(_T(_r.ADMIN_ID, 'adm_sub_tiktok'), callback_data="admsub_tiktok"),
            types.InlineKeyboardButton(_T(_r.ADMIN_ID, 'adm_sub_mix'),    callback_data="admsub_mix"),
            types.InlineKeyboardButton(_T(_r.ADMIN_ID, 'adm_sub_all'),    callback_data="admsub_all"),
        )
        bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'adm_sub_type'), reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('admsub_'))
    def admin_give_sub_time(call):
        global admin_input_pending
        if call.from_user.id != _r.ADMIN_ID:
            return
        sub_type = call.data.split('_')[1]
        data = _r.get_user_data(_r.ADMIN_ID)
        data['admin_temp_sub_type'] = sub_type
        admin_input_pending = True
        msg = bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'adm_enter_term'))
        bot.register_next_step_handler(msg, _adm_give_sub_fin)

    def _adm_give_sub_fin(message):
        global admin_input_pending
        admin_input_pending = False
        if message.from_user.id != _r.ADMIN_ID:
            return
        term = message.text.strip()
        admin_data = _r.get_user_data(_r.ADMIN_ID)
        uid = int(admin_data.get('admin_temp_uid', 0))
        sub_type = admin_data.get('admin_temp_sub_type')
        if not uid or not sub_type:
            return
        end = _r.get_subscription_end_text(sub_type, term)
        if end is None:
            bot.send_message(_r.ADMIN_ID, "Невірний формат терміну.")
            return
        data = _r.get_user_data(uid)
        if sub_type in ('url', 'mix', 'all'):
            data['sub_url_until'] = end
        if sub_type in ('grp', 'mix', 'all'):
            data['sub_groups_until'] = end
        if sub_type in ('tiktok', 'all'):
            data['sub_tiktok_until'] = end
        _r.save_db()
        bot.send_message(_r.ADMIN_ID,
            _T(_r.ADMIN_ID, 'adm_sub_given').format(uid=uid))
        try:
            bot.send_message(uid, _T(uid, 'adm_sub_notify'))
        except Exception:
            pass

    # ── Видалити підписку ------------------------------------------------
    @bot.callback_query_handler(func=lambda call: call.data == 'adm_del_sub')
    def admin_del_sub(call):
        global admin_input_pending
        if call.from_user.id != _r.ADMIN_ID:
            return
        admin_input_pending = True
        msg = bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'adm_del_sub_confirm'))
        bot.register_next_step_handler(msg, _adm_del_sub_fin)

    def _adm_del_sub_fin(message):
        global admin_input_pending
        admin_input_pending = False
        try:
            u_id = int(message.text.strip())
            d = _r.get_user_data(u_id)
            d['sub_url_until'] = 0
            d['sub_groups_until'] = 0
            d['sub_tiktok_until'] = 0
            _r.save_db()
            bot.send_message(_r.ADMIN_ID,
                _T(_r.ADMIN_ID, 'adm_del_sub_done').format(uid=u_id))
        except Exception:
            bot.send_message(_r.ADMIN_ID, "❌ Помилка введення.")

    # ── Підменю «Керувати користувачами» ---------------------------------
    @bot.callback_query_handler(func=lambda call: call.data == 'adm_manage_users')
    def admin_manage_users(call):
        if call.from_user.id != _r.ADMIN_ID:
            bot.answer_callback_query(call.id)
            return
        bot.answer_callback_query(call.id)
        uid = call.message.chat.id
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(_T(uid, 'adm_give_sub_btn'), callback_data="adm_give_sub"),
            types.InlineKeyboardButton(_T(uid, 'adm_del_sub_btn'),  callback_data="adm_del_sub"),
            types.InlineKeyboardButton(_T(uid, 'adm_add_bal_btn'),  callback_data="adm_add_bal"),
            types.InlineKeyboardButton(_T(uid, 'adm_rem_bal_btn'),  callback_data="adm_rem_bal"),
            types.InlineKeyboardButton(_T(uid, 'b_back_prev'),      callback_data="m_main"),
        )
        try:
            bot.edit_message_text(_T(uid, 'b_manage_users'), uid,
                                  call.message.message_id, reply_markup=markup)
        except Exception:
            bot.send_message(uid, _T(uid, 'b_manage_users'), reply_markup=markup)

    # ── Надіслати повідомлення користувачу -------------------------------
    @bot.callback_query_handler(func=lambda call: call.data == 'adm_send_msg')
    def admin_send_msg(call):
        if call.from_user.id != _r.ADMIN_ID:
            bot.answer_callback_query(call.id)
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'send_msg_ask_uid'))
        bot.register_next_step_handler(msg, _adm_send_msg_uid)

    def _adm_send_msg_uid(message):
        if message.from_user.id != _r.ADMIN_ID:
            return
        try:
            target_uid = int(message.text.strip())
        except Exception:
            bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'send_msg_user_not_found'))
            return
        if target_uid not in _r.users_db:
            bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'send_msg_user_not_found'))
            return
        msg = bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'send_msg_ask_text'))
        bot.register_next_step_handler(msg, lambda m: _adm_send_msg_text(m, target_uid))

    def _adm_send_msg_text(message, target_uid):
        if message.from_user.id != _r.ADMIN_ID:
            return
        _admin_pending_msg[_r.ADMIN_ID] = {
            'mode': 'send_to_user',
            'target_uid': target_uid,
            'content_type': message.content_type,
            'text': message.text if message.content_type == 'text' else None,
            'photo_id': message.photo[-1].file_id if message.content_type == 'photo' else None,
            'doc_id': message.document.file_id if message.content_type == 'document' else None,
            'caption': (message.caption or '') if message.content_type in ('photo', 'document') else None,
        }
        _ask_admin_button(_r.ADMIN_ID)

    # ── Розсилка ---------------------------------------------------------
    @bot.callback_query_handler(func=lambda call: call.data == 'adm_broadcast')
    def admin_broadcast(call):
        if call.from_user.id != _r.ADMIN_ID:
            return
        msg = bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'adm_broadcast_prompt'))
        bot.register_next_step_handler(msg, _adm_broadcast_fin)

    def _adm_broadcast_fin(message):
        if message.from_user.id != _r.ADMIN_ID:
            return
        _admin_pending_msg[_r.ADMIN_ID] = {
            'mode': 'broadcast',
            'target_uid': None,
            'content_type': message.content_type,
            'text': message.text if message.content_type == 'text' else None,
            'photo_id': message.photo[-1].file_id if message.content_type == 'photo' else None,
            'doc_id': message.document.file_id if message.content_type == 'document' else None,
            'caption': (message.caption or '') if message.content_type in ('photo', 'document') else None,
        }
        _ask_admin_button(_r.ADMIN_ID)

    # ── Помічники прикріплення кнопки ----------------------------------
    def _ask_admin_button(uid: int):
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(_T(uid, 'btn_attach_create_new'),
                                       callback_data='adm_btn_create'),
            types.InlineKeyboardButton(_T(uid, 'btn_attach_pick_existing'),
                                       callback_data='adm_btn_pick'),
            types.InlineKeyboardButton(_T(uid, 'btn_attach_none'),
                                       callback_data='adm_btn_none'),
        )
        bot.send_message(uid, _T(uid, 'btn_attach_ask'), reply_markup=markup)

    def _do_send_admin_msg(markup):
        """Викликається після вибору кнопки/none — фактично надсилає
        збережене повідомлення (одному користувачу або у broadcast)."""
        state = _admin_pending_msg.pop(_r.ADMIN_ID, None)
        if not state:
            return
        ct      = state['content_type']
        caption = state.get('caption', '') or ''

        def _send_one(uid):
            try:
                if ct == 'photo':
                    bot.send_photo(uid, state['photo_id'], caption=caption, reply_markup=markup)
                elif ct == 'document':
                    bot.send_document(uid, state['doc_id'], caption=caption, reply_markup=markup)
                else:
                    bot.send_message(uid, state['text'] or '', reply_markup=markup)
                return True
            except Exception:
                return False

        if state['mode'] == 'send_to_user':
            target = state['target_uid']
            if _send_one(target):
                bot.send_message(_r.ADMIN_ID,
                    _T(_r.ADMIN_ID, 'send_msg_sent').format(uid=target))
            else:
                bot.send_message(_r.ADMIN_ID,
                    _T(_r.ADMIN_ID, 'send_msg_failed').format(err='send failed'))
        else:  # broadcast
            sent = errors = 0
            for uid in list(_r.users_db.keys()):
                if _send_one(uid):
                    sent += 1
                else:
                    errors += 1
            bot.send_message(_r.ADMIN_ID,
                _T(_r.ADMIN_ID, 'adm_broadcast_result').format(sent=sent, errors=errors))

    @bot.callback_query_handler(func=lambda call: call.data == 'adm_btn_none')
    def admin_btn_none(call):
        if call.from_user.id != _r.ADMIN_ID:
            bot.answer_callback_query(call.id)
            return
        bot.answer_callback_query(call.id)
        _do_send_admin_msg(markup=None)

    @bot.callback_query_handler(func=lambda call: call.data == 'adm_btn_create')
    def admin_btn_create(call):
        global admin_input_pending
        if call.from_user.id != _r.ADMIN_ID:
            bot.answer_callback_query(call.id)
            return
        bot.answer_callback_query(call.id)
        admin_input_pending = True
        msg = bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'btn_create_ask_text'))
        bot.register_next_step_handler(msg, _admin_btn_got_text)

    def _admin_btn_got_text(message):
        global admin_input_pending
        if message.from_user.id != _r.ADMIN_ID:
            admin_input_pending = False
            return
        state = _admin_pending_msg.get(_r.ADMIN_ID)
        if not state:
            admin_input_pending = False
            return
        state['_btn_text'] = (message.text or '').strip()
        msg = bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'btn_create_ask_url'))
        bot.register_next_step_handler(msg, _admin_btn_got_url)

    def _admin_btn_got_url(message):
        global admin_input_pending
        admin_input_pending = False
        if message.from_user.id != _r.ADMIN_ID:
            return
        state = _admin_pending_msg.get(_r.ADMIN_ID)
        if not state:
            return
        url      = (message.text or '').strip()
        btn_text = state.pop('_btn_text', 'Link')
        _load_custom_btns()
        _custom_buttons.append({'text': btn_text, 'url': url})
        _save_custom_btns()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(btn_text, url=url))
        _do_send_admin_msg(markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == 'adm_btn_pick')
    def admin_btn_pick(call):
        if call.from_user.id != _r.ADMIN_ID:
            bot.answer_callback_query(call.id)
            return
        bot.answer_callback_query(call.id)
        _load_custom_btns()
        if not _custom_buttons:
            _do_send_admin_msg(markup=None)
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for i, btn in enumerate(_custom_buttons):
            short_url = btn['url'][:40] + '…' if len(btn['url']) > 40 else btn['url']
            markup.add(types.InlineKeyboardButton(
                f"{btn['text']}  ·  {short_url}",
                callback_data=f"adm_btn_use_{i}",
            ))
        markup.add(types.InlineKeyboardButton(
            _T(_r.ADMIN_ID, 'btn_attach_none'), callback_data='adm_btn_none'))
        bot.send_message(_r.ADMIN_ID, "Виберіть кнопку:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('adm_btn_use_'))
    def admin_btn_use(call):
        if call.from_user.id != _r.ADMIN_ID:
            bot.answer_callback_query(call.id)
            return
        bot.answer_callback_query(call.id)
        try:
            idx = int(call.data.replace('adm_btn_use_', ''))
        except ValueError:
            _do_send_admin_msg(markup=None)
            return
        _load_custom_btns()
        if idx >= len(_custom_buttons):
            _do_send_admin_msg(markup=None)
            return
        btn = _custom_buttons[idx]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(btn['text'], url=btn['url']))
        _do_send_admin_msg(markup=markup)
