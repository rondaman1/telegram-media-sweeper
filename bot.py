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
c.execute(
    """
    INSERT INTO users (chat_id, user_id, joined_at, last_media_at, warned_2h, warned_10m)
    VALUES (?,?,?,?,0,0)
    ON CONFLICT(chat_id, user_id)
    DO UPDATE SET
        joined_at=excluded.joined_at,
        last_media_at=NULL,
        warned_2h=0,
        warned_10m=0
    """,
    (chat_id, new_user.id, now().isoformat(), None)
)
conn.commit()

def now():
    return datetime.utcnow()

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ I’m online and watching for photos/videos."
    )
async def on_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cu = update.chat_member
    if not cu:
        return

    chat_id = cu.chat.id
    new_user = cu.new_chat_member.user

    if new_user.is_bot:
        return

    old_status = cu.old_chat_member.status
    new_status = cu.new_chat_member.status

    joined = (old_status in ("left", "kicked")) and (new_status in ("member", "administrator"))
    if not joined:
        return


    c.execute(
        """
        INSERT INTO users (chat_id, user_id, joined_at, last_media_at, warned_2h, warned_10m)
        VALUES (?,?,?,?,0,0)
        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            joined_at=excluded.joined_at,
            last_media_at=NULL,
            warned_2h=0,
            warned_10m=0
        """,
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
        ...
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.unban_chat_member(chat_id, user_id)
            await context.bot.send_message(chat_id, "❌ A user was removed for inactivity (no media posted).")
        except:
            pass
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(ChatMemberHandler(on_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, on_media))

    app.job_queue.run_repeating(sweep, interval=300)

    app.add_error_handler(on_error)    

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
