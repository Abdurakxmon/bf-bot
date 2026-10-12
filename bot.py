import asyncio, html, logging, os, re, sqlite3
from contextlib import suppress

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (CallbackQuery, ChatAdministratorRights, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, KeyboardButtonRequestChat, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)

_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env):
    for line in open(_env, encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"')

TOKEN = os.environ["BOT_TOKEN"]
ADMINS = {int(x) for x in os.environ["ADMIN_IDS"].split(",")}

db = sqlite3.connect(os.path.join(os.path.dirname(_env), "bot.db"))
db.executescript("""
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, channel INTEGER, poster_chat INTEGER, poster_msg INTEGER, button TEXT DEFAULT 'Kanalga qo''shilish');
CREATE TABLE IF NOT EXISTS messages(pos INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT, chat INTEGER, msg INTEGER);
CREATE TABLE IF NOT EXISTS users(id INTEGER, event TEXT, PRIMARY KEY(id, event));
""")
with suppress(sqlite3.OperationalError):  # upgrade older bot.db
    db.execute("ALTER TABLE messages ADD COLUMN kind TEXT")
with suppress(sqlite3.OperationalError):
    db.execute("ALTER TABLE events ADD COLUMN title TEXT")  # channel title, shown in the event picker
db.execute("UPDATE events SET button='Kanalga qo''shilish' WHERE button='Join channel'"); db.commit()

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
admin = Router()
admin.message.filter(F.from_user.id.in_(ADMINS))
admin.callback_query.filter(F.from_user.id.in_(ADMINS))
pending = {}  # admin id -> (action, event)  ponytail: in-memory, lost on restart; just tap the button again


def event(eid):
    return db.execute("SELECT channel, poster_chat, poster_msg, button FROM events WHERE id=?", (eid,)).fetchone()


def one(sql, *args):
    return db.execute(sql, args).fetchone()[0]


# chat action shown while the next welcome message "arrives"
ACTIONS = {"video_note": "upload_video_note", "video": "upload_video", "animation": "upload_video",
           "photo": "upload_photo", "voice": "record_voice", "audio": "upload_voice", "document": "upload_document"}


async def send_welcome(chat_id, eid):
    for chat, msg, kind in db.execute("SELECT chat, msg, kind FROM messages WHERE event=? ORDER BY pos", (eid,)).fetchall():
        with suppress(Exception):
            await bot.send_chat_action(chat_id, ACTIONS.get(kind, "typing"))
        await asyncio.sleep(1.2)
        try:
            await bot.copy_message(chat_id, chat, msg)
        except Exception as e:
            logging.warning("welcome %s/%s failed: %s", chat, msg, e)


async def send_invite(chat_id, eid, url):
    ev = event(eid)
    markup = kb([InlineKeyboardButton(text=ev[3], url=url, style="primary")], [btn("🔄 Havola ishlamayaptimi? Yangisini olish", f"link:{eid}")])
    if ev[1]:
        await bot.copy_message(chat_id, ev[1], ev[2], reply_markup=markup)
    else:
        await bot.send_message(chat_id, "🎟 Shaxsiy taklif havolangiz — faqat siz uchun, bir martalik:", reply_markup=markup)


async def invite(chat_id, uid, eid):
    """Personal one-time link, unless the user is already in the channel."""
    ch = event(eid)[0]
    if not ch:
        return
    with suppress(Exception):
        if (await bot.get_chat_member(ch, uid)).status in ("member", "administrator", "creator"):
            return await bot.send_message(chat_id, "✅ Siz allaqachon kanaldasiz — o'sha yerda ko'rishamiz!")
    try:
        url = (await bot.create_chat_invite_link(ch, member_limit=1, name=f"{eid}:{uid}"[:32])).invite_link
    except Exception as e:
        logging.error("invite link for %s failed: %s", eid, e)
        return await bot.send_message(chat_id, "😕 Hozircha taklif havolasini yaratib bo'lmadi.",
                                      reply_markup=kb([btn("🔄 Qayta urinish", f"link:{eid}", "primary")]))
    await send_invite(chat_id, eid, url)


# ---------- subscribers ----------
@dp.message(CommandStart())
async def start(m: Message, command: CommandObject):
    eid = command.args
    if m.from_user.id in ADMINS and not eid:
        pending.pop(m.from_user.id, None)
        return await m.answer(**home())
    if not event(eid):
        return await m.answer(**await event_menu())
    await enter(m.chat.id, m.from_user.id, eid)


async def enter(chat_id, uid, eid):
    first_time = db.execute("INSERT OR IGNORE INTO users VALUES(?,?)", (uid, eid)).rowcount; db.commit()
    if first_time:  # returning users skip straight to their link
        await send_welcome(chat_id, eid)
    await invite(chat_id, uid, eid)


async def event_menu():
    """Events a user can pick when they open the bot without an event link: only ones with a channel linked."""
    rows = []
    for eid, ch, title in db.execute("SELECT id, channel, title FROM events WHERE channel IS NOT NULL ORDER BY rowid").fetchall():
        if not title:
            with suppress(Exception):
                title = (await bot.get_chat(ch)).title
                db.execute("UPDATE events SET title=? WHERE id=?", (title, eid)); db.commit()
        rows.append([btn(f"🎟 {title or eid}", f"join:{eid}")])
    if not rows:
        return dict(text="😔 Hozircha faol tadbirlar yo'q. Keyinroq qayta urinib ko'ring.")
    return dict(text="👋 Salom! Qaysi tadbirda qatnashmoqchisiz? 👇", reply_markup=kb(*rows))


@dp.callback_query(F.data.startswith("join:"))
async def join(c: CallbackQuery):
    await c.answer()
    if event(eid := c.data[5:]):
        await enter(c.message.chat.id, c.from_user.id, eid)


@dp.callback_query(F.data == "events")
async def events_menu(c: CallbackQuery):
    await c.answer()
    await c.message.answer(**await event_menu())


@dp.callback_query(F.data.startswith("link:"))
async def relink(c: CallbackQuery):
    await c.answer()
    if event(eid := c.data[5:]):
        await invite(c.message.chat.id, c.from_user.id, eid)


@dp.message(F.chat.type == "private", ~F.from_user.id.in_(ADMINS))
async def fallback(m: Message):
    row = db.execute("SELECT event FROM users WHERE id=? ORDER BY rowid DESC LIMIT 1", (m.from_user.id,)).fetchone()
    if row and event(row[0]):
        return await m.answer("Taklif havolangiz kerakmi? 👇", reply_markup=kb([btn("🎟 Taklif havolamni olish", f"link:{row[0]}", "primary")],
                                                                                 [btn("📋 Boshqa tadbirlar", "events")]))
    await m.answer(**await event_menu())


# ---------- admin panel ----------
def btn(text, data, style=None):
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[[b for b in r if b] for r in rows if any(r)])


