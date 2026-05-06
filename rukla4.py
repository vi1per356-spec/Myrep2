from telebot import types


def _T(uid: int, key: str) -> str:
    try:
        import rukla as _r
        return _r.T(uid, key)
    except Exception:
        return key


def open_shop(bot, uid: int, message_id: int):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(_T(uid, 'b_back'), callback_data="m_manage_ad"),
    )
    bot.edit_message_text(_T(uid, 'shop_greeting'), uid, message_id, reply_markup=markup)
