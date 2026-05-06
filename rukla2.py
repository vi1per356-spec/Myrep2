import asyncio
from telethon import Button
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from rukla1 import (
    get_ctx, UserContext,
    distribute_and_join_all_channels,
    leave_channel_on_all_accounts,
    leave_folder_channels_on_all_accounts,
    show_accounts_menu,
    show_group_accounts_menu,
    _setup_monitoring_on_account,
    menu_bot_status,
    menu_group_bot_status,
    save_settings,
)


def _T(uid: int, key: str) -> str:
    try:
        import rukla as _r
        return _r.T(uid, key)
    except Exception:
        return key


# ================= МЕНЮ =================
def menu_styles(ctx: UserContext, uid: int = 0):
    buttons = []
    for name in ctx.bot_settings["styles"]:
        buttons.append([Button.inline(f"📄 {name}", f"view_style_{name}".encode())])
    buttons.append([Button.inline(_T(uid, 'r2_btn_create_style'), b"create_style")])
    if ctx.bot_settings["styles"]:
        buttons.append([Button.inline(_T(uid, 'r2_btn_del_style'), b"delete_style")])
    buttons.append([Button.inline(_T(uid, 'r1_btn_back_acc'), b"back_to_accounts")])
    return buttons


def menu_channels(ctx: UserContext, uid: int = 0):
    buttons = []
    for name in ctx.bot_settings["channels"]:
        buttons.append([Button.inline(f"📁 {name}", f"view_folder_{name}".encode())])
    buttons.append([Button.inline(_T(uid, 'r1_btn_create_folder'), b"create_folder")])
    if ctx.bot_settings["channels"]:
        buttons.append([Button.inline(_T(uid, 'r1_btn_del_folder'), b"delete_folder")])
    buttons.append([Button.inline(_T(uid, 'r1_btn_back_acc'), b"back_to_accounts")])
    return buttons


def menu_group_manage_groups(ctx: UserContext, uid: int = 0):
    chats = ctx.group_bot_settings["group_chats"]
    mon_ch = ctx.group_bot_settings["monitoring_channel"] or _T(uid, 'r2_not_set')
    mon_status = _T(uid, 'r2_mon_active') if ctx.group_bot_settings["monitoring_active"] else _T(uid, 'r2_mon_stopped')
    buttons = []
    for i, ch in enumerate(chats):
        title = ch.get("title", ch["link"])[:35]
        buttons.append([Button.inline(f"📌 {i+1}. {title}", f"g_view_group_{i}".encode())])
    buttons.append([Button.inline(_T(uid, 'r2_btn_add_group'), b"g_add_group")])
    if chats:
        buttons.append([Button.inline(_T(uid, 'r2_btn_del_group'), b"g_del_group")])
    buttons.append([Button.inline(_T(uid, 'r2_btn_interval'), b"g_set_interval")])
    buttons.append([Button.inline(_T(uid, 'r2_btn_repeat'), b"g_set_repeat")])
    buttons.append([Button.inline(_T(uid, 'r1_btn_back_acc'), b"g_back_to_accounts")])
    return mon_ch, mon_status, buttons


# ================= SHOW МЕНЮ =================
async def show_styles_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = None
    styles_text = "\n".join([f"• {n}: {t[:50]}..." for n, t in ctx.bot_settings["styles"].items()]) if ctx.bot_settings["styles"] else _T(chat_id, 'r2_styles_empty')
    await ctx.show_nav(chat_id, _T(chat_id, 'r2_styles_header').format(styles=styles_text), buttons=menu_styles(ctx, chat_id))


async def show_reminders_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = None
    rem_text = "\n".join([f"• {n}: {t[:40]}..." for n, t in ctx.bot_settings["reminders"].items()]) if ctx.bot_settings["reminders"] else _T(chat_id, 'r2_rems_empty')
    text = _T(chat_id, 'r2_rems_header').format(rems=rem_text, delay=ctx.bot_settings['reminder_delay'])
    buttons = []
    for name in ctx.bot_settings["reminders"]:
        buttons.append([Button.inline(f"📄 {name}", f"view_rem_{name}".encode())])
    buttons.append([Button.inline(_T(chat_id, 'r2_btn_create_rem'), b"create_rem")])
    if ctx.bot_settings["reminders"]:
        buttons.append([Button.inline(_T(chat_id, 'r2_btn_del_rem'), b"delete_rem")])
    buttons.append([Button.inline(_T(chat_id, 'r2_btn_set_delay'), b"set_rem_delay")])
    buttons.append([Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"back_to_accounts")])
    await ctx.show_nav(chat_id, text, buttons=buttons)


