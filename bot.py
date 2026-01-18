"""
Zara - Your AI Girlfriend Telegram Bot
Using Chutes API for AI responses with conversation memory
"""

import os
import io
import base64
import logging
import httpx
import threading
from flask import Flask
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

# Initialize Chutes API client (OpenAI-compatible)
client = OpenAI(
    api_key=CHUTES_API_KEY,
    base_url="https://llm.chutes.ai/v1"
)

# Conversation memory: {chat_id: [messages]}
conversation_history = defaultdict(list)

# Store user's last uploaded image for editing: {chat_id: base64_string}
user_images = {}

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
    
    # Build messages (no system prompt)
    messages = conversation_history[chat_id]
    
    try:
        response = client.chat.completions.create(
            model="moonshotai/Kimi-K2-Thinking-TEE",
            messages=messages,
            max_tokens=1024,
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


async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /generate command for image generation."""
    chat_id = update.effective_chat.id
    
    # Get the prompt from command arguments
    if not context.args:
        await update.message.reply_text(
            "✨ To generate an image, use:\n"
            "`/generate <your prompt>`\n\n"
            "Example: `/generate a serene sunset over mountains`",
            parse_mode="Markdown"
        )
        return
    
    prompt = " ".join(context.args)
    
    # Show upload photo action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    await update.message.reply_text(f"🎨 Creating your image: *{prompt}*\n\nThis may take a moment...", parse_mode="Markdown")
    
    try:
        # Call Chutes Image API (Z-Image Turbo)
        async with httpx.AsyncClient(timeout=120.0) as http_client:
            response = await http_client.post(
                "https://chutes-z-image-turbo.chutes.ai/generate",
                headers={
                    "Authorization": f"Bearer {CHUTES_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "prompt": prompt
                }
            )
            
            if response.status_code == 200:
                # Send the generated image
                image_data = io.BytesIO(response.content)
                image_data.name = "generated_image.png"
                await update.message.reply_photo(
                    photo=image_data,
                    caption=f"✨ *{prompt}*",
                    parse_mode="Markdown"
                )
            else:
                logger.error(f"Image generation failed: {response.status_code} - {response.text}")
                await update.message.reply_text(
                    "😔 I couldn't generate that image right now. Please try again with a different prompt."
                )
                
    except httpx.TimeoutException:
        await update.message.reply_text(
            "⏳ The image is taking too long to generate. Please try a simpler prompt."
        )
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        await update.message.reply_text(
            "😔 Something went wrong while generating your image. Please try again later."
        )


async def animate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /animate command for image-to-video generation using WAN 2.2."""
    chat_id = update.effective_chat.id
    
    # Check if user has an image stored
    if chat_id not in user_images:
        await update.message.reply_text(
            "📷 To animate an image, first send me a photo, then use:\n"
            "`/animate <motion description>`\n\n"
            "Example: Send a photo, then `/animate she slowly turns her head and smiles`",
            parse_mode="Markdown"
        )
        return
    
    # Get the prompt from command arguments
    prompt = " ".join(context.args) if context.args else "gentle movement and subtle animation"
    
    # Show typing action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")
    await update.message.reply_text(f"🎬 Animating your image: *{prompt}*\n\n⏳ This may take 1-2 minutes...", parse_mode="Markdown")
    
    try:
        # Get raw base64 image
        image_b64 = user_images[chat_id]
        
        # Call WAN 2.2 Image-to-Video API
        async with httpx.AsyncClient(timeout=300.0) as http_client:
            request_body = {
                "seed": None,
                "image": image_b64,
                "prompt": prompt,
                "negative_prompt": "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
            }
            
            logger.info(f"Animate request (image length: {len(image_b64)} chars)")
            
            response = await http_client.post(
                "https://chutes-wan-2-2-i2v-14b-fast.chutes.ai/generate",
                headers={
                    "Authorization": f"Bearer {CHUTES_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=request_body
            )
            
            logger.info(f"Animate response status: {response.status_code}")
            
            if response.status_code == 200:
                # Try to parse as JSON (might contain base64 video)
                try:
                    json_response = response.json()
                    logger.info(f"Animate response keys: {json_response.keys() if isinstance(json_response, dict) else type(json_response)}")
                    
                    # Look for video data in response
                    video_b64 = None
                    for key in ['video', 'video_b64', 'output', 'result', 'data', 'generated_video']:
                        if key in json_response:
                            val = json_response[key]
                            if isinstance(val, str):
                                video_b64 = val
                                break
                            elif isinstance(val, list) and len(val) > 0:
                                video_b64 = val[0]
                                break
                    
                    if video_b64:
                        video_bytes = base64.b64decode(video_b64)
                        video_data = io.BytesIO(video_bytes)
                        video_data.name = "animated_video.mp4"
                        await update.message.reply_video(
                            video=video_data,
                            caption=f"🎬 *{prompt}*",
                            parse_mode="Markdown"
                        )
                    else:
                        logger.error(f"Could not find video in JSON: {json_response}")
                        await update.message.reply_text("😔 Unexpected response format from the API.")
                        
                except Exception:
                    # Raw video bytes
                    logger.info("Response is raw video bytes")
                    video_data = io.BytesIO(response.content)
                    video_data.name = "animated_video.mp4"
                    await update.message.reply_video(
                        video=video_data,
                        caption=f"🎬 *{prompt}*",
                        parse_mode="Markdown"
                    )
            else:
                error_text = response.text[:500] if len(response.text) > 500 else response.text
                logger.error(f"Animation failed: {response.status_code} - {error_text}")
                await update.message.reply_text(
                    f"😔 Animation failed. Error: {response.status_code}\n{error_text[:200]}"
                )
                
    except httpx.TimeoutException:
        await update.message.reply_text(
            "⏳ The animation is taking too long. Please try again."
        )
    except Exception as e:
        logger.error(f"Animation error: {e}")
        await update.message.reply_text(
            "😔 Something went wrong while animating your image. Please try again later."
        )
# ==================== END WAN 2.2 I2V ====================


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos and store them for editing."""
    chat_id = update.effective_chat.id
    
    # Get the largest photo size
    photo = update.message.photo[-1]
    
    try:
        # Download the photo
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        
        # Convert to base64
        photo_b64 = base64.b64encode(photo_bytes).decode('utf-8')
        
        # Store for later editing
        user_images[chat_id] = photo_b64
        
        await update.message.reply_text(
            "📸 Image received! You can now edit it using:\n"
            "`/edit <your prompt>`\n\n"
            "Example: `/edit make the sky purple`",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Photo handling error: {e}")
        await update.message.reply_text(
            "😔 I couldn't process that image. Please try sending it again."
        )


async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /edit command for image editing."""
    chat_id = update.effective_chat.id
    
    # Check if user has an image stored
    if chat_id not in user_images:
        await update.message.reply_text(
            "📷 To edit an image, first send me a photo, then use:\n"
            "`/edit <your prompt>`\n\n"
            "Example: Send a photo, then `/edit make it look like a painting`",
            parse_mode="Markdown"
        )
        return
    
    # Get the prompt from command arguments
    if not context.args:
        await update.message.reply_text(
            "✨ To edit your image, use:\n"
            "`/edit <your prompt>`\n\n"
            "Example: `/edit add sunglasses`",
            parse_mode="Markdown"
        )
        return
    
    prompt = " ".join(context.args)
    
    # Show upload photo action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    await update.message.reply_text(f"🎨 Editing your image: *{prompt}*\n\nThis may take a moment...", parse_mode="Markdown")
    
    try:
        # Call Chutes Qwen Image Edit API
        async with httpx.AsyncClient(timeout=120.0) as http_client:
            response = await http_client.post(
                "https://chutes-qwen-image-edit-2511.chutes.ai/generate",
                headers={
                    "Authorization": f"Bearer {CHUTES_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "seed": None,
                    "width": 1024,
                    "height": 1024,
                    "prompt": prompt,
                    "image_b64s": [user_images[chat_id]],
                    "true_cfg_scale": 4,
                    "negative_prompt": "",
                    "num_inference_steps": 40
                }
            )
            
            if response.status_code == 200:
                # Try to parse as JSON first (API may return base64 in JSON)
                try:
                    json_response = response.json()
                    logger.info(f"Image edit JSON response keys: {json_response.keys() if isinstance(json_response, dict) else type(json_response)}")
                    
                    # Handle different possible JSON response formats
                    if isinstance(json_response, dict):
                        # Try common keys for base64 image data
                        image_b64 = None
                        for key in ['image', 'images', 'output', 'result', 'data', 'image_b64', 'generated_image']:
                            if key in json_response:
                                val = json_response[key]
                                if isinstance(val, str):
                                    image_b64 = val
                                    break
                                elif isinstance(val, list) and len(val) > 0:
                                    image_b64 = val[0]
                                    break
                        
                        if image_b64:
                            # Decode base64 to bytes
                            image_bytes = base64.b64decode(image_b64)
                            image_data = io.BytesIO(image_bytes)
                            image_data.name = "edited_image.png"
                            await update.message.reply_photo(
                                photo=image_data,
                                caption=f"✨ Edited: *{prompt}*",
                                parse_mode="Markdown"
                            )
                            # Store for further edits
                            user_images[chat_id] = image_b64
                        else:
                            logger.error(f"Could not find image in JSON response: {json_response}")
                            await update.message.reply_text("😔 Unexpected response format from the API.")
                    else:
                        logger.error(f"Unexpected JSON type: {type(json_response)}")
                        await update.message.reply_text("😔 Unexpected response format from the API.")
                        
                except Exception as json_err:
                    # Not JSON, try as raw image bytes
                    logger.info(f"Response is not JSON, treating as raw image. Error: {json_err}")
                    image_data = io.BytesIO(response.content)
                    image_data.name = "edited_image.png"
                    await update.message.reply_photo(
                        photo=image_data,
                        caption=f"✨ Edited: *{prompt}*",
                        parse_mode="Markdown"
                    )
                    # Store the edited image for further edits
                    edited_b64 = base64.b64encode(response.content).decode('utf-8')
                    user_images[chat_id] = edited_b64
                
            else:
                logger.error(f"Image edit failed: {response.status_code} - {response.text}")
                await update.message.reply_text(
                    f"😔 I couldn't edit that image. Error: {response.status_code}"
                )
                
    except httpx.TimeoutException:
        await update.message.reply_text(
            "⏳ The image edit is taking too long. Please try a simpler prompt."
        )
    except Exception as e:
        logger.error(f"Image edit error: {e}")
        await update.message.reply_text(
            "😔 Something went wrong while editing your image. Please try again later."
        )


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
    application.add_handler(CommandHandler("generate", generate_command))
    application.add_handler(CommandHandler("edit", edit_command))
    application.add_handler(CommandHandler("animate", animate_command))  # WAN 2.2 Image-to-Video
    # application.add_handler(CommandHandler("video", video_command))  # Text-to-video (model cold)
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start polling
    logger.info("Zara is online and ready to chat! 💕")
    
    # Start dummy web server for port binding (Render/Heroku/etc)
    app = Flask(__name__)

    @app.route('/')
    def home():
        return "Zara Bot is running! 🌿"

    @app.route('/healthz')
    def health_check():
        return "OK", 200

    def run_server():
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port)

    # Run server in a separate thread
    threading.Thread(target=run_server, daemon=True).start()
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()