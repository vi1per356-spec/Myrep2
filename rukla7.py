"""
Account / proxy purchase flow.

Spec:
- Entry: "Купити акаунти для X" inside Керувати акаунтами submenu of URL/Group/TikTok.
- Menu: "📱 Купити акаунти для X" + "🌍 Купити проксі для X" + Back.
- Click → "Ціна за один акаунт 0.50$" → user enters quantity → bot calculates total.
- Payment options: balance only if total < 10$; balance + card + crypto if >= 10$.
- After payment from balance: "⏱ Очікуйте відповіді від адміністрації."
- Admin gets: user info + amount + N×accounts for X. Buttons: Approve / Reject / Contact.
- Approve → ask admin for N accounts; admin sends; bot validates count and forwards to user.
- Contact → support-like chat; on /close re-show approve/reject.
- 25-account hard limit honored when delivering.
"""
import json
import os
import time
from telebot import types

ORDERS_FILE = 'orders.json'
PRICE_PER_UNIT = 0.50  # $ per account or proxy

_orders: dict = {}
_pending_qty_input: dict = {}      # uid -> {'context': 'url'|'grp'|'tiktok', 'kind': 'acc'|'proxy'}
_pending_admin_delivery: dict = {} # admin_uid -> {'oid': ..., 'received': []}
_admin_contact: dict = {}          # admin_uid -> oid (admin currently chatting)
_user_contact: dict = {}           # user_uid -> oid (user currently chatting)
_bot_ref = None                    # set in register_callbacks for use in next_step handlers

_EXT_WALLETS = {
    'mono':  ('Monobank',     '`4874 1000 2703 7129`'),
    'trc20': ('USDT TRC-20',  '`TQA13mo3bK1r29LNPYZ5wGwHB8vv22tFix`'),
    'ton':   ('USDT TON',     '`UQA8WHq2-asw9S-v11HheGVjXYRXMN1osupOPDnb9u1OlrZQ`'),
    'erc20': ('USDT ERC-20',  '`0x32bc85F9F8A4F00D5983b8Bdbd3E8a83685c3CCE`'),
    'btc':   ('Bitcoin',      '`bc1qauz0zaqy2hknz7afullhv2wa6elp04txhf2e02`'),
    'eth':   ('Ethereum',     '`0x32bc85F9F8A4F00D5983b8Bdbd3E8a83685c3CCE`'),
}


def _T(uid: int, key: str) -> str:
    try:
        import rukla as _r
        return _r.T(uid, key)
    except Exception:
        return key


def _load():
    global _orders
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE, 'r', encoding='utf-8') as f:
                _orders = json.load(f)
        except Exception:
            _orders = {}


def _save():
    with open(ORDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(_orders, f, ensure_ascii=False, indent=2)


def _oid() -> str:
    return str(int(time.time() * 1000))[-9:]


def _ctx_label(ctx: str, uid: int) -> str:
    """Localized label of the advertising context."""
    return {
        'url':    _T(uid, 'r7_ctx_url'),
        'grp':    _T(uid, 'r7_ctx_grp'),
        'tiktok': _T(uid, 'r7_ctx_tiktok'),
    }.get(ctx, ctx)


def _kind_label(kind: str, uid: int) -> str:
    return _T(uid, 'r7_kind_acc') if kind == 'acc' else _T(uid, 'r7_kind_proxy')


def _back_callback(ctx: str) -> str:
    """Where to return after order/cancel inside the purchase flow."""
    return {
        'url':    'r7_buy_acc_url',
        'grp':    'r7_buy_acc_grp',
        'tiktok': 'r7_buy_acc_tiktok',
    }.get(ctx, 'm_main')


def open_purchase_menu(bot, uid: int, message_id: int, ctx: str):
    """Show 'buy accounts / buy proxies / back' for given context."""
    label = _ctx_label(ctx, uid)
    text = _T(uid, 'r7_menu_greeting').format(label=label)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            _T(uid, 'b_buy_acc_' + ctx),
            callback_data=f"r7_pick_acc_{ctx}"
        ),
        types.InlineKeyboardButton(
            _T(uid, 'b_buy_proxy_' + ctx),
            callback_data=f"r7_pick_proxy_{ctx}"
        ),
        types.InlineKeyboardButton(
            _T(uid, 'b_back_prev'),
            callback_data=f"r7_back_{ctx}"
        ),
    )
    try:
        bot.edit_message_text(text, uid, message_id, reply_markup=markup)
    except Exception:
        bot.send_message(uid, text, reply_markup=markup)