async def show_cycle_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = None
    state_text = _T(chat_id, 'r2_cycle_off') if ctx.bot_settings["cycle_delay"] == 0 else f"{ctx.bot_settings['cycle_delay']} сек."
    text = _T(chat_id, 'r2_cycle_header').format(state=state_text)
    buttons = [
        [Button.inline(_T(chat_id, 'r2_btn_set_cycle'), b"set_cycle_delay")],
        [Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"back_to_accounts")]
    ]
    await ctx.show_nav(chat_id, text, buttons=buttons)


async def show_channels_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = None
    if ctx.bot_settings["channels"]:
        ch_text = ""
        for fname, links in ctx.bot_settings["channels"].items():
            ch_text += f"\n📁 {fname}:\n" + "\n".join(f"  • {l}" for l in links) + "\n"
        text = _T(chat_id, 'r1_channels_header') + ch_text
    else:
        text = _T(chat_id, 'r1_channels_empty')
    await ctx.show_nav(chat_id, text, buttons=menu_channels(ctx, chat_id))


async def show_group_manage_menu(chat_id):
    ctx = get_ctx(chat_id)
    ctx.user_states[chat_id] = None
    mon_ch, mon_status, buttons = menu_group_manage_groups(ctx, chat_id)
    chats = ctx.group_bot_settings["group_chats"]
    chat_list = "".join([f"  №{i+1} {c.get('title', c['link'])[:40]}\n" for i, c in enumerate(chats)]) or f"  {_T(chat_id, 'r2_grp_empty')}\n"
    text = _T(chat_id, 'r2_grp_menu_header').format(
        chan=mon_ch, status=mon_status,
        interval=ctx.group_bot_settings['repost_interval'],
        repeat=ctx.group_bot_settings.get('repost_repeat', 5),
        chats=chat_list
    )
    await ctx.show_nav(chat_id, text, buttons=buttons)


