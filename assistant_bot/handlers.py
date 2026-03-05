import random
import time

from telegram import Update
from telegram.ext import ContextTypes

from assistant_bot.config import logger
from assistant_bot.services import get_ai_response_with_stream, send_message_draft
from assistant_bot.state import conversation_history


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
    """Handle incoming text messages with streamed Gemini responses."""
    chat_id = update.effective_chat.id
    user_message = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    effective_message = update.effective_message
    chat_type = update.effective_chat.type if update.effective_chat else ""
    use_draft_stream = chat_type == "private"
    draft_enabled = True

    draft_id = (
        effective_message.message_id
        if effective_message and effective_message.message_id
        else random.randint(1, 2_147_483_647)
    )
    message_thread_id = getattr(effective_message, "message_thread_id", None)
    last_sent_len = 0
    last_sent_at = 0.0

    async def on_partial(partial_text: str) -> None:
        nonlocal draft_enabled, last_sent_len, last_sent_at

        if not use_draft_stream or not draft_enabled:
            return

        text = partial_text.strip()
        if not text:
            return

        now = time.monotonic()
        if len(text) - last_sent_len < 24 and (now - last_sent_at) < 0.8:
            return

        ok = await send_message_draft(
            chat_id=chat_id,
            draft_id=draft_id,
            text=text,
            message_thread_id=message_thread_id,
        )
        if ok:
            last_sent_len = len(text)
            last_sent_at = now
        else:
            draft_enabled = False

    response = await get_ai_response_with_stream(chat_id, user_message, on_partial=on_partial)
    await update.message.reply_text(response)


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
