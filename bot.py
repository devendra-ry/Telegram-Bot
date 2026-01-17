"""
Zara - Your AI Girlfriend Telegram Bot
Using Chutes API for AI responses with conversation memory
"""

import os
import logging
from collections import defaultdict
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHUTES_API_KEY = os.getenv("CHUTES_API_KEY")
BOT_PERSONALITY = os.getenv("BOT_PERSONALITY")

# Initialize Chutes API client (OpenAI-compatible)
client = OpenAI(
    api_key=CHUTES_API_KEY,
    base_url="https://llm.chutes.ai/v1"
)

# Conversation memory: {chat_id: [messages]}
conversation_history = defaultdict(list)

# Maximum messages to keep in history (to avoid token limits)
MAX_HISTORY = 40


def get_ai_response(chat_id: int, user_message: str) -> str:
    """Get AI response from Chutes API with conversation history."""
    
    # Add user message to history
    conversation_history[chat_id].append({
        "role": "user",
        "content": user_message
    })
    
    # Trim history if too long
    if len(conversation_history[chat_id]) > MAX_HISTORY:
        conversation_history[chat_id] = conversation_history[chat_id][-MAX_HISTORY:]
    
    # Build messages with system prompt
    messages = [
        {"role": "system", "content": BOT_PERSONALITY}
    ] + conversation_history[chat_id]
    
    try:
        response = client.chat.completions.create(
            model="moonshotai/Kimi-K2-Thinking-TEE",
            messages=messages,
            max_tokens=500,
            temperature=0.8
        )
        
        assistant_message = response.choices[0].message.content
        
        # Add assistant response to history
        conversation_history[chat_id].append({
            "role": "assistant",
            "content": assistant_message
        })
        
        return assistant_message
        
    except Exception as e:
        logger.error(f"Chutes API error: {e}")
        return "I apologize, I'm experiencing a brief interruption. Could you please try again in a moment?"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []  # Clear history on start
    
    welcome_message = (
        "Hello, and welcome. 🌿\n\n"
        "I'm Zara, and I'm here to listen and support you. "
        "This is a safe space where you can share whatever is on your mind.\n\n"
        "Feel free to talk about anything - I'm here for you.\n"
        "Use /clear anytime to start a fresh conversation."
    )
    await update.message.reply_text(welcome_message)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command to reset conversation history."""
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("I've cleared our conversation history. 🌿 Whenever you're ready, I'm here to listen.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    chat_id = update.effective_chat.id
    user_message = update.message.text
    
    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Get AI response
    response = get_ai_response(chat_id, user_message)
    
    await update.message.reply_text(response)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")


def main() -> None:
    """Start the bot."""
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not found in .env file!")
    if not CHUTES_API_KEY:
        raise ValueError("CHUTES_API_KEY not found in .env file!")
    
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start polling
    logger.info("Zara is online and ready to chat! 💕")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()