import os
import threading

from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from assistant_bot.config import GEMINI_API_KEY, TELEGRAM_TOKEN, logger
from assistant_bot.handlers import (
    clear_command,
    error_handler,
    handle_message,
    handle_photo,
    media_disabled_command,
    start_command,
)


def validate_config() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not found in .env file!")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not found in .env file!")


def build_application() -> Application:
    application = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("clear", clear_command))

    # Legacy media commands are intentionally disabled during migration.
    for command in [
        "generate",
        "imagine",
        "dream",
        "edit",
        "combine",
        "clearimages",
        "animate",
        "video",
        "video_cinematic",
        "ltxanimate",
    ]:
        application.add_handler(CommandHandler(command, media_disabled_command))

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    async def post_init(app: Application) -> None:
        await app.bot.set_my_commands(
            [
                ("start", "Start the bot"),
                ("clear", "Clear conversation history"),
            ]
        )

    application.post_init = post_init
    return application


def start_health_server() -> None:
    app = Flask(__name__)

    @app.route("/")
    def home() -> str:
        return "Assistant Bot is running."

    @app.route("/healthz")
    def health_check() -> tuple[str, int]:
        return "OK", 200

    def run_server() -> None:
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    threading.Thread(target=run_server, daemon=True).start()


def main() -> None:
    validate_config()
    application = build_application()
    logger.info("Assistant Bot is online and ready.")
    start_health_server()
    application.run_polling(allowed_updates=Update.ALL_TYPES)
