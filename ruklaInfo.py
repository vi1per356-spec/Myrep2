from telebot import types

TEXTS = {
    'uk': {
        'b_info': "ℹ️ ВАЖЛИВО: прочитати перед купівлею",
        'info_main': (
            "👋 Вітаю. Перед купівлею однієї з функцій прочитайте важливу інформацію про них натиснувши відповідну клавішу знизу.\n\n"
            "💻 В разі якщо вам щось не зрозуміло - зверніться у технічну підтримку."
        ),
        'info_btn_url':    "📣 Про URL рекламу",
        'info_btn_grp':    "💬 Про рекламу по групах",
        'info_btn_tiktok': "🛩 Про рекламу у Tik-Tok",
        'info_url_text': (
            "📣 <b>URL реклама</b>\n\n"
            "👋 Вітаю любий друже! Я дуже радий що ти вирішив вибрати саме нас, для просування свого каналу.\n\n"
            "ℹ️ Отже, найголовніше що потрібно знати перед купівлею функції \"URL реклами\":\n"
            "—❓Що таке URL реклама? - у вас є база каналів (власна, або та, що ви створите за допомогою нашого боту) в якій буде рекламуватися наший бот. Пояснюю як це буде працювати: канал надсилає повідомлення ⊳ наший бот його переглядає, та надсилає у коментарі під ним текст, котрий ви дасте боту ⊳ проходить заданий вами час та надсилається нагадування ⊳ проходить заданий вами час, та цей цикл повторюється (проте, якщо канал надіслав нове повідомлення, цей цикл буде відтворювати знову, але вже під ним). Також, в \"рекламі за допомогою URL\" є функція, котра допоможе вам запобігти надсилання реклами під непотрібними повідомленнями: ключові слова - бот буде надсилати рекламу лише під тими повідомленнями, котрі містять ваші ключові слова.\n"
            "—❗️Важливо! Перед купівлею \"реклами URL\" впевніться що у вас є телеграм акаунти (використання свого особистого акаунту не рекомендується) та що у вас є .session Telethon файли до кожного акаунту.\n"
            "— ❓Чому так важливо використати проксі? - Використання проксі забезпечує ваші акаунти від передчасного блокування. Зазвичай рекомендується використовувати не більше 1х проксі на 5х акаунтів.\n"
            "—❔Яка ціна? - Реклама URL: 99$ на місяць / 1099$ на рік (економія 10%).\n\n"
            "Якщо у вас виникли запитання - зверніться до технічної підтримки."
        ),
        'info_grp_text': (
            "💬 <b>Реклама по групах</b>\n\n"
            "—❓Що таке реклама по групах? - у вас є база чатів (власна, або та, що ви створите за допомогою нашого боту) в якій буде рекламуватися наший бот. Пояснюю як це буде працювати: ви задаєте боту країну вашого каналу ⊳ надаєте посилання на ваший персональний канал ⊳ бот читає ваший канал, ви пишите умовно \"Сього у Варшаві досить сонячно\" ⊳ бот пересилає це повідомлення у чати Варшави/району ⊳ ви надсилаєте ще одне повідомлення у канал \"Сьогодні в Польші буде дощ\" ⊳ бот бачить що це не локальне повідомлення, та надсилає по всіх ваших чатах.\n"
            "—❗️Важливо! Перед купівлею впевніться що у вас є телеграм акаунти та .session Telethon файли до кожного акаунту.\n"
            "—❔Яка ціна? - Реклама по групах: 99$ на місяць / 1099$ на рік (економія 10%).\n\n"
            "Якщо у вас виникли запитання - зверніться до технічної підтримки."
        ),
        'info_tiktok_text': (
            "🛩 <b>Реклама у Tik-Tok</b>\n\n"
            "Інформація буде додана найближчим часом."
        ),
    },
    'en': {
        'b_info': "ℹ️ IMPORTANT: read before buying",
        'info_main': (
            "👋 Hello. Before purchasing any feature, please read the important information by clicking the relevant button below.\n\n"
            "💻 If you have any questions — contact technical support."
        ),
        'info_btn_url':    "📣 About URL advertising",
        'info_btn_grp':    "💬 About group advertising",
        'info_btn_tiktok': "🛩 About TikTok advertising",
        'info_url_text': "📣 <b>URL Advertising</b>\n\nInformation will be added soon.",
        'info_grp_text': "💬 <b>Group Advertising</b>\n\nInformation will be added soon.",
        'info_tiktok_text': "🛩 <b>TikTok Advertising</b>\n\nInformation will be added soon.",
    },
    'ru': {
        'b_info': "ℹ️ ВАЖНО: прочитать перед покупкой",
        'info_main': (
            "👋 Привет. Перед покупкой любой функции прочитайте важную информацию о ней, нажав соответствующую кнопку ниже.\n\n"
            "💻 Если что-то непонятно — обратитесь в техподдержку."
        ),
        'info_btn_url':    "📣 О URL рекламе",
        'info_btn_grp':    "💬 О рекламе в группах",
        'info_btn_tiktok': "🛩 О рекламе в Tik-Tok",
        'info_url_text': "📣 <b>URL Реклама</b>\n\nИнформация будет добавлена в ближайшее время.",
        'info_grp_text': "💬 <b>Реклама в группах</b>\n\nИнформация будет добавлена в ближайшее время.",
        'info_tiktok_text': "🛩 <b>Реклама в Tik-Tok</b>\n\nИнформация будет добавлена в ближайшее время.",
    },
}


