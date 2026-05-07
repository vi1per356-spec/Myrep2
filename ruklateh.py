"""
ruklateh.py — модуль технічної підтримки (виділено з rukla.py).

Зберігає глобальний стан тікетів та реєструє хендлери підтримки.
Мова перекладу береться з rukla._LX через rukla.T().
"""

from __future__ import annotations

from telebot import types

import rukla as _r

# ── Стан тікетів (раніше — глобали в rukla.py) ────────────────────────────
admin_current_ticket = None      # int | None — uid користувача в активному діалозі
pending_tickets: list[int] = []  # uid у черзі очікування


def _T(uid, key):  # коротка обгортка
    return _r.T(uid, key)


def _back_btn(uid, target='m_main'):
    return _r.get_back_btn(uid, target)


# ── Публічні хелпери (rukla.py звертатиметься сюди) ───────────────────────
def is_in_active_chat(uid: int) -> bool:
    """Чи в активному support-діалозі цей користувач."""
    data = _r.get_user_data(uid)
    return data.get('support_state') in ('active', 'composing')


def reset_state(uid: int) -> None:
    """Скинути support-стан користувача (викликається з /start, тощо)."""
    data = _r.get_user_data(uid)
    data['support_state'] = None


def check_pending_tickets(bot):
    """Викликати наступний тікет з черги, якщо адмін вільний."""
    global admin_current_ticket, pending_tickets
    if admin_current_ticket is None and pending_tickets:
        uid = pending_tickets.pop(0)
        data = _r.get_user_data(uid)
        if data.get('support_state') == 'waiting_in_queue':
            user = bot.get_chat(uid)
            uname = f"@{user.username}" if user.username else ""
            ticket_text = data.get('pending_ticket_text', 'Нове звернення')
            msg_text = _T(_r.ADMIN_ID, 'support_ticket_new').format(
                text=ticket_text, name=user.first_name, uid=uid, uname=uname
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(_T(_r.ADMIN_ID, 'support_btn_accept'),
                                           callback_data=f"sup_accept_{uid}"),
                types.InlineKeyboardButton(_T(_r.ADMIN_ID, 'support_btn_reject'),
                                           callback_data=f"sup_reject_{uid}"),
            )
            file_id = data.get('pending_ticket_file_id')
            msg_type = data.get('pending_ticket_type')
            if msg_type == 'photo' and file_id:
                msg = bot.send_photo(_r.ADMIN_ID, file_id, caption=msg_text, reply_markup=markup)
            elif msg_type == 'document' and file_id:
                msg = bot.send_document(_r.ADMIN_ID, file_id, caption=msg_text, reply_markup=markup)
            else:
                msg = bot.send_message(_r.ADMIN_ID, msg_text, reply_markup=markup)
            data['support_admin_msg_id'] = msg.message_id
            data['support_state'] = 'waiting'
            for key in ('pending_ticket_text', 'pending_ticket_type', 'pending_ticket_file_id'):
                data.pop(key, None)


def is_admin_busy() -> bool:
    return admin_current_ticket is not None


def current_ticket_uid():
    return admin_current_ticket