def steps(eid):
    ch, poster, _, _ = event(eid)
    n = one("SELECT COUNT(*) FROM messages WHERE event=?", eid)
    return n, [(f"Welcome messages ({n})", n > 0, "add"), ("Poster", bool(poster), "pst"), ("Private channel", bool(ch), "chn")]


def home():
    rows = []
    for (eid,) in db.execute("SELECT id FROM events ORDER BY rowid").fetchall():
        done = sum(d for _, d, _ in steps(eid)[1])
        rows.append([btn(f"{'✅' if done == 3 else f'⏳ {done}/3'}  {eid}", f"ev:{eid}")])
    users = one("SELECT COUNT(DISTINCT id) FROM users")
    text = "<b>🎟 Events</b>\nTap an event to manage it." if rows else "<b>🎟 No events yet</b>\nCreate your first one 👇"
    return dict(text=text, reply_markup=kb(*rows, [btn("➕ New event", "new", None if rows else "primary")],
                    [btn(f"📣 Broadcast to all ({users})", "bc:")] if users else []))


async def card(eid):
    _, _, _, button = event(eid)
    n, st = steps(eid)
    done = sum(d for _, d, _ in st)
    nxt = next((key for _, d, key in st if not d), None)
    users = one("SELECT COUNT(*) FROM users WHERE event=?", eid)
    link = f"https://t.me/{(await bot.me()).username}?start={eid}"
    text = (f"📅 <b>{eid}</b>\n🔗 <code>{link}</code>\n👥 {users} users\n\n<b>Setup: {done} of 3</b>\n"
            + "\n".join(f"{'✅' if d else '⬜'} {label}" for label, d, _ in st)
            + f"\n🔘 Button: {html.escape(button)}"
            + ("\n\n🎉 <b>Ready!</b> Share the link above." if done == 3 else ""))
    primary = lambda key: "primary" if key == nxt else None
    return dict(text=text, reply_markup=kb([btn("➕ Add welcome messages", f"add:{eid}", primary("add")), btn("🗑 Clear", f"clr:{eid}") if n else None],
                    [btn("🖼 Poster", f"pst:{eid}", primary("pst")), btn("🔘 Button text", f"btn:{eid}")],
                    [btn("📢 Channel", f"chn:{eid}", primary("chn"))],
                    [btn("👁 Preview", f"pre:{eid}"), btn(f"📣 Broadcast ({users})", f"bc:{eid}")],
                    [btn("« Events", "home"), btn("🗑 Delete", f"del:{eid}")]))


