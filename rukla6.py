from telebot import types


def _T(uid: int, key: str) -> str:
    try:
        import rukla as _r
        return _r.T(uid, key)
    except Exception:
        return key


def open_accounts_shop(bot, uid: int, message_id: int):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(_T(uid, 'acc_shop_btn_tg'),    callback_data="r7_type_tg_acc"),
        types.InlineKeyboardButton(_T(uid, 'acc_shop_btn_tt'),    callback_data="r7_type_tt_acc"),
        types.InlineKeyboardButton(_T(uid, 'acc_shop_btn_proxy'), callback_data="r7_type_proxy"),
        types.InlineKeyboardButton(_T(uid, 'b_back'),             callback_data="m_main"),
    )
    bot.edit_message_text(
        _T(uid, 'acc_shop_greeting'),
        uid, message_id,
        reply_markup=markup,
    )


def register_callbacks(bot):
    pass