# ================= ОБРОБНИК ТЕКСТОВИХ СТАНІВ =================
async def handle_text_state(ctx, chat_id, state, text, event) -> bool:

    if state == "WAITING_KEYWORDS":
        keywords = [kw.strip() for kw in text.split(",") if kw.strip()]
        ctx.bot_settings["keywords"] = keywords
        kw_display = ", ".join(keywords) if keywords else _T(chat_id, 'r2_kw_empty')
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_kw_ok').format(kw=kw_display))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_accounts_menu(chat_id)
        return True

    if state == "WAITING_STYLE_NAME":
        ctx.user_states[chat_id] = f"WAITING_STYLE_TEXT_{text}"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_style_name_ok').format(name=text))
        return True

    if state == "WAITING_REM_NAME":
        ctx.user_states[chat_id] = f"WAITING_REM_TEXT_{text}"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_rem_name_ok').format(name=text))
        return True

    if state == "WAITING_FOLDER_NAME":
        ctx.user_states[chat_id] = f"WAITING_FOLDER_LINKS_{text}"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_folder_name_ok').format(name=text))
        return True

    if state and state.startswith("WAITING_STYLE_TEXT_"):
        style_name = state.split("WAITING_STYLE_TEXT_", 1)[1]
        ctx.bot_settings["styles"][style_name] = text
        ctx.bot_settings["rules_text"] = text
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_style_saved').format(name=style_name))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_styles_menu(chat_id)
        return True

    if state == "WAITING_DELETE_STYLE":
        if text in ctx.bot_settings["styles"]:
            del ctx.bot_settings["styles"][text]
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_style_deleted'))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_styles_menu(chat_id)
        return True

    if state and state.startswith("WAITING_REM_TEXT_"):
        rem_name = state.split("WAITING_REM_TEXT_", 1)[1]
        ctx.bot_settings["reminders"][rem_name] = text
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_rem_saved'))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_reminders_menu(chat_id)
        return True

    if state == "WAITING_DEL_REM":
        if text in ctx.bot_settings["reminders"]:
            del ctx.bot_settings["reminders"][text]
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_rem_deleted'))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_reminders_menu(chat_id)
        return True

    if state == "WAITING_REM_DELAY":
        if text.isdigit():
            ctx.bot_settings["reminder_delay"] = int(text)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_rem_delay_ok').format(secs=text))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_reminders_menu(chat_id)
        return True

    if state == "WAITING_CYCLE_DELAY":
        if text.isdigit():
            ctx.bot_settings["cycle_delay"] = int(text)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_cycle_delay_ok').format(secs=text))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_cycle_menu(chat_id)
        return True

    if state and state.startswith("WAITING_FOLDER_LINKS_"):
        folder_name = state.split("WAITING_FOLDER_LINKS_", 1)[1]
        links = [l.strip() for l in text.split("\n") if l.strip()]
        ctx.bot_settings["channels"][folder_name] = links
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_folder_saving'))
        await distribute_and_join_all_channels(ctx)
        save_settings(ctx)
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_folder_saved'))
        await asyncio.sleep(1)
        await show_channels_menu(chat_id)
        return True

    if state == "WAITING_DELETE_FOLDER":
        if text in ctx.bot_settings["channels"]:
            links_to_leave = ctx.bot_settings["channels"][text]
            del ctx.bot_settings["channels"][text]
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_folder_deleting'))
            await leave_folder_channels_on_all_accounts(ctx, links_to_leave)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_folder_deleted'))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_channels_menu(chat_id)
        return True

    if state and state.startswith("WAITING_ADD_CHAN_"):
        folder = state.split("WAITING_ADD_CHAN_", 1)[1]
        link = text.strip()
        if folder in ctx.bot_settings["channels"]:
            ctx.bot_settings["channels"][folder].append(link)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_chan_adding'))
            await distribute_and_join_all_channels(ctx)
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_channels_menu(chat_id)
        return True

    if state and state.startswith("WAITING_DEL_CHAN_"):
        folder = state.split("WAITING_DEL_CHAN_", 1)[1]
        link = text.strip()
        if folder in ctx.bot_settings["channels"] and link in ctx.bot_settings["channels"][folder]:
            ctx.bot_settings["channels"][folder].remove(link)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_chan_removing'))
            await leave_channel_on_all_accounts(ctx, link)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_chan_removed'))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_channels_menu(chat_id)
        return True

    # ===== ГРУПА: НАЛАШТУВАННЯ =====
    if state == "G_WAITING_MONITORING_COUNTRY":
        ctx.group_bot_settings["monitoring_country"] = text.strip()
        ctx.user_states[chat_id] = "G_WAITING_MONITORING_LINK"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_mon_country_ok').format(country=text.strip()))
        return True

    if state == "G_WAITING_MONITORING_LINK":
        link = text.strip()
        ctx.group_bot_settings["monitoring_channel"] = link
        ctx.group_bot_settings["monitoring_active"] = False
        ctx.group_bot_settings["monitoring_channel_id"] = None
        if ctx.group_userbots:
            try:
                username = link.split("/")[-1].lstrip("@")
                entity = await ctx.group_userbots[0]["client"].get_entity(username)
                ctx.group_bot_settings["monitoring_channel_id"] = entity.id
                for acc in ctx.group_userbots:
                    _setup_monitoring_on_account(ctx, acc)
                ctx.group_bot_settings["monitoring_active"] = True
                ctx.user_states[chat_id] = None
                save_settings(ctx)
                await ctx.send_and_track(
                    chat_id,
                    _T(chat_id, 'r2_mon_set_ok').format(
                        link=link,
                        country=ctx.group_bot_settings['monitoring_country'],
                        grps=len(ctx.group_bot_settings['group_chats']),
                        interval=ctx.group_bot_settings['repost_interval']
                    ),
                    [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]]
                )
            except Exception as e:
                ctx.user_states[chat_id] = None
                save_settings(ctx)
                await ctx.send_and_track(
                    chat_id,
                    _T(chat_id, 'r2_mon_set_warn').format(e=e),
                    [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]]
                )
        else:
            ctx.user_states[chat_id] = None
            save_settings(ctx)
            await ctx.send_and_track(
                chat_id,
                _T(chat_id, 'r2_mon_set_no_acc'),
                [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]]
            )
        return True

    if state == "G_WAITING_INTERVAL":
        if text.isdigit() and int(text) > 0:
            ctx.group_bot_settings["repost_interval"] = int(text)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_interval_ok').format(secs=text))
        else:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_interval_err'))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_group_manage_menu(chat_id)
        return True

    if state == "G_WAITING_REPEAT":
        if text.isdigit() and int(text) > 0:
            ctx.group_bot_settings["repost_repeat"] = int(text)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_repeat_ok').format(n=text))
        else:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_repeat_err'))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_group_manage_menu(chat_id)
        return True

    if state == "G_WAITING_ADD_GROUP":
        links = [l.strip() for l in text.split("\n") if l.strip()]
        if not links:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_grp_no_link'))
            return True
        ctx.user_states[chat_id] = None
        added = 0
        join_errors = 0
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_grp_processing').format(n=len(links)))
        for link in links:
            existing_links = [c["link"] for c in ctx.group_bot_settings["group_chats"]]
            if link in existing_links:
                continue
            title = link
            chat_id_tg = None
            username = None
            if ctx.group_userbots:
                acc = ctx.group_userbots[0]
                try:
                    if "t.me/+" in link or "t.me/joinchat/" in link:
                        invite_hash = link.split("/")[-1].replace("+", "")
                        result = await acc["client"](ImportChatInviteRequest(invite_hash))
                        if hasattr(result, "chats") and result.chats:
                            entity = result.chats[0]
                            title = entity.title
                            chat_id_tg = entity.id
                        added += 1
                    else:
                        username = link.split("/")[-1].lstrip("@").split("?")[0]
                        try:
                            entity = await acc["client"].get_entity(username)
                            await acc["client"](JoinChannelRequest(entity))
                            title = entity.title
                            chat_id_tg = entity.id
                            added += 1
                        except Exception:
                            title = username
                            join_errors += 1
                    for other_acc in ctx.group_userbots[1:]:
                        try:
                            if "t.me/+" in link or "t.me/joinchat/" in link:
                                inv = link.split("/")[-1].replace("+", "")
                                await other_acc["client"](ImportChatInviteRequest(inv))
                            elif username:
                                e2 = await other_acc["client"].get_entity(username)
                                await other_acc["client"](JoinChannelRequest(e2))
                        except:
                            pass
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"[Add group] {link}: {e}")
                    join_errors += 1
            ctx.group_bot_settings["group_chats"].append({"link": link, "title": title, "id": chat_id_tg})
        summary = _T(chat_id, 'r2_grp_added').format(added=added)
        if join_errors:
            summary += _T(chat_id, 'r2_grp_add_warn').format(n=join_errors)
        save_settings(ctx)
        await ctx.send_and_track(chat_id, summary)
        await asyncio.sleep(1)
        await show_group_manage_menu(chat_id)
        return True

    if state == "G_WAITING_DEL_GROUP":
        ctx.user_states[chat_id] = None
        num_str = ''.join(filter(str.isdigit, text.strip()))
        if num_str:
            idx = int(num_str) - 1
            if 0 <= idx < len(ctx.group_bot_settings["group_chats"]):
                removed = ctx.group_bot_settings["group_chats"].pop(idx)
                await ctx.send_and_track(chat_id, _T(chat_id, 'r2_grp_deleted').format(title=removed.get('title', removed['link'])))
            else:
                await ctx.send_and_track(chat_id, _T(chat_id, 'r2_grp_del_no_num'))
        else:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_grp_enter_num'))
        save_settings(ctx)
        await asyncio.sleep(1)
        await show_group_manage_menu(chat_id)
        return True

    return False


