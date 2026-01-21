import sqlite3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ChatMemberHandler, ContextTypes, filters

TOKEN = "8515071987:AAHdbbOU"

GRACE_HOURS = 24
MEDIA_DAYS = 7
WARN_2H = 2
WARN_10M = 10

conn = sqlite3.connect("activity.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER,
    user_id INTEGER,
    joined_at TEXT,
    last_media_at TEXT,
    warned_2h INTEGER DEFAULT 0,
    warned_10m INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
)
""")
conn.commit()

def now():
    return datetime.utcnow()

async def on_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.chat_member.new_chat_member
    if m.user.is_bot:
        return

    chat_id = update.chat_member.chat.id
    user_id = m.user.id

    c.execute(
        "INSERT OR REPLACE INTO users VALUES (?,?,?,?,0,0)",
        (chat_id, user_id, now().isoformat(), None)
    )
    conn.commit()

    await context.bot.send_message(
        chat_id,
        f"👋 Welcome {m.user.first_name}!\n"
        f"You have **24 hours** to post a **photo or video** or you’ll be removed.",
        parse_mode="Markdown"
    )

async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.is_bot:
        return

    c.execute(
        """UPDATE users 
           SET last_media_at=?, warned_2h=0, warned_10m=0 
           WHERE chat_id=? AND user_id=?""",
        (now().isoformat(), update.effective_chat.id, update.effective_user.id)
    )
    conn.commit()

async def sweep(context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT * FROM users")
    for chat_id, user_id, joined, last_media, w2h, w10m in c.fetchall():
        joined = datetime.fromisoformat(joined)
        last_media = datetime.fromisoformat(last_media) if last_media else None

        elapsed = now() - joined

        if elapsed < timedelta(hours=GRACE_HOURS):
            remaining = timedelta(hours=GRACE_HOURS) - elapsed

            if remaining <= timedelta(hours=WARN_2H) and not w2h:
                await context.bot.send_message(
                    chat_id,
                    f"⚠️ <a href='tg://user?id={user_id}'>Warning</a>: "
                    f"Post a photo or video within **2 hours** or you’ll be removed.",
                    parse_mode="HTML"
                )
                c.execute("UPDATE users SET warned_2h=1 WHERE chat_id=? AND user_id=?", (chat_id, user_id))

            if remaining <= timedelta(minutes=WARN_10M) and not w10m:
                await context.bot.send_message(
                    chat_id,
                    f"🚨 <a href='tg://user?id={user_id}'>Final warning</a>: "
                    f"Post a photo or video in **10 minutes** or you will be removed.",
                    parse_mode="HTML"
                )
                c.execute("UPDATE users SET warned_10m=1 WHERE chat_id=? AND user_id=?", (chat_id, user_id))

            conn.commit()
            continue

        if not last_media or now() - last_media > timedelta(days=MEDIA_DAYS):
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
                await context.bot.send_message(
                    chat_id,
                    "❌ A user was removed for inactivity (no media posted)."
                )
            except:
                pass

async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(ChatMemberHandler(on_join, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, on_media))
    app.job_queue.run_repeating(sweep, interval=300)  # every 5 minutes
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
