"""
ruklabalnce.py — модуль балансу та купівлі (виділено з rukla.py).

Усі callback'и: m_balance, balbuy_*, buy_*, buy_custom, sub_pay_bal, pay_*,
paid_*, adm_confirm_pay_*, adm_reject_pay_*. Шаблони повідомлень беруться
з rukla.TEXTS через rukla.T().
"""

from __future__ import annotations

import time

from telebot import types

import rukla as _r


def _T(uid, key):
    return _r.T(uid, key)


def _back_btn(uid, target='m_main'):
    return _r.get_back_btn(uid, target)


# ── Показ балансу + список тарифів ───────────────────────────────────────
def show_balance_view(bot, call):
    uid = call.message.chat.id
    data = _r.get_user_data(uid)
    balance = data['balance']
    text = _T(uid, 'balance').format(balance=balance)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(_T(uid, 'buy_url_m'),    callback_data="buy_url_m_99"),
        types.InlineKeyboardButton(_T(uid, 'buy_grp_m'),    callback_data="buy_grp_m_99"),
        types.InlineKeyboardButton(_T(uid, 'buy_url_y'),    callback_data="buy_url_y_1099"),
        types.InlineKeyboardButton(_T(uid, 'buy_grp_y'),    callback_data="buy_grp_y_1099"),
        types.InlineKeyboardButton(_T(uid, 'buy_mix_m'),    callback_data="buy_mix_m_149"),
        types.InlineKeyboardButton(_T(uid, 'buy_mix_y'),    callback_data="buy_mix_y_1399"),
        types.InlineKeyboardButton(_T(uid, 'buy_tiktok_m'), callback_data="buy_tiktok_m_79"),
        types.InlineKeyboardButton(_T(uid, 'buy_tiktok_y'), callback_data="buy_tiktok_y_869"),
        types.InlineKeyboardButton(_T(uid, 'buy_all'),      callback_data="buy_all_m_1999"),
        types.InlineKeyboardButton(_T(uid, 'buy_custom'),   callback_data="buy_custom"),
        _back_btn(uid),
    )
    bot.edit_message_text(text, uid, call.message.message_id, reply_markup=markup)


def _product_info(cb_data: str):
    parts = cb_data.split('_')
    ptype = parts[1]
    period = parts[2]
    amount = int(parts[3])
    secs = (30 if period == 'm' else 365) * 86400
    return ptype, secs, amount


def _payment_markup(uid, amount):
    data = _r.get_user_data(uid)
    pp = data.get('pending_payment', {})
    is_topup = pp.get('is_balance_topup', False)
    markup = types.InlineKeyboardMarkup(row_width=1)
    if not is_topup:
        markup.add(types.InlineKeyboardButton(_T(uid, 'pay_from_balance'),
                                              callback_data="sub_pay_bal"))
    markup.add(
        types.InlineKeyboardButton("Monobank - переказ на картку",
                                   callback_data=f"pay_mono_{amount}"),
        types.InlineKeyboardButton("USDT (TRON - TRC-20)",
                                   callback_data=f"pay_trc20_{amount}"),
        types.InlineKeyboardButton("USDT (TON)",
                                   callback_data=f"pay_ton_{amount}"),
        types.InlineKeyboardButton("USDT (Ethereum - ERC-20)",
                                   callback_data=f"pay_erc20_{amount}"),
        types.InlineKeyboardButton("Bitcoin (BTC)",
                                   callback_data=f"pay_btc_{amount}"),
        types.InlineKeyboardButton("Ethereum",
                                   callback_data=f"pay_eth_{amount}"),
        _back_btn(uid, "m_balance"),
    )
    return markup