def T(uid: int, key: str) -> str:
    try:
        import rukla as _r
        lang = _r.get_user_data(uid).get('lang', 'uk')
    except Exception:
        lang = 'uk'
    return TEXTS.get(lang, TEXTS['uk']).get(key, TEXTS['uk'].get(key, key))


def open_info_menu(bot, uid: int, message_id: int):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(T(uid, 'info_btn_url'),    callback_data="info_url"),
        types.InlineKeyboardButton(T(uid, 'info_btn_grp'),    callback_data="info_grp"),
        types.InlineKeyboardButton(T(uid, 'info_btn_tiktok'), callback_data="info_tiktok"),
    )
    try:
        import rukla as _r
        markup.add(
            types.InlineKeyboardButton(_r.T(uid, 'b_support'), callback_data="m_support"),
            types.InlineKeyboardButton(_r.T(uid, 'b_back'),    callback_data="m_main"),
        )
    except Exception:
        pass
    bot.edit_message_text(
        T(uid, 'info_main'),
        uid, message_id,
        reply_markup=markup,
    )


def _back_markup(uid: int):
    markup = types.InlineKeyboardMarkup(row_width=1)
    try:
        import rukla as _r
        back_text = _r.T(uid, 'b_back')
    except Exception:
        back_text = "⬅️ Назад"
    markup.add(types.InlineKeyboardButton(back_text, callback_data="info_back"))
    return markup


def register_callbacks(bot):
    @bot.callback_query_handler(func=lambda call: call.data == 'info_back')
    def info_back(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        open_info_menu(bot, uid, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data == 'info_url')
    def info_url(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            T(uid, 'info_url_text'),
            uid, call.message.message_id,
            reply_markup=_back_markup(uid),
            parse_mode="HTML",
        )

    @bot.callback_query_handler(func=lambda call: call.data == 'info_grp')
    def info_grp(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            T(uid, 'info_grp_text'),
            uid, call.message.message_id,
            reply_markup=_back_markup(uid),
            parse_mode="HTML",
        )

    @bot.callback_query_handler(func=lambda call: call.data == 'info_tiktok')
    def info_tiktok(call):
        uid = call.message.chat.id
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            T(uid, 'info_tiktok_text'),
            uid, call.message.message_id,
            reply_markup=_back_markup(uid),
            parse_mode="HTML",
        )
