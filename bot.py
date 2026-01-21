import sqlite3
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = "8515071987:AAHCy16_lskoL_rt8TicmTDuILi9c6ybnl0"

GRACE_HOURS = 24
MEDIA_DAYS = 7

WARN_2H = 2
WARN_10M = 10

# --- DB setup ---
conn = sqlite3.connect("activity.db", check_same_thread=False)
c = conn.cursor()
c.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER,
        user_id INTEGER,
        joined_at TEXT,
        last_media_at TEXT,
        warned_2h INTEGER DEFAULT 0,
        warned_10m INTEGER DEFAULT 0,
        PRIMARY KEY (chat_id, user_id)
    )
"""
)
conn.commit()


def now() -> datetime:
    return datetime.utcnow()


# --- Error handler (prevents crash loops) ---
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")


# --- Commands ---
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Send a normal message (safer than reply_text)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ I’m online and watching for photos/videos.",
    )


# --- Join handling ---
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

    # Join/rejoin detection
    joined = (old_status in ("left", "kicked")) and (new_status in ("member", "administrator"))
    if not joined:
        return

    # Reset timer on every join/rejoin (your "YES" choice)
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
        (chat_id, new_user.id, now().isoformat(), None),
    )
    conn.commit()

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"👋 Welcome {new_user.first_name}!\n"
            f"You have **{GRACE_HOURS} hours** to post a **photo or video** or you’ll be removed."
        ),
        parse_mode="Markdown",
    )


# --- Media tracking ---
async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user is None or update.effective_user.is_bot:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Ensure row exists
    c.execute(
        """
        INSERT OR IGNORE INTO users(chat_id, user_id, joined_at, last_media_at, warned_2h, warned_10m)
        VALUES (?,?,?,?,0,0)
        """,
        (chat_id, user_id, now().isoformat(), None),
    )

    # Mark last_media_at now and reset warnings
    c.execute(
        """
        UPDATE users
        SET last_media_at=?, warned_2h=0, warned_10m=0
        WHERE chat_id=? AND user_id=?
        """,
        (now().isoformat(), chat_id, user_id),
    )
    conn.commit()


# --- Periodic enforcement ---
async def sweep(context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT chat_id, user_id, joined_at, last_media_at, warned_2h, warned_10m FROM users")
    rows = c.fetchall()

    for chat_id, user_id, joined_at, last_media_at, warned_2h, warned_10m in rows:
        joined_dt = datetime.fromisoformat(joined_at)
        last_media_dt = datetime.fromisoformat(last_media_at) if last_media_at else None

        elapsed = now() - joined_dt

        # Grace period enforcement (must post media within GRACE_HOURS)
        if elapsed < timedelta(hours=GRACE_HOURS):
            remaining = timedelta(hours=GRACE_HOURS) - elapsed

            # 2-hour warning
            if remaining <= timedelta(hours=WARN_2H) and not warned_2h and last_media_dt is None:
                await context.bot.send_message(
                    chat_id,
                    f"⚠️ <a href='tg://user?id={user_id}'>Warning</a>: "
                    f"Post a photo or video within **2 hours** or you’ll be removed.",
                    parse_mode="HTML",
                )
                c.execute("UPDATE users SET warned_2h=1 WHERE chat_id=? AND user_id=?", (chat_id, user_id))
                conn.commit()

            # 10-min warning
            if remaining <= timedelta(minutes=WARN_10M) and not warned_10m and last_media_dt is None:
                await context.bot.send_message(
                    chat_id,
                    f"🚨 <a href='tg://user?id={user_id}'>Final warning</a>: "
                    f"Post a photo or video in **10 minutes** or you will be removed.",
                    parse_mode="HTML",
                )
                c.execute("UPDATE users SET warned_10m=1 WHERE chat_id=? AND user_id=?", (chat_id, user_id))
                conn.commit()

            continue

        # After grace: remove if still no media
        if last_media_dt is None:
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
                await context.bot.send_message(chat_id, "❌ A user was removed for inactivity (no media posted).")
            except Exception as e:
                print(f"Kick failed: {e}")
            continue

        # Ongoing rule: must post media every MEDIA_DAYS
        if now() - last_media_dt > timedelta(days=MEDIA_DAYS):
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
                await context.bot.send_message(chat_id, "❌ A user was removed for inactivity (no recent media posted).")
            except Exception as e:
                print(f"Kick failed: {e}")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_error_handler(on_error)

    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(ChatMemberHandler(on_member_update, ChatMemberHandler.CHAT_MEMBER))

    # Count more media types so “video note / gif / video file” counts too
    app.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.VIDEO
            | filters.ANIMATION
            | filters.VIDEO_NOTE
            | filters.Document.VIDEO,
            on_media,
        )
    )

    app.job_queue.run_repeating(sweep, interval=300)  # every 5 minutes

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