def _ask_quantity(bot, uid: int, ctx: str, kind: str):
    _pending_qty_input[uid] = {'context': ctx, 'kind': kind}
    label_kind = _kind_label(kind, uid)
    label_ctx = _ctx_label(ctx, uid)
    bot.send_message(
        uid,
        _T(uid, 'r7_ask_qty').format(
            kind=label_kind, label=label_ctx, price=PRICE_PER_UNIT,
        ),
    )


def _show_checkout(bot, uid: int, ctx: str, kind: str, qty: int):
    total = round(qty * PRICE_PER_UNIT, 2)
    label_kind = _kind_label(kind, uid)
    label_ctx = _ctx_label(ctx, uid)
    try:
        import rukla as _r
        balance = _r.get_user_data(uid).get('balance', 0)
    except Exception:
        balance = 0
    text = _T(uid, 'r7_checkout').format(
        kind=label_kind, label=label_ctx, qty=qty, price=PRICE_PER_UNIT,
        total=total, balance=balance,
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(
        _T(uid, 'r7_pay_balance'), callback_data=f"r7_pay_balance_{ctx}_{kind}_{qty}"
    ))
    if total >= 10:
        markup.add(
            types.InlineKeyboardButton("Monobank - переказ на картку", callback_data=f"r7_ext_mono_{ctx}_{kind}_{qty}"),
            types.InlineKeyboardButton("USDT (TRON - TRC-20)",         callback_data=f"r7_ext_trc20_{ctx}_{kind}_{qty}"),
            types.InlineKeyboardButton("USDT (TON)",                   callback_data=f"r7_ext_ton_{ctx}_{kind}_{qty}"),
            types.InlineKeyboardButton("USDT (Ethereum - ERC-20)",     callback_data=f"r7_ext_erc20_{ctx}_{kind}_{qty}"),
            types.InlineKeyboardButton("Bitcoin (BTC)",                callback_data=f"r7_ext_btc_{ctx}_{kind}_{qty}"),
            types.InlineKeyboardButton("Ethereum",                     callback_data=f"r7_ext_eth_{ctx}_{kind}_{qty}"),
        )
    markup.add(types.InlineKeyboardButton(_T(uid, 'b_back_prev'), callback_data=f"r7_back_{ctx}"))
    bot.send_message(uid, text, reply_markup=markup)


def _place_order_balance(bot, uid: int, ctx: str, kind: str, qty: int):
    """Pay from balance, create order, notify admin."""
    _load()
    try:
        import rukla as _r
        data = _r.get_user_data(uid)
        balance = data.get('balance', 0)
        total = round(qty * PRICE_PER_UNIT, 2)
        if balance < total:
            bot.send_message(uid, _T(uid, 'not_enough_balance').format(balance=balance, price=total))
            return
        data['balance'] = round(balance - total, 2)
        _r.save_db()

        oid = _oid()
        order = {
            'id': oid,
            'uid': uid,
            'context': ctx,
            'kind': kind,
            'qty': qty,
            'total': total,
            'status': 'pending',
            'paid_with': 'balance',
            'created': int(time.time()),
        }
        _orders[oid] = order
        _save()

        bot.send_message(uid, _T(uid, 'r7_paid_wait'))

        # Notify admin
        admin_id = _r.ADMIN_ID
        try:
            user = bot.get_chat(uid)
            uname = f"@{user.username}" if user.username else ""
            u_name = user.first_name
        except Exception:
            uname = ""
            u_name = str(uid)
        label_kind = _kind_label(kind, admin_id)
        label_ctx = _ctx_label(ctx, admin_id)
        adm_text = _T(admin_id, 'r7_admin_new_order').format(
            name=u_name, uid=uid, uname=uname,
            total=total, qty=qty, kind=label_kind, label=label_ctx,
            oid=oid,
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(_T(admin_id, 'r7_admin_approve'), callback_data=f"r7_approve_{oid}"),
            types.InlineKeyboardButton(_T(admin_id, 'r7_admin_reject'),  callback_data=f"r7_reject_{oid}"),
            types.InlineKeyboardButton(_T(admin_id, 'r7_admin_contact'), callback_data=f"r7_contact_{oid}"),
        )
        try:
            bot.send_message(admin_id, adm_text, reply_markup=markup, parse_mode="HTML")
        except Exception as e:
            print(f"[rukla7] notify admin failed: {e}")
    except Exception as e:
        print(f"[rukla7] _place_order_balance error: {e}")
        try: bot.send_message(uid, f"❌ {e}")
        except Exception: pass


