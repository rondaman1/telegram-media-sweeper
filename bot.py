import sqlite3
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

TOKEN = "8515071987:AAHCy16_lskoL_rt8TicmTDuILi9c6ybnl0"

GRACE_HOURS = 24
MEDIA_DAYS = 7

# Warning times before GRACE ends (only applies if they still haven't posted media)
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

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ I’m online and watching for photos/videos.")

async def on_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fires for member status changes. We'll treat "joined/added" as a join.
    """
    cu = update.chat_member
    if not cu:
        return

    chat_id = cu.chat.id
    new_user = cu.new_chat_member.user

    # Ignore bots
    if new_user.is_bot:
        return

    # Detect join/add: status became member/administrator from left/kicked
    old_status = cu.old_chat_member.status
    new_status = cu.new_chat_member.status

    joined = (old_status in ("left", "kicked")) and (new_status in ("member", "administrator"))
    if not joined:
        return

    c.execute(
        "INSERT OR REPLACE INTO users VALUES (?,?,?,?,0,0)",
        (chat_id, new_user.id, now().isoformat(), None)
    )
    conn.commit()

    await context.bot.send_message(
        chat_id,
        f"👋 Welcome {new_user.first_name}!\n"
        f"You have **{GRACE_HOURS} hours** to post a **photo or video** or you’ll be removed.",
        parse_mode="Markdown"
    )

async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or update.effective_user.is_bot:
        return

    c.execute(
        """INSERT OR IGNORE INTO users(chat_id, user_id, joined_at, last_media_at, warned_2h, warned_10m)
           VALUES (?,?,?,?,0,0)""",
        (update.effective_chat.id, update.effective_user.id, now().isoformat(), None)
    )

    c.execute(
        """UPDATE users
           SET last_media_at=?, warned_2h=0, warned_10m=0
           WHERE chat_id=? AND user_id=?""",
        (now().isoformat(), update.effective_chat.id, update.effective_user.id)
    )
    conn.commit()

async def sweep(context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT chat_id, user_id, joined_at, last_media_at, warned_2h, warned_10m FROM users")
    rows = c.fetchall()

    for chat_id, user_id, joined, last_media, w2h, w10m in rows:
        joined_dt = datetime.fromisoformat(joined)
        last_media_dt = datetime.fromisoformat(last_media) if last_media else None

        elapsed = now() - joined_dt

        # Still in grace period
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
                conn.commit()

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

        # After grace: enforce ongoing media rule
        if (last_media_dt is None) or (now() - last_media_dt > timedelta(days=MEDIA_DAYS)):
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
                await context.bot.send_message(chat_id, "❌ A user was removed for inactivity (no media posted).")
            except:
                pass

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # A simple test command
    app.add_handler(CommandHandler("ping", ping))

    # Member updates (joins/leaves)
    app.add_handler(ChatMemberHandler(on_member_update, ChatMemberHandler.CHAT_MEMBER))

    # Media tracking
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, on_media))

    # Run checks every 5 minutes
    app.job_queue.run_repeating(sweep, interval=300)

    # Make sure we receive member updates too
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