def back(eid):
    return f"ev:{eid}" if eid else "home"


def channel_picker():
    rights = dict.fromkeys(ChatAdministratorRights.model_fields, False) | {"can_invite_users": True}
    pick = KeyboardButton(text="📢 Pick channel", request_chat=KeyboardButtonRequestChat(
        request_id=1, chat_is_channel=True, user_administrator_rights=ChatAdministratorRights(**rights),
        bot_administrator_rights=ChatAdministratorRights(**rights)))
    return ReplyKeyboardMarkup(keyboard=[[pick], [KeyboardButton(text="✖ Cancel")]], resize_keyboard=True, one_time_keyboard=True)


PROMPTS = {
    "add": "Send welcome messages one by one — round video, video, photo, text or a forwarded post.\nThey go out in this order.",
    "pst": "Send the poster: a photo or video with a caption. The join button goes under it.",
    "btn": "Send the text for the join button.",
}


@admin.callback_query()
async def on_button(c: CallbackQuery):
    act, _, eid = c.data.partition(":")
    uid = c.from_user.id
    pending.pop(uid, None)
    await c.answer()
    edit = lambda text, markup=None: c.message.edit_text(text, reply_markup=markup)
    if act not in ("home", "new", "bc", "go") and not event(eid):
        return await c.message.edit_text(**home())
    with suppress(TelegramBadRequest):  # "message is not modified"
        if act == "home":
            await c.message.edit_text(**home())
        elif act == "ev":
            await c.message.edit_text(**await card(eid))
        elif act == "new":
            pending[uid] = ("new", None)
            await edit("Send a short ID for the event — letters, digits, <code>_</code> and <code>-</code>.\n"
                       "It becomes part of the link, e.g. <code>spring24</code>.", kb([btn("✖ Cancel", "home")]))
        elif act in PROMPTS:
            pending[uid] = (act, eid)
            await edit(f"<b>{eid}</b>\n\n{PROMPTS[act]}", kb([btn("✖ Cancel", back(eid))]))
        elif act == "chn":
            pending[uid] = ("chn", eid)
            await c.message.delete()
            await c.message.answer(f"<b>{eid}</b>\n\nTap <b>Pick channel</b> and choose your private channel — "
                                   "I'll be added there as admin automatically.\nOr forward any post from the channel.",
                                   reply_markup=channel_picker())
        elif act == "pre":
            await c.message.answer("👁 <b>Preview</b> — this is what subscribers get (the button is a dummy here):")
            await send_welcome(c.message.chat.id, eid)
            await send_invite(c.message.chat.id, eid, f"https://t.me/{(await bot.me()).username}")
            await c.message.answer(**await card(eid))
        elif act == "bc":
            pending[uid] = ("bc", eid or None)
            who = f"users of <b>{eid}</b>" if eid else "<b>all</b> users"
            await edit(f"📣 Send the message to broadcast to {who}.\nYou'll confirm before it goes out.",
                       kb([btn("✖ Cancel", back(eid))]))
        elif act == "go":
            msg_id, _, eid = eid.partition(":")
            await edit("📣 Sending…")
            asyncio.create_task(broadcast(c.message, int(msg_id), eid or None))
        elif act in ("clr", "del"):
            what = "all welcome messages of" if act == "clr" else "the event"
            await edit(f"Delete {what} <b>{eid}</b>?" + ("\nIts users stay in the bot for broadcasts." if act == "del" else ""),
                       kb([btn("🗑 Yes, delete", f"{act}!:{eid}", "danger"), btn("Cancel", f"ev:{eid}")]))
        elif act == "clr!":
            db.execute("DELETE FROM messages WHERE event=?", (eid,)); db.commit()
            await c.message.edit_text(**await card(eid))
        elif act == "del!":
            db.execute("DELETE FROM messages WHERE event=?", (eid,))
            db.execute("DELETE FROM events WHERE id=?", (eid,)); db.commit()
            await c.message.edit_text(**home())