# ================= ОБРОБНИК CALLBACK =================
async def handle_callback(ctx, chat_id, data, event) -> bool:

    if data == b"set_keywords":
        ctx.user_states[chat_id] = "WAITING_KEYWORDS"
        current_kw = ", ".join(ctx.bot_settings["keywords"]) if ctx.bot_settings["keywords"] else _T(chat_id, 'r2_not_set')
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_kw_prompt').format(kw=current_kw))
        return True

    if data == b"bot_status":
        ctx.user_states[chat_id] = None
        text, buttons = menu_bot_status(ctx)
        await ctx.send_and_track(chat_id, text, buttons=buttons)
        return True

    if data == b"bot_enable":
        ctx.bot_settings["bot_enabled"] = True
        save_settings(ctx)
        text, buttons = menu_bot_status(ctx)
        await ctx.clear_chat(chat_id)
        await ctx.send_and_track(chat_id, text, buttons=buttons)
        return True

    if data == b"bot_disable":
        ctx.bot_settings["bot_enabled"] = False
        save_settings(ctx)
        text, buttons = menu_bot_status(ctx)
        await ctx.clear_chat(chat_id)
        await ctx.send_and_track(chat_id, text, buttons=buttons)
        return True

    if data == b"manage_styles":
        await show_styles_menu(chat_id)
        return True

    if data == b"create_style":
        ctx.user_states[chat_id] = "WAITING_STYLE_NAME"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_style_name_prompt'))
        return True

    if data == b"delete_style":
        ctx.user_states[chat_id] = "WAITING_DELETE_STYLE"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_del_name_prompt'))
        return True

    if data and data.startswith(b"view_style_"):
        name = data.replace(b"view_style_", b"").decode()
        if name in ctx.bot_settings["styles"]:
            ctx.bot_settings["rules_text"] = ctx.bot_settings["styles"][name]
            save_settings(ctx)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_style_active').format(name=name))
            await asyncio.sleep(1)
            await show_styles_menu(chat_id)
        return True

    if data == b"manage_reminders":
        await show_reminders_menu(chat_id)
        return True

    if data == b"create_rem":
        ctx.user_states[chat_id] = "WAITING_REM_NAME"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_rem_name_prompt'))
        return True

    if data == b"delete_rem":
        ctx.user_states[chat_id] = "WAITING_DEL_REM"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_del_name_prompt'))
        return True

    if data == b"set_rem_delay":
        ctx.user_states[chat_id] = "WAITING_REM_DELAY"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_delay_prompt'))
        return True

    if data == b"manage_cycle":
        await show_cycle_menu(chat_id)
        return True

    if data == b"set_cycle_delay":
        ctx.user_states[chat_id] = "WAITING_CYCLE_DELAY"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_cycle_delay_prompt'))
        return True

    if data == b"manage_channels":
        await show_channels_menu(chat_id)
        return True

    if data == b"create_folder":
        ctx.user_states[chat_id] = "WAITING_FOLDER_NAME"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_folder_name_prompt'))
        return True

    if data == b"delete_folder":
        ctx.user_states[chat_id] = "WAITING_DELETE_FOLDER"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_del_name_prompt'))
        return True

    if data and data.startswith(b"view_folder_"):
        name = data.replace(b"view_folder_", b"").decode()
        if name in ctx.bot_settings["channels"]:
            links = "\n".join(ctx.bot_settings["channels"][name])
            btns = [
                [Button.inline(_T(chat_id, 'r2_btn_add_chan'), f"add_chan_{name}".encode())],
                [Button.inline(_T(chat_id, 'r2_btn_del_chan'), f"del_chan_{name}".encode())],
                [Button.inline(_T(chat_id, 'r1_btn_back_short'), b"manage_channels")]
            ]
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_folder_view').format(name=name, links=links), buttons=btns)
        return True

    if data and data.startswith(b"add_chan_"):
        name = data.replace(b"add_chan_", b"").decode()
        ctx.user_states[chat_id] = f"WAITING_ADD_CHAN_{name}"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_add_chan_prompt'))
        return True

    if data and data.startswith(b"del_chan_"):
        name = data.replace(b"del_chan_", b"").decode()
        ctx.user_states[chat_id] = f"WAITING_DEL_CHAN_{name}"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_del_chan_prompt'))
        return True

    # ===== ГРУПА =====
    if data == b"g_bot_status":
        ctx.user_states[chat_id] = None
        text, buttons = menu_group_bot_status(ctx)
        await ctx.send_and_track(chat_id, text, buttons=buttons)
        return True

    if data == b"g_bot_enable":
        ctx.group_bot_settings["bot_enabled"] = True
        if ctx.group_bot_settings.get("monitoring_channel_id") and ctx.group_userbots:
            for acc in ctx.group_userbots:
                _setup_monitoring_on_account(ctx, acc)
            ctx.group_bot_settings["monitoring_active"] = True
        save_settings(ctx)
        text, buttons = menu_group_bot_status(ctx)
        await ctx.clear_chat(chat_id)
        await ctx.send_and_track(chat_id, text, buttons=buttons)
        return True

    if data == b"g_bot_disable":
        ctx.group_bot_settings["bot_enabled"] = False
        ctx.group_bot_settings["monitoring_active"] = False
        save_settings(ctx)
        text, buttons = menu_group_bot_status(ctx)
        await ctx.clear_chat(chat_id)
        await ctx.send_and_track(chat_id, text, buttons=buttons)
        return True

    if data == b"g_set_monitoring":
        ctx.user_states[chat_id] = "G_WAITING_MONITORING_COUNTRY"
        current = ctx.group_bot_settings["monitoring_channel"] or _T(chat_id, 'r2_not_set')
        status = _T(chat_id, 'r2_mon_active') if ctx.group_bot_settings["monitoring_active"] else _T(chat_id, 'r2_mon_stopped')
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_mon_prompt').format(chan=current, status=status))
        return True

    if data == b"g_monitoring_stop":
        ctx.group_bot_settings["monitoring_active"] = False
        save_settings(ctx)
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_mon_stopped_msg'), [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]])
        return True

    if data == b"g_monitoring_start":
        if ctx.group_bot_settings["monitoring_channel_id"] and ctx.group_userbots:
            for acc in ctx.group_userbots:
                _setup_monitoring_on_account(ctx, acc)
            ctx.group_bot_settings["monitoring_active"] = True
            save_settings(ctx)
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_mon_started_msg'), [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]])
        else:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_mon_not_ready'), [[Button.inline(_T(chat_id, 'r1_btn_back_acc'), b"g_back_to_accounts")]])
        return True

    if data == b"g_manage_groups":
        await show_group_manage_menu(chat_id)
        return True

    if data == b"g_add_group":
        ctx.user_states[chat_id] = "G_WAITING_ADD_GROUP"
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_add_group_prompt'))
        return True

    if data == b"g_del_group":
        chats = ctx.group_bot_settings["group_chats"]
        if not chats:
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_grp_empty_db'))
            return True
        ctx.user_states[chat_id] = "G_WAITING_DEL_GROUP"
        lst = "\n".join([f"  №{i+1} {c.get('title', c['link'])[:40]}" for i, c in enumerate(chats)])
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_del_group_prompt').format(list=lst))
        return True

    if data and data.startswith(b"g_view_group_"):
        idx_str = data.replace(b"g_view_group_", b"").decode()
        try:
            idx = int(idx_str)
            ch = ctx.group_bot_settings["group_chats"][idx]
            btns = [[Button.inline(_T(chat_id, 'r1_btn_back_short'), b"g_manage_groups")]]
            await ctx.send_and_track(chat_id, _T(chat_id, 'r2_view_group').format(
                n=idx+1, title=ch.get('title', '—'), link=ch['link'], id=ch.get('id', '—')
            ), buttons=btns)
        except:
            await show_group_manage_menu(chat_id)
        return True

    if data == b"g_set_interval":
        ctx.user_states[chat_id] = "G_WAITING_INTERVAL"
        cur = ctx.group_bot_settings.get("repost_interval", 180)
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_interval_prompt').format(cur=cur))
        return True

    if data == b"g_set_repeat":
        ctx.user_states[chat_id] = "G_WAITING_REPEAT"
        cur = ctx.group_bot_settings.get("repost_repeat", 5)
        await ctx.send_and_track(chat_id, _T(chat_id, 'r2_repeat_prompt').format(cur=cur))
        return True

    return False
