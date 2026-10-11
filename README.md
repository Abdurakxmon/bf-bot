# bf-bot

A Telegram bot for events. People arrive from a link on any social network, get your welcome messages, then a personal one-time invite to a private channel.

## How it works

1. You create an event, for example `spring24`, and share its link: `https://t.me/YourBot?start=spring24`.
2. A user opens the link and the bot sends your welcome messages in order: round videos, videos, photos, text or forwarded posts.
3. Then it sends your poster with a button holding an invite link that works **once**, only for that user.
4. Later you can broadcast a message to all users, or only to one event's users.

## Setup

**1. Install Python 3.10+ and the dependency**

```bash
pip install -r requirements.txt
```

**2. Create the bot.** Open [@BotFather](https://t.me/BotFather), send `/newbot` and copy the token.

**3. Find your Telegram user ID.** Open [@userinfobot](https://t.me/userinfobot) and it replies with your ID.

**4. Create `.env`.** Copy `.env.example` to `.env` and fill it in:

```
BOT_TOKEN=123456789:AA...
ADMIN_IDS=111111111
```

For several admins, separate the IDs with commas: `111,222`. Never share or commit `.env`, because anyone with the token controls your bot.

**5. Run**

```bash
python bot.py
```

The bot runs while this window stays open. All data is saved in `bot.db` next to `bot.py`.

## Setting up an event

Send `/start` to your bot as an admin to open the panel.

1. **➕ New event**: send a short ID (letters, digits, `_`, `-`). You get the event link.
2. **➕ Add welcome messages**: send them one by one, then tap **Done**.
3. **🖼 Poster**: send a photo or video with a caption. The join button goes under it.
4. **📢 Channel**: tap **Pick channel** and choose your private channel. Telegram adds the bot there as admin with the invite right.
5. **👁 Preview** shows exactly what users will get.

The event screen shows a setup checklist (*Setup: 2 of 3*). When everything is done it says **Ready**, and you can share the link.

**🔘 Button text** changes the join button's label, and **📣 Broadcast** sends a message to that event's users. Both ask for confirmation first.

## Good to know

- Welcome messages and the poster are re-sent from your chat with the bot. **Don't delete them there**, or users stop receiving them.
- Users who already joined the channel aren't sent a new link. Returning users skip the welcome messages and get only their invite.
- Broadcasts send about 20 messages per second. A large audience takes a few minutes, and the bot shows progress as it goes.
- `/cancel` stops whatever step you're in.
