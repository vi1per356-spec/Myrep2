"""
apply_rukla_fix.py — one-shot patcher for rukla.py.

Run once after pulling this branch:

    python apply_rukla_fix.py

It updates rukla.py so that clicking «Реклама у TikTok» from the main
menu opens the merged parent menu in rukla5 (which already exposes
manage-accounts AND every parameter button), instead of the obsolete
two-button submenu.

The script is idempotent — safe to run multiple times.  It exits with 0
if rukla.py is already patched, 1 on any error.
"""

from __future__ import annotations

import sys
from pathlib import Path

RUKLA_PATH = Path(__file__).parent / "rukla.py"

OLD_BLOCK = '''    else:  # m_manage_tiktok
        if not is_sub_active(data.get('sub_tiktok_until', 0)):
            bot.answer_callback_query(call.id, T(uid,'locked'), show_alert=True)
            return
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(T(uid, 'b_manage_accounts'),  callback_data="m_tiktok_accounts"),
            types.InlineKeyboardButton(T(uid, 'b_manage_ad_params'), callback_data="m_tiktok_params"),
            types.InlineKeyboardButton(T(uid, 'b_back_prev'),        callback_data="m_manage_ad"),
        )
        try:
            bot.edit_message_text(T(uid, 'manage_ad_greeting'), uid, call.message.message_id, reply_markup=markup)
        except Exception:
            bot.send_message(uid, T(uid, 'manage_ad_greeting'), reply_markup=markup)'''

NEW_BLOCK = '''    else:  # m_manage_tiktok
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
                                  uid, call.message.message_id)'''

OLD_PARAMS_HANDLER = '''@bot.callback_query_handler(func=lambda call: call.data == 'm_tiktok_params')
def tiktok_params_menu(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    try:
        import rukla5
        rukla5.open_params_menu(bot, uid, call.message.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Модуль rukla5 недоступний: {e}", uid, call.message.message_id)'''

NEW_PARAMS_HANDLER = '''@bot.callback_query_handler(func=lambda call: call.data == 'm_tiktok_params')
def tiktok_params_menu(call):
    """Backwards-compat alias — старі повідомлення можуть містити цю кнопку.
    Відкриває об'єднаний parent menu (де параметри + керування акаунтами)."""
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    try:
        import rukla5
        rukla5.open_main_menu(bot, uid, call.message.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Модуль rukla5 недоступний: {e}", uid, call.message.message_id)'''


def main() -> int:
    if not RUKLA_PATH.exists():
        print(f"❌ rukla.py не знайдено за шляхом {RUKLA_PATH}")
        return 1

    src = RUKLA_PATH.read_text(encoding="utf-8")

    if NEW_BLOCK in src and NEW_PARAMS_HANDLER in src:
        print("✅ rukla.py вже застосовано — нічого робити.")
        return 0

    changed = False

    if OLD_BLOCK in src:
        src = src.replace(OLD_BLOCK, NEW_BLOCK, 1)
        changed = True
        print("✓ replaced m_manage_tiktok handler")
    elif NEW_BLOCK in src:
        print("• m_manage_tiktok already updated, skipping")
    else:
        print("⚠️  m_manage_tiktok handler not found in expected form — manual fix needed")
        return 1

    if OLD_PARAMS_HANDLER in src:
        src = src.replace(OLD_PARAMS_HANDLER, NEW_PARAMS_HANDLER, 1)
        changed = True
        print("✓ replaced m_tiktok_params handler")
    elif NEW_PARAMS_HANDLER in src:
        print("• m_tiktok_params already updated, skipping")
    else:
        print("⚠️  m_tiktok_params handler not found in expected form — skipping that one")

    if changed:
        RUKLA_PATH.write_text(src, encoding="utf-8")
        print(f"✅ rukla.py пропатчено ({RUKLA_PATH})")
    else:
        print("(no changes were necessary)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
