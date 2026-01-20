import time
import sqlite3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ChatMemberHandler, ContextTypes, filters

TOKEN = "8515071987:AAHdbbOU"

GRACE_HOURS = 24
MEDIA_DAYS = 7

conn = sqlite3.connect("activity.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER,
    user_id INTEGER,
    joined_at TEXT,
    last_media_at TEXT,
    PRIMARY KEY (chat_id, user_id)
)
""")
conn.commit()

def now():
    return datetime.utcnow()

async def on_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member = update.chat_member.new_chat_member
    if member.user.is_bot:
        return
    c.execute(
        "INSERT OR IGNORE INTO users VALUES (?,?,?,?)",
        (update.chat_member.chat.id, member.user.id, now().isoformat(), None)
    )
    conn.commit()

async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.is_bot:
        return
    c.execute(
        "UPDATE users SET last_media_at=? WHERE chat_id=? AND user_id=?",
        (now().isoformat(), update.effective_chat.id, update.effective_user.id)
    )
    conn.commit()

async def sweep(context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT chat_id, user_id, joined_at, last_media_at FROM users")
    for chat_id, user_id, joined, last_media in c.fetchall():
        joined = datetime.fromisoformat(joined)
        last_media = datetime.fromisoformat(last_media) if last_media else None

        if now() - joined < timedelta(hours=GRACE_HOURS):
            continue

        if not last_media or now() - last_media > timedelta(days=MEDIA_DAYS):
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
            except:
                pass

async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(ChatMemberHandler(on_join, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, on_media))
    app.job_queue.run_repeating(sweep, interval=3600)
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