# ── Реєстрація хендлерів ──────────────────────────────────────────────────
def register(bot):
    @bot.callback_query_handler(func=lambda call: call.data == 'm_support')
    def support_menu(call):
        uid = call.message.chat.id
        data = _r.get_user_data(uid)
        if data.get('support_state') == 'active':
            bot.answer_callback_query(call.id,
                "Ви вже в діалозі. Використовуйте /close для завершення.")
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(_T(uid, 'support_btn_start'), callback_data="sup_start"),
            _back_btn(uid),
        )
        bot.edit_message_text(_T(uid, 'support_intro'), uid, call.message.message_id,
                              reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == 'sup_start')
    def support_start(call):
        uid = call.message.chat.id
        data = _r.get_user_data(uid)
        data['support_state'] = 'composing'
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(_back_btn(uid, 'm_main'))
        bot.edit_message_text(_T(uid, 'support_start_chat'), uid, call.message.message_id,
                              reply_markup=markup)

    @bot.message_handler(
        func=lambda msg: _r.get_user_data(msg.chat.id).get('support_state') == 'composing',
        content_types=['text', 'photo', 'document'],
    )
    def support_ticket_compose(message):
        global admin_current_ticket, pending_tickets
        uid = message.chat.id
        data = _r.get_user_data(uid)
        user = message.from_user
        uname = f"@{user.username}" if user.username else ""

        if message.text:
            ticket_text = message.text
        elif message.photo:
            ticket_text = "[Фото] " + (message.caption or "")
        elif message.document:
            ticket_text = "[Документ] " + (message.caption or "")
        else:
            ticket_text = "[Невідомий тип]"

        data['pending_ticket_text'] = ticket_text
        data['pending_ticket_type'] = message.content_type
        if message.photo:
            data['pending_ticket_file_id'] = message.photo[-1].file_id
        elif message.document:
            data['pending_ticket_file_id'] = message.document.file_id

        if admin_current_ticket is None:
            msg_text = _T(_r.ADMIN_ID, 'support_ticket_new').format(
                text=ticket_text, name=user.first_name, uid=uid, uname=uname
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(_T(_r.ADMIN_ID, 'support_btn_accept'),
                                           callback_data=f"sup_accept_{uid}"),
                types.InlineKeyboardButton(_T(_r.ADMIN_ID, 'support_btn_reject'),
                                           callback_data=f"sup_reject_{uid}"),
            )
            if message.photo:
                msg = bot.send_photo(_r.ADMIN_ID, message.photo[-1].file_id,
                                     caption=msg_text, reply_markup=markup)
            elif message.document:
                msg = bot.send_document(_r.ADMIN_ID, message.document.file_id,
                                        caption=msg_text, reply_markup=markup)
            else:
                msg = bot.send_message(_r.ADMIN_ID, msg_text, reply_markup=markup)
            data['support_admin_msg_id'] = msg.message_id
            data['support_state'] = 'waiting'
            bot.send_message(uid, _T(uid, 'support_msg_sent'))
        else:
            pending_tickets.append(uid)
            data['support_state'] = 'waiting_in_queue'
            bot.send_message(uid,
                "Наразі оператор зайнятий, ваша заявка буде розглянута найближчим часом.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('sup_accept_'))
    def support_admin_accept(call):
        global admin_current_ticket
        if call.from_user.id != _r.ADMIN_ID:
            return
        uid = int(call.data.split('_')[2])
        data = _r.get_user_data(uid)
        if data.get('support_state') not in ('waiting', 'waiting_in_queue'):
            bot.answer_callback_query(call.id, "Заявка вже не актуальна.")
            return
        if admin_current_ticket is not None:
            bot.answer_callback_query(call.id,
                "Ви вже в діалозі. Завершіть поточний /close.")
            return
        admin_current_ticket = uid
        data['support_state'] = 'active'
        data['support_chat_id'] = _r.ADMIN_ID
        bot.send_message(uid, _T(uid, 'support_accepted'))
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                      reply_markup=None)
        bot.send_message(_r.ADMIN_ID,
            f"Розпочато діалог з {uid}. Використовуйте /close для завершення.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('sup_reject_'))
    def support_admin_reject(call):
        if call.from_user.id != _r.ADMIN_ID:
            return
        uid = int(call.data.split('_')[2])
        data = _r.get_user_data(uid)
        data['support_state'] = None
        bot.send_message(uid, _T(uid, 'support_rejected'),
                         reply_markup=types.InlineKeyboardMarkup().add(
                             types.InlineKeyboardButton(_T(uid, 'support_btn_again'),
                                                        callback_data='sup_start'),
                             _back_btn(uid),
                         ))
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                      reply_markup=None)
        check_pending_tickets(bot)

    @bot.message_handler(
        func=lambda msg: _r.get_user_data(msg.chat.id).get('support_state') == 'active'
                         and msg.text != '/close',
        content_types=['text', 'photo', 'document'],
    )
    def support_chat_user(msg):
        uid = msg.chat.id
        if msg.photo:
            bot.send_photo(_r.ADMIN_ID, msg.photo[-1].file_id,
                           caption=f"Від користувача {uid}")
        elif msg.document:
            bot.send_document(_r.ADMIN_ID, msg.document.file_id,
                              caption=f"Від користувача {uid}")
        else:
            bot.send_message(_r.ADMIN_ID, f"Користувач {uid}:\n{msg.text}")

    @bot.message_handler(
        func=lambda msg: msg.from_user.id == _r.ADMIN_ID
                         and admin_current_ticket is not None
                         and msg.text != '/close',
        content_types=['text', 'photo', 'document'],
    )
    def support_chat_admin(msg):
        uid = admin_current_ticket
        if uid is None:
            return
        if msg.photo:
            caption = msg.caption or None
            bot.send_photo(uid, msg.photo[-1].file_id, caption=caption)
        elif msg.document:
            caption = msg.caption or None
            bot.send_document(uid, msg.document.file_id, caption=caption)
        else:
            bot.send_message(uid, msg.text)

    @bot.message_handler(commands=['close'])
    def close_ticket(msg):
        global admin_current_ticket
        uid = msg.chat.id
        # Спочатку віддаємо у rukla7 (контактний реле замовлення), якщо там
        try:
            import rukla7 as _r7
            if uid in _r7._admin_contact or uid in _r7._user_contact:
                _r7._do_close_contact(bot, uid)
                return
        except Exception:
            pass

        if uid == _r.ADMIN_ID:
            if admin_current_ticket is not None:
                user_id = admin_current_ticket
                data = _r.get_user_data(user_id)
                data['support_state'] = None
                _r.reset_rukla1_state(user_id)
                bot.send_message(user_id, _T(user_id, 'support_closed'),
                                 reply_markup=_r.get_main_menu(user_id))
                bot.send_message(_r.ADMIN_ID, "Діалог завершено.",
                                 reply_markup=_r.get_main_menu(_r.ADMIN_ID))
                admin_current_ticket = None
                check_pending_tickets(bot)
            else:
                bot.send_message(_r.ADMIN_ID, "Немає активного діалогу.")
        else:
            data = _r.get_user_data(uid)
            if data.get('support_state') == 'active':
                data['support_state'] = None
                _r.reset_rukla1_state(uid)
                bot.send_message(_r.ADMIN_ID, f"Користувач {uid} завершив діалог.")
                bot.send_message(uid, _T(uid, 'support_closed'),
                                 reply_markup=_r.get_main_menu(uid))
                if admin_current_ticket == uid:
                    admin_current_ticket = None
                    check_pending_tickets(bot)
            else:
                bot.send_message(uid, "Немає активного діалогу.")
