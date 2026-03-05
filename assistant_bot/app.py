import os
import threading

from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from assistant_bot.config import CHUTES_API_KEY, TELEGRAM_TOKEN, logger
from assistant_bot.handlers import (
    animate_command,
    clear_command,
    clearimages_command,
    combine_command,
    dream_command,
    edit_command,
    error_handler,
    generate_command,
    handle_message,
    handle_photo,
    imagine_command,
    ltxanimate_command,
    start_command,
    video_cinematic_command,
    video_command,
)


def validate_config() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not found in .env file!")
    if not CHUTES_API_KEY:
        raise ValueError("CHUTES_API_KEY not found in .env file!")


def build_application() -> Application:
    application = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("generate", generate_command))
    application.add_handler(CommandHandler("imagine", imagine_command))
    application.add_handler(CommandHandler("dream", dream_command))
    application.add_handler(CommandHandler("edit", edit_command))
    application.add_handler(CommandHandler("combine", combine_command))
    application.add_handler(CommandHandler("clearimages", clearimages_command))
    application.add_handler(CommandHandler("animate", animate_command))
    application.add_handler(CommandHandler("video", video_command))
    application.add_handler(CommandHandler("video_cinematic", video_cinematic_command))
    application.add_handler(CommandHandler("ltxanimate", ltxanimate_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    async def post_init(app: Application) -> None:
        await app.bot.set_my_commands(
            [
                ("start", "Start the bot"),
                ("clear", "Clear conversation history"),
                ("generate", "Generate image [w h]"),
                ("imagine", "HQ Image [w h] [cfg]"),
                ("dream", "Dream Image [w h] [steps]"),
                ("edit", "Edit Image [w h] [cfg] [steps]"),
                ("combine", "Combine 2-5 images [w h] [cfg]"),
                ("clearimages", "Clear stored images"),
                ("video", "Text-to-Video [res] [steps] [mode]"),
                ("video_cinematic", "Cinematic Video [cam] [res]"),
                ("animate", "Animate Image [frames]"),
                ("ltxanimate", "LTX Animate Image [steps]"),
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