@admin.message(Command("cancel"))
async def cancel(m: Message):
    pending.pop(m.from_user.id, None)
    await m.answer("Cancelled.", reply_markup=ReplyKeyboardRemove())
    await m.answer(**home())


@admin.message(lambda m: m.from_user.id in pending and not (m.text or "").startswith("/"))
async def capture(m: Message):
    uid = m.from_user.id
    action, eid = pending[uid]
    # ponytail: messages are stored as references to this chat and resent via copy_message — don't delete them here
    if action == "add":
        db.execute("INSERT INTO messages(event, chat, msg, kind) VALUES(?,?,?,?)",
                   (eid, m.chat.id, m.message_id, getattr(m.content_type, "value", m.content_type))); db.commit()
        n = one("SELECT COUNT(*) FROM messages WHERE event=?", eid)
        return await m.reply(f"✅ Saved — {n} total. Send the next one, or tap Done.", reply_markup=kb([btn("Done", f"ev:{eid}", "primary")]))

    if action == "new":
        new = (m.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", new):
            return await m.answer("Only letters, digits, <code>_</code> and <code>-</code>, up to 40 chars. Try again.",
                                  reply_markup=kb([btn("✖ Cancel", "home")]))
        if event(new):
            return await m.answer("That ID is taken. Try another.", reply_markup=kb([btn("✖ Cancel", "home")]))
        db.execute("INSERT INTO events(id) VALUES(?)", (new,)); db.commit()
        pending.pop(uid)
        return await m.answer(**await card(new))

    if action == "pst":
        db.execute("UPDATE events SET poster_chat=?, poster_msg=? WHERE id=?", (m.chat.id, m.message_id, eid)); db.commit()

    elif action == "btn":
        if not m.text:
            return await m.answer("Send plain text for the button.")
        db.execute("UPDATE events SET button=? WHERE id=?", (m.text[:64], eid)); db.commit()

    elif action == "chn":
        if m.text == "✖ Cancel":
            pending.pop(uid)
            await m.answer("Cancelled.", reply_markup=ReplyKeyboardRemove())
            return await m.answer(**await card(eid))
        o = m.forward_origin
        chat_id = m.chat_shared.chat_id if m.chat_shared else o.chat.id if o and o.type == "channel" else None
        if not chat_id:
            return await m.answer("Tap <b>Pick channel</b> below, or forward a post from the channel.")
        try:
            me = await bot.get_chat_member(chat_id, bot.id)
            ok = me.status == "administrator" and me.can_invite_users
        except TelegramBadRequest:
            ok = False
        if not ok:
            return await m.answer("I'm not an admin there with the <b>Invite users</b> right yet. Fix that and try again.")
        db.execute("UPDATE events SET channel=?, title=NULL WHERE id=?", (chat_id, eid)); db.commit()
        await m.answer("📢 Channel linked.", reply_markup=ReplyKeyboardRemove())

    elif action == "bc":
        n = one("SELECT COUNT(DISTINCT id) FROM users" + (" WHERE event=?" if eid else ""), *([eid] if eid else []))
        pending.pop(uid)
        return await m.reply(f"Send this to <b>{n}</b> users?",
                             reply_markup=kb([btn("📣 Send", f"go:{m.message_id}:{eid or ''}", "success"), btn("✖ Cancel", back(eid))]))

    pending.pop(uid)
    await m.answer(**await card(eid))


async def broadcast(status: Message, msg_id, eid):
    ids = [r[0] for r in db.execute("SELECT DISTINCT id FROM users" + (" WHERE event=?" if eid else ""), (eid,) if eid else ())]
    ok = 0
    for i, uid in enumerate(ids, 1):
        try:
            await bot.copy_message(uid, status.chat.id, msg_id); ok += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            with suppress(Exception):
                await bot.copy_message(uid, status.chat.id, msg_id); ok += 1
        except Exception:
            pass  # blocked / deleted account
        if i % 25 == 0:
            with suppress(TelegramBadRequest):
                await status.edit_text(f"📣 Sending… {i} of {len(ids)}")
        await asyncio.sleep(0.05)  # stay under ~20 msg/s
    await status.edit_text(f"✅ Broadcast done: delivered to {ok} of {len(ids)}"
                           + (f" ({len(ids) - ok} blocked the bot)" if ok < len(ids) else "") + ".",
                           reply_markup=kb([btn("« Back", back(eid))]))


dp.include_router(admin)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(dp.start_polling(bot))
