import html
import re
import time

from telegram import Update
from telegram.ext import ContextTypes

from assistant_bot.config import logger
from assistant_bot.services import get_ai_response_with_stream
from assistant_bot.state import conversation_history


_ALLOWED_HTML_TAGS = ("b", "strong", "i", "em", "u", "s", "code", "pre")


def _restore_allowed_html_tags(escaped_text: str) -> str:
    restored = escaped_text
    for tag in _ALLOWED_HTML_TAGS:
        restored = re.sub(fr"&lt;{tag}&gt;", f"<{tag}>", restored, flags=re.IGNORECASE)
        restored = re.sub(fr"&lt;/{tag}&gt;", f"</{tag}>", restored, flags=re.IGNORECASE)

    restored = re.sub(r"&lt;br\s*/?&gt;", "<br>", restored, flags=re.IGNORECASE)
    return restored


def _to_telegram_html(text: str) -> str:
    """Escape text for HTML parse mode and allow a safe subset of formatting tags."""
    escaped = html.escape(text or "", quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=re.DOTALL)
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    return _restore_allowed_html_tags(escaped)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []

    welcome_message = (
        "Hello.\n\n"
        "This bot now uses Google Gemini for text responses. "
        "Image and video generation commands are currently disabled.\n\n"
        "Use /clear to reset conversation history."
    )
    await update.message.reply_text(welcome_message)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command to reset conversation history."""
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("Conversation history cleared.")


async def media_disabled_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inform users that media generation is disabled."""
    await update.message.reply_text(
        "Image/video generation is disabled while migrating from Chutes to Google Gemini."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo uploads while media features are disabled."""
    await update.message.reply_text(
        "Photo processing is currently disabled while migrating from Chutes to Google Gemini."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages by editing a single response message while streaming."""
    chat_id = update.effective_chat.id
    user_message = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    response_message = await update.message.reply_text("Thinking...")
    last_sent_len = 0
    last_sent_at = 0.0
    edit_failed = False

    async def on_partial(partial_text: str) -> None:
        nonlocal last_sent_len, last_sent_at, edit_failed

        if edit_failed:
            return

        text = partial_text.strip()
        if not text:
            return

        now = time.monotonic()
        if len(text) - last_sent_len < 24 and (now - last_sent_at) < 0.8:
            return

        try:
            await response_message.edit_text(text[:4096])
            last_sent_len = len(text)
            last_sent_at = now
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return
            logger.warning("Streaming edit failed: %s", exc)
            edit_failed = True

    response = await get_ai_response_with_stream(chat_id, user_message, on_partial=on_partial)
    final_text_raw = (response or "I could not generate a response. Please try again.")[:4096]
    final_text_html = _to_telegram_html(final_text_raw)

    try:
        await response_message.edit_text(final_text_html, parse_mode="HTML")
    except Exception as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Final edit failed: %s", exc)
            await update.message.reply_text(final_text_raw)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors with user-friendly messages."""
    error = context.error
    logger.error("Error occurred: %s", error)

    if update and update.effective_message:
        try:
            error_name = type(error).__name__
            if "Timeout" in error_name or "TimeoutError" in error_name:
                msg = "The request timed out. Please try again."
            elif "NetworkError" in error_name or "ConnectionError" in error_name:
                msg = "Network error. Please check your connection and try again."
            elif "BadRequest" in error_name:
                msg = "Invalid request. Please check your input and try again."
            elif "Forbidden" in error_name:
                msg = "Access denied. The bot may not have permission for this action."
            elif "Conflict" in error_name:
                msg = "Another request is in progress. Please wait a moment."
            else:
                msg = "Something went wrong. Please try again later."

            await update.effective_message.reply_text(msg)
        except Exception:
            pass