def register(bot):
    @bot.callback_query_handler(func=lambda call: call.data == 'm_balance')
    def show_balance(call):
        show_balance_view(bot, call)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('balbuy_'))
    def buy_with_balance(call):
        uid = call.message.chat.id
        data = _r.get_user_data(uid)
        # balbuy_{type}_{period}_{days}_{price}
        parts = call.data.split('_')
        ptype = parts[1]
        days = int(parts[3])
        price = int(parts[4])
        balance = data['balance']
        if balance < price:
            bot.answer_callback_query(
                call.id,
                f"❌ Недостатньо коштів. Баланс: {balance}$, потрібно: {price}$.",
                show_alert=True,
            )
            return
        secs = days * 86400
        now = time.time()
        if ptype in ('url', 'mix'):
            cur = data['sub_url_until']
            base = cur if (isinstance(cur, (int, float)) and cur > now) else now
            data['sub_url_until'] = base + secs
        if ptype in ('grp', 'mix'):
            cur = data['sub_groups_until']
            base = cur if (isinstance(cur, (int, float)) and cur > now) else now
            data['sub_groups_until'] = base + secs
        if ptype == 'tiktok':
            cur = data.get('sub_tiktok_until', 0)
            base = cur if (isinstance(cur, (int, float)) and cur > now) else now
            data['sub_tiktok_until'] = base + secs
        data['balance'] -= price
        _r.save_db()
        bot.answer_callback_query(call.id,
            f"✅ Підписку придбано за {price}$ з балансу!", show_alert=True)
        # Refresh balance page
        call.data = 'm_balance'
        show_balance_view(bot, call)

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith('buy_') and call.data != 'buy_custom'
    )
    def buy_subscription(call):
        uid = call.message.chat.id
        ptype, secs, amount = _product_info(call.data)
        data = _r.get_user_data(uid)
        data['pending_payment'] = {
            'type': ptype,
            'duration': secs,
            'amount': amount,
            'is_balance_topup': False,
        }
        text = _T(uid, 'payment_prompt').format(amount=amount)
        markup = _payment_markup(uid, amount)
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == 'buy_custom')
    def custom_amount_start(call):
        uid = call.message.chat.id
        msg = bot.send_message(uid, _T(uid, 'custom_amount_prompt'))
        bot.register_next_step_handler(msg, _custom_amount_process)

    def _custom_amount_process(message):
        uid = message.chat.id
        try:
            amount = int(message.text.replace('$', '').strip())
            if amount < 10:
                bot.send_message(uid, _T(uid, 'min_amount_error'))
                return
            data = _r.get_user_data(uid)
            data['pending_payment'] = {
                'type': 'balance',
                'amount': amount,
                'is_balance_topup': True,
            }
            bot.send_message(uid, _T(uid, 'payment_prompt').format(amount=amount),
                             reply_markup=_payment_markup(uid, amount))
        except ValueError:
            bot.send_message(uid, _T(uid, 'invalid_amount_error'))

    @bot.callback_query_handler(func=lambda call: call.data == 'sub_pay_bal')
    def pay_balance_sub(call):
        uid = call.message.chat.id
        data = _r.get_user_data(uid)
        pp = data.get('pending_payment')
        if not pp or pp.get('is_balance_topup'):
            bot.answer_callback_query(call.id, "❌ Помилка.", show_alert=True)
            return
        amount = pp['amount']
        balance = data['balance']
        if balance < amount:
            bot.answer_callback_query(
                call.id,
                _T(uid, 'not_enough_balance').format(balance=balance, price=amount),
                show_alert=True,
            )
            return
        now = time.time()
        secs = pp['duration']
        ptype = pp['type']
        if ptype in ('url', 'mix', 'all'):
            cur = data['sub_url_until']
            base = cur if (isinstance(cur, (int, float)) and cur > now) else now
            data['sub_url_until'] = base + secs
        if ptype in ('grp', 'mix', 'all'):
            cur = data['sub_groups_until']
            base = cur if (isinstance(cur, (int, float)) and cur > now) else now
            data['sub_groups_until'] = base + secs
        if ptype in ('tiktok', 'all'):
            cur = data.get('sub_tiktok_until', 0)
            base = cur if (isinstance(cur, (int, float)) and cur > now) else now
            data['sub_tiktok_until'] = base + secs
        data['balance'] -= amount
        data.pop('pending_payment', None)
        _r.save_db()
        bot.answer_callback_query(call.id,
            _T(uid, 'bought_with_balance').format(price=amount), show_alert=True)
        try:
            call.data = 'm_balance'
            show_balance_view(bot, call)
        except Exception:
            pass

    @bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
    def payment_address(call):
        uid = call.message.chat.id
        parts = call.data.split('_')
        method = parts[1]
        amount = parts[2]
        wallets = {
            'mono':  ('Monobank',     '`4874 1000 2703 7129`'),
            'trc20': ('USDT TRC-20',  '`TQA13mo3bK1r29LNPYZ5wGwHB8vv22tFix`'),
            'ton':   ('USDT TON',     '`UQA8WHq2-asw9S-v11HheGVjXYRXMN1osupOPDnb9u1OlrZQ`'),
            'erc20': ('USDT ERC-20',  '`0x32bc85F9F8A4F00D5983b8Bdbd3E8a83685c3CCE`'),
            'btc':   ('Bitcoin',      '`bc1qauz0zaqy2hknz7afullhv2wa6elp04txhf2e02`'),
            'eth':   ('Ethereum',     '`0x32bc85F9F8A4F00D5983b8Bdbd3E8a83685c3CCE`'),
        }
        name, address = wallets[method]
        text = _T(uid, 'wallet_info').format(amount=amount, name=name, address=address)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(_T(uid, 'i_paid'), callback_data=f"paid_{method}_{amount}"),
            _back_btn(uid, "m_balance"),
        )
        bot.edit_message_text(text, uid, call.message.message_id,
                              reply_markup=markup, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
    def ask_screenshot(call):
        uid = call.message.chat.id
        msg = bot.send_message(uid, _T(uid, 'send_screenshot'))
        bot.register_next_step_handler(msg, _process_screenshot, call.data)

    def _process_screenshot(message, payment_info):
        uid = message.chat.id
        if not message.photo and not message.document:
            bot.send_message(uid, _T(uid, 'not_screenshot'))
            return
        parts = payment_info.split('_')
        method = parts[1]
        amount = parts[2]
        user = message.from_user
        uname = f"@{user.username}" if user.username else ""
        data = _r.get_user_data(uid)
        pp = data.get('pending_payment', {})
        if pp.get('is_balance_topup'):
            desc = "поповнення балансу боту"
        else:
            ptype = pp.get('type')
            desc_map = {
                'url':    "купівлі місячної/річної URL реклами",
                'grp':    "купівлі місячної/річної реклами по групах",
                'tiktok': "купівлі підписки на рекламу у TikTok",
                'all':    "купівлі підписки на всі сервіси",
            }
            desc = desc_map.get(ptype, "купівлі URL+групи")
        caption = (
            f"{user.first_name} ({user.id}) {uname}\n"
            f"Здійснив переказ на {method} на суму {amount}$ для {desc}."
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✅ Підтвердити платіж",
                                       callback_data=f"adm_confirm_pay_{uid}_{amount}"),
            types.InlineKeyboardButton("❌ Відхилити платіж",
                                       callback_data=f"adm_reject_pay_{uid}"),
        )
        if message.photo:
            bot.send_photo(_r.ADMIN_ID, message.photo[-1].file_id,
                           caption=caption, reply_markup=markup)
        else:
            bot.send_document(_r.ADMIN_ID, message.document.file_id,
                              caption=caption, reply_markup=markup)
        bot.send_message(uid, _T(uid, 'payment_wait'))

    @bot.callback_query_handler(func=lambda call: call.data.startswith('adm_confirm_pay_'))
    def admin_ask_confirm(call):
        if call.from_user.id != _r.ADMIN_ID:
            return
        parts = call.data.split('_')
        uid = int(parts[3])
        amount = parts[4]
        msg = bot.send_message(_r.ADMIN_ID, _T(_r.ADMIN_ID, 'adm_payment_confirm'))
        bot.register_next_step_handler(msg, _admin_final_confirm, uid, amount, call.message)

    def _admin_final_confirm(message, uid, amount, original_msg):
        if message.text.strip().lower() == 'так':
            data = _r.get_user_data(uid)
            pp = data.get('pending_payment', {})
            if pp.get('is_balance_topup'):
                data['balance'] += int(amount)
                bot.send_message(uid, f"✅ Ваш баланс поповнено на {amount}$.")
                _r.save_db()
            else:
                new_end = time.time() + pp['duration']
                ptype = pp['type']
                if ptype in ('url', 'mix', 'all'):
                    data['sub_url_until'] = new_end
                if ptype in ('grp', 'mix', 'all'):
                    data['sub_groups_until'] = new_end
                if ptype in ('tiktok', 'all'):
                    data['sub_tiktok_until'] = new_end
                bot.send_message(uid, _T(uid, 'payment_approved'))
                _r.save_db()
            data.pop('pending_payment', None)
            bot.send_message(_r.ADMIN_ID, "✅ Операцію підтверджено.")
            try:
                bot.edit_message_reply_markup(original_msg.chat.id,
                                              original_msg.message_id,
                                              reply_markup=None)
            except Exception:
                pass
        else:
            bot.send_message(_r.ADMIN_ID, "❌ Підтвердження скасовано.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('adm_reject_pay_'))
    def admin_reject_pay(call):
        if call.from_user.id != _r.ADMIN_ID:
            return
        uid = int(call.data.split('_')[3])
        data = _r.get_user_data(uid)
        data.pop('pending_payment', None)
        bot.send_message(uid, _T(uid, 'payment_rejected'),
                         reply_markup=types.InlineKeyboardMarkup().add(
                             types.InlineKeyboardButton(_T(uid, 'b_support'),
                                                        callback_data='m_support'),
                             _back_btn(uid),
                         ))
        try:
            bot.edit_message_reply_markup(call.message.chat.id,
                                          call.message.message_id,
                                          reply_markup=None)
        except Exception:
            pass