def _show_admin_order_actions(bot, oid: str):
    """Re-show approve/reject/contact for an order to admin (used after /close)."""
    _load()
    order = _orders.get(oid)
    if not order or order['status'] != 'pending':
        return
    try:
        import rukla as _r
        admin_id = _r.ADMIN_ID
        uid = order['uid']
        try:
            user = bot.get_chat(uid)
            uname = f"@{user.username}" if user.username else ""
            u_name = user.first_name
        except Exception:
            uname = ""
            u_name = str(uid)
        label_kind = _kind_label(order['kind'], admin_id)
        label_ctx = _ctx_label(order['context'], admin_id)
        text = _T(admin_id, 'r7_admin_new_order').format(
            name=u_name, uid=uid, uname=uname,
            total=order['total'], qty=order['qty'],
            kind=label_kind, label=label_ctx,
            oid=oid,
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(_T(admin_id, 'r7_admin_approve'), callback_data=f"r7_approve_{oid}"),
            types.InlineKeyboardButton(_T(admin_id, 'r7_admin_reject'),  callback_data=f"r7_reject_{oid}"),
            types.InlineKeyboardButton(_T(admin_id, 'r7_admin_contact'), callback_data=f"r7_contact_{oid}"),
        )
        bot.send_message(admin_id, text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        print(f"[rukla7] _show_admin_order_actions: {e}")


def register_callbacks(bot):
    global _bot_ref
    _bot_ref = bot

    # ---- Entry from Керувати акаунтами submenu ----
    @bot.callback_query_handler(func=lambda call: call.data in ('r7_buy_acc_url', 'r7_buy_acc_grp', 'r7_buy_acc_tiktok'))
    def r7_open_buy(call):
        uid = call.message.chat.id
        ctx = call.data.replace('r7_buy_acc_', '')
        bot.answer_callback_query(call.id)
        open_purchase_menu(bot, uid, call.message.message_id, ctx)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('r7_back_'))
    def r7_back(call):
        uid = call.message.chat.id
        ctx = call.data.replace('r7_back_', '')
        bot.answer_callback_query(call.id)
        _pending_qty_input.pop(uid, None)
        # Return to the corresponding "manage accounts" submenu by re-opening manage_ad
        try:
            import rukla1
            if ctx == 'url':
                rukla1._run_on_rukla1_loop(rukla1.show_url_manage_accounts_menu(uid))
            elif ctx == 'grp':
                rukla1._run_on_rukla1_loop(rukla1.show_grp_manage_accounts_menu(uid))
            else:  # tiktok
                import rukla5
                rukla5.open_tiktok_menu(bot, uid, call.message.message_id)
        except Exception as e:
            try:
                import rukla as _r
                bot.edit_message_text(_r.T(uid, 'greeting'), uid, call.message.message_id,
                                      reply_markup=_r.get_main_menu(uid))
            except Exception:
                bot.send_message(uid, str(e))

    # ---- Pick acc / proxy ----
    @bot.callback_query_handler(func=lambda call: call.data.startswith('r7_pick_'))
    def r7_pick(call):
        uid = call.message.chat.id
        rest = call.data.replace('r7_pick_', '')   # 'acc_url' | 'proxy_grp' ...
        if '_' not in rest:
            return
        kind, ctx = rest.split('_', 1)
        if kind not in ('acc', 'proxy') or ctx not in ('url', 'grp', 'tiktok'):
            return
        bot.answer_callback_query(call.id)
        _ask_quantity(bot, uid, ctx, kind)

    # ---- Quantity input ----
    @bot.message_handler(
        func=lambda msg: msg.chat.id in _pending_qty_input,
        content_types=['text'],
    )
    def r7_qty(message):
        uid = message.chat.id
        st = _pending_qty_input.pop(uid, None)
        if not st:
            return
        text = (message.text or "").strip()
        try:
            qty = int(text)
            if qty <= 0 or qty > 1000:
                raise ValueError()
        except Exception:
            bot.send_message(uid, _T(uid, 'r7_qty_invalid'))
            _pending_qty_input[uid] = st
            return
        _show_checkout(bot, uid, st['context'], st['kind'], qty)

    # ---- Payment: balance ----
    @bot.callback_query_handler(func=lambda call: call.data.startswith('r7_pay_balance_'))
    def r7_pay_balance_cb(call):
        uid = call.message.chat.id
        # r7_pay_balance_{ctx}_{kind}_{qty}
        rest = call.data.replace('r7_pay_balance_', '')
        parts = rest.split('_')
        if len(parts) != 3:
            bot.answer_callback_query(call.id, "Invalid", show_alert=True)
            return
        ctx, kind, qty_str = parts
        try:
            qty = int(qty_str)
        except ValueError:
            return
        bot.answer_callback_query(call.id)
        _place_order_balance(bot, uid, ctx, kind, qty)

    # ---- Payment: external (wallet address) ----
    @bot.callback_query_handler(func=lambda call: call.data.startswith('r7_ext_'))
    def r7_pay_ext(call):
        uid = call.message.chat.id
        # r7_ext_{method}_{ctx}_{kind}_{qty}
        rest = call.data.replace('r7_ext_', '')
        parts = rest.split('_')
        if len(parts) != 4:
            bot.answer_callback_query(call.id, "Invalid", show_alert=True)
            return
        method, ctx, kind, qty_str = parts
        try:
            qty = int(qty_str)
        except ValueError:
            return
        total = round(qty * PRICE_PER_UNIT, 2)
        w = _EXT_WALLETS.get(method)
        if not w:
            bot.answer_callback_query(call.id, "Unknown method", show_alert=True)
            return
        name, address = w
        bot.answer_callback_query(call.id)
        try:
            import rukla as _r
            text = _r.T(uid, 'wallet_info').format(amount=total, name=name, address=address)
        except Exception:
            text = (
                f"💳 До сплати: {total}$.\n"
                f"‼️ Комісію мережі покриваєте ви!\n\n"
                f"Адреса ({name}):\n{address}\n\n"
                "Після переказу натисніть «Я сплатив»."
            )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                _T(uid, 'i_paid'),
                callback_data=f"r7_paid_{method}_{ctx}_{kind}_{qty}",
            ),
            types.InlineKeyboardButton(_T(uid, 'b_back_prev'), callback_data=f"r7_back_{ctx}"),
        )
        try:
            bot.edit_message_text(text, uid, call.message.message_id,
                                  reply_markup=markup, parse_mode="Markdown")
        except Exception:
            bot.send_message(uid, text, reply_markup=markup, parse_mode="Markdown")

    # ---- Payment: "I paid" → ask screenshot ----
    @bot.callback_query_handler(func=lambda call: call.data.startswith('r7_paid_'))
    def r7_paid_ext(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        pay_info = call.data.replace('r7_paid_', '')   # method_ctx_kind_qty
        try:
            import rukla as _r
            prompt = _r.T(uid, 'send_screenshot')
        except Exception:
            prompt = "📃 Надішліть скріншот переказу."
        msg = bot.send_message(uid, prompt)
        bot.register_next_step_handler(msg, _r7_process_screenshot, pay_info)

    # ---- Admin: Approve ----
    @bot.callback_query_handler(func=lambda call: call.data.startswith('r7_approve_'))
    def r7_approve(call):
        try:
            import rukla as _r
            if call.from_user.id != _r.ADMIN_ID:
                return
        except Exception:
            return
        oid = call.data.replace('r7_approve_', '')
        _load()
        order = _orders.get(oid)
        if not order or order['status'] != 'pending':
            bot.answer_callback_query(call.id, f"#{oid}: not pending", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        _pending_admin_delivery[call.from_user.id] = {'oid': oid, 'received': []}
        kind = order['kind']
        qty = order['qty']
        ext = ".session" if kind == 'acc' and order['context'] != 'tiktok' else \
              "Cookie" if kind == 'acc' else "host:port[:user:pass]"
        bot.send_message(
            call.from_user.id,
            _T(call.from_user.id, 'r7_admin_send_n').format(qty=qty, ext=ext, oid=oid),
        )

    # ---- Admin: Reject ----
    @bot.callback_query_handler(func=lambda call: call.data.startswith('r7_reject_'))
    def r7_reject(call):
        try:
            import rukla as _r
            if call.from_user.id != _r.ADMIN_ID:
                return
        except Exception:
            return
        oid = call.data.replace('r7_reject_', '')
        _load()
        order = _orders.get(oid)
        if not order or order['status'] != 'pending':
            bot.answer_callback_query(call.id, f"#{oid}: not pending", show_alert=True)
            return
        order['status'] = 'rejected'
        _save()
        # Refund balance only if paid with balance
        refund_msg = _T(order['uid'], 'r7_user_rejected').format(oid=oid, total=order['total'])
        if order.get('paid_with', 'balance') == 'balance':
            try:
                import rukla as _r
                d = _r.get_user_data(order['uid'])
                d['balance'] = round(d.get('balance', 0) + order['total'], 2)
                _r.save_db()
            except Exception:
                pass
        else:
            # External payment — no automatic refund
            refund_msg = (
                f"❌ Ваше замовлення #{oid} відхилено.\n"
                "Якщо кошти були надіслані — зверніться у технічну підтримку для повернення."
            )
        bot.answer_callback_query(call.id, f"#{oid} rejected.")
        try:
            bot.send_message(order['uid'], refund_msg)
        except Exception:
            pass

    # ---- Admin: Contact ----
    @bot.callback_query_handler(func=lambda call: call.data.startswith('r7_contact_'))
    def r7_contact(call):
        try:
            import rukla as _r
            if call.from_user.id != _r.ADMIN_ID:
                return
        except Exception:
            return
        oid = call.data.replace('r7_contact_', '')
        _load()
        order = _orders.get(oid)
        if not order or order['status'] != 'pending':
            bot.answer_callback_query(call.id, f"#{oid}: not pending", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        admin_id = call.from_user.id
        target = order['uid']
        _admin_contact[admin_id] = oid
        _user_contact[target] = oid
        bot.send_message(admin_id, _T(admin_id, 'r7_admin_contact_open').format(uid=target, oid=oid))
        try:
            bot.send_message(target, _T(target, 'r7_user_contact_open').format(oid=oid))
        except Exception:
            pass

    # ---- Admin sends accounts/proxies after approve ----
    @bot.message_handler(
        func=lambda msg: msg.from_user.id in _pending_admin_delivery,
        content_types=['text', 'document', 'photo'],
    )
    def r7_admin_delivery(message):
        admin_id = message.from_user.id
        st = _pending_admin_delivery.get(admin_id)
        if not st:
            return
        # /done finishes delivery
        if message.text and message.text.strip().lower() in ('/done', 'done'):
            _finish_delivery(bot, admin_id)
            return
        st['received'].append({
            'msg_id': message.message_id,
            'type': message.content_type,
        })
        order = _orders.get(st['oid'])
        if order:
            need = order['qty']
            got = len(st['received'])
            bot.send_message(admin_id, _T(admin_id, 'r7_delivery_progress').format(got=got, need=need))
            if got >= need:
                _finish_delivery(bot, admin_id)

    # ---- Admin <-> User contact relay ----
    @bot.message_handler(
        func=lambda msg: msg.from_user.id in _admin_contact and not (msg.text or '').startswith('/close'),
        content_types=['text', 'photo', 'document'],
    )
    def r7_admin_to_user(message):
        admin_id = message.from_user.id
        oid = _admin_contact.get(admin_id)
        if not oid:
            return
        order = _orders.get(oid) or {}
        target = order.get('uid')
        if not target:
            return
        try:
            if message.content_type == 'text':
                bot.send_message(target, message.text)
            else:
                bot.copy_message(target, admin_id, message.message_id)
        except Exception as e:
            bot.send_message(admin_id, f"❌ {e}")

    @bot.message_handler(
        func=lambda msg: msg.from_user.id in _user_contact and not (msg.text or '').startswith('/close'),
        content_types=['text', 'photo', 'document'],
    )
    def r7_user_to_admin(message):
        uid = message.from_user.id
        oid = _user_contact.get(uid)
        if not oid:
            return
        try:
            import rukla as _r
            admin_id = _r.ADMIN_ID
            if message.content_type == 'text':
                bot.send_message(admin_id, f"[#{oid}] {message.text}")
            else:
                bot.copy_message(admin_id, uid, message.message_id)
        except Exception as e:
            print(f"[rukla7] r7_user_to_admin: {e}")

    # /close handled by rukla.py close_ticket which calls _do_close_contact
    pass  # placeholder to preserve indentation


def _r7_process_screenshot(message, pay_info: str):
    """next_step handler: receives screenshot for external account purchase."""
    uid = message.chat.id
    bot = _bot_ref
    if bot is None:
        return
    if not message.photo and not message.document:
        try:
            import rukla as _r
            bot.send_message(uid, _r.T(uid, 'not_screenshot'))
        except Exception:
            bot.send_message(uid, "Це не скріншот. Спробуйте ще раз.")
        return
    # pay_info = "method_ctx_kind_qty"
    parts = pay_info.split('_')
    if len(parts) != 4:
        return
    method, ctx, kind, qty_str = parts
    try:
        qty = int(qty_str)
    except ValueError:
        return
    total = round(qty * PRICE_PER_UNIT, 2)

    # Create pending order
    _load()
    oid = _oid()
    order = {
        'id': oid,
        'uid': uid,
        'context': ctx,
        'kind': kind,
        'qty': qty,
        'total': total,
        'status': 'pending',
        'paid_with': 'external',
        'ext_method': method,
        'created': int(time.time()),
    }
    _orders[oid] = order
    _save()

    # Notify admin with screenshot
    try:
        import rukla as _r
        admin_id = _r.ADMIN_ID
        user = message.from_user
        uname = f"@{user.username}" if user.username else ""
        label_kind = _kind_label(kind, admin_id)
        label_ctx = _ctx_label(ctx, admin_id)
        w_name = _EXT_WALLETS.get(method, (method, ''))[0]
        caption = (
            f"🛒 Нове замовлення #{oid}\n\n"
            f"👤 {user.first_name} ({uid}) {uname}\n"
            f"📦 {qty}× {label_kind} для {label_ctx}\n"
            f"💳 {w_name}, сума: {total}$"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(_T(admin_id, 'r7_admin_approve'), callback_data=f"r7_approve_{oid}"),
            types.InlineKeyboardButton(_T(admin_id, 'r7_admin_reject'),  callback_data=f"r7_reject_{oid}"),
            types.InlineKeyboardButton(_T(admin_id, 'r7_admin_contact'), callback_data=f"r7_contact_{oid}"),
        )
        if message.photo:
            bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption,
                           reply_markup=markup)
        else:
            bot.send_document(admin_id, message.document.file_id, caption=caption,
                              reply_markup=markup)
        bot.send_message(uid, _r.T(uid, 'r7_paid_wait'))
    except Exception as e:
        print(f"[rukla7] _r7_process_screenshot error: {e}")
        try:
            bot.send_message(uid, f"❌ {e}")
        except Exception:
            pass


def _get_admin_id():
    try:
        import rukla as _r
        return _r.ADMIN_ID
    except Exception:
        return None


def _do_close_contact(bot, actor: int):
    """Called by rukla.py /close handler when actor is in an order contact relay."""
    _load()
    oid = _admin_contact.pop(actor, None) or _user_contact.pop(actor, None)
    if not oid:
        return
    order = _orders.get(oid) or {}
    admin_id = _get_admin_id()
    if actor == order.get('uid'):
        if admin_id:
            _admin_contact.pop(admin_id, None)
    else:
        _user_contact.pop(order.get('uid'), None)
    try:
        bot.send_message(actor, _T(actor, 'r7_contact_closed'))
        other = order.get('uid') if actor != order.get('uid') else admin_id
        if other:
            try:
                bot.send_message(other, _T(other, 'r7_contact_closed'))
            except Exception:
                pass
    except Exception:
        pass
    if order and order.get('status') == 'pending':
        _show_admin_order_actions(bot, oid)


def _finish_delivery(bot, admin_id: int):
    st = _pending_admin_delivery.pop(admin_id, None)
    if not st:
        return
    _load()
    order = _orders.get(st['oid'])
    if not order:
        bot.send_message(admin_id, "❌ Order not found.")
        return
    received = st['received']
    if len(received) < order['qty']:
        # Need more
        bot.send_message(
            admin_id,
            _T(admin_id, 'r7_delivery_short').format(got=len(received), need=order['qty']),
        )
        # restart pending delivery for the missing items
        _pending_admin_delivery[admin_id] = {'oid': st['oid'], 'received': received}
        return

    # Forward to user
    target = order['uid']
    delivered = 0
    for item in received:
        try:
            bot.forward_message(target, admin_id, item['msg_id'])
            delivered += 1
        except Exception as e:
            print(f"[rukla7] forward to user failed: {e}")

    label_kind = _kind_label(order['kind'], target)
    label_ctx = _ctx_label(order['context'], target)
    try:
        bot.send_message(
            target,
            _T(target, 'r7_user_delivered').format(
                oid=order['id'], kind=label_kind, label=label_ctx, qty=order['qty'],
            ),
        )
    except Exception as e:
        print(f"[rukla7] notify user failed: {e}")

    order['status'] = 'done'
    order['delivered'] = delivered
    _save()
    bot.send_message(admin_id, _T(admin_id, 'r7_delivery_done').format(oid=order['id'], n=delivered))
