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
from openai import AsyncOpenAI
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

# Initialize Chutes API client (OpenAI-compatible) - Using AsyncOpenAI for concurrent request handling
client = AsyncOpenAI(
    api_key=CHUTES_API_KEY,
    base_url="https://llm.chutes.ai/v1"
)

# Conversation memory: {chat_id: [messages]}
conversation_history = defaultdict(list)
MAX_HISTORY = 20  # Keep last 20 messages per user

# LTX-2 Resolution mapping (all must be divisible by 64)
RES_MAP = {
    "sd": (768, 512),      # Standard definition
    "hd": (1280, 768),     # High definition (fixed from 720)
    "fhd": (1920, 1088)    # Full HD
}

# Camera LoRAs for LTX-2
CAMERA_LORAS = [
    "camera-dolly-in",
    "camera-dolly-out",
    "camera-dolly-left",
    "camera-dolly-right",
    "camera-jib-up",
    "camera-jib-down",
    "camera-static"
]

# User uploaded images: {chat_id: image_b64}
# User uploaded images: {chat_id: [list of image_b64 strings]}
user_images = {}

# Maximum messages to keep in history (to avoid token limits)
# MAX_HISTORY = 40


async def get_ai_response(chat_id: int, user_message: str) -> str:
    """Get AI response from Chutes API with conversation history (async)."""
    
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
        response = await client.chat.completions.create(
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
    """Handle /generate command for fast image generation (Z-Image-Turbo)."""
    chat_id = update.effective_chat.id
    
    # Get the prompt from command arguments
    if not context.args:
        await update.message.reply_text(
            "✨ To generate an image, use:\n"
            "`/generate [width height] <prompt>`\n\n"
            "**Examples:**\n"
            "`/generate a sunset over mountains`\n"
            "`/generate 1920 1080 a wide landscape`\n\n"
            "Default: 1024×1024 (range: 576-2048)",
            parse_mode="Markdown"
        )
        return
    
    args = list(context.args)
    width = 1024  # default
    height = 1024  # default
    
    # Check if first two args are dimensions
    if len(args) >= 3 and args[0].isdigit() and args[1].isdigit():
        width = max(576, min(2048, int(args[0])))
        height = max(576, min(2048, int(args[1])))
        args = args[2:]
    
    if not args:
        await update.message.reply_text("Please provide a prompt.")
        return
    
    prompt = " ".join(args)
    
    # Show upload photo action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    
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
                    "prompt": prompt,
                    "height": height,
                    "width": width,
                    "num_inference_steps": 9,
                    "guidance_scale": 0.0,
                    "shift": 3.0
                }
            )
            
            if response.status_code == 200:
                # Send the generated image
                image_data = io.BytesIO(response.content)
                image_data.name = "generated_image.png"
                await update.message.reply_photo(photo=image_data)
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



async def imagine_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /imagine command for high-quality image generation (Qwen-Image-2512)."""
    chat_id = update.effective_chat.id
    
    # Get the prompt from command arguments
    if not context.args:
        await update.message.reply_text(
            "🎨 To generate a high-quality image, use:\n"
            "`/imagine [width height] [cfg=X] <prompt>`\n\n"
            "**Examples:**\n"
            "`/imagine a sunset over mountains`\n"
            "`/imagine 1920 1080 a wide landscape`\n"
            "`/imagine cfg=6 a detailed portrait`\n\n"
            "Default: 1328×1328, cfg=4 (range: 128-2048, cfg: 0-10)",
            parse_mode="Markdown"
        )
        return
    
    args = list(context.args)
    width = 1328  # default
    height = 1328  # default
    cfg_scale = 4.0  # default
    negative_prompt = ""
    
    # Check if first two args are dimensions
    if len(args) >= 3 and args[0].isdigit() and args[1].isdigit():
        width = max(128, min(2048, int(args[0])))
        height = max(128, min(2048, int(args[1])))
        args = args[2:]
    
    # Check for cfg=X parameter
    new_args = []
    for arg in args:
        if arg.lower().startswith("cfg="):
            try:
                cfg_scale = max(0.0, min(10.0, float(arg[4:])))
            except ValueError:
                pass
        elif arg.lower().startswith("neg="):
            negative_prompt = arg[4:]
        else:
            new_args.append(arg)
    args = new_args
    
    if not args:
        await update.message.reply_text("Please provide a prompt.")
        return
    
    prompt = " ".join(args)
    
    # Show typing action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    
    try:
        # Call Qwen-Image-2512 API
        async with httpx.AsyncClient(timeout=180.0) as http_client:
            request_body = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "height": height,
                "width": width,
                "num_inference_steps": 50,
                "true_cfg_scale": cfg_scale
            }
            
            logger.info(f"Imagine request: {prompt[:50]}...")
            
            response = await http_client.post(
                "https://chutes-qwen-image-2512.chutes.ai/generate",
                headers={
                    "Authorization": f"Bearer {CHUTES_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=request_body
            )
            
            if response.status_code == 200:
                # Send the generated image
                image_data = io.BytesIO(response.content)
                image_data.name = "imagine.jpg"
                await update.message.reply_photo(photo=image_data)
            else:
                logger.error(f"Imagine failed: {response.status_code} - {response.text[:300]}")
                await update.message.reply_text(
                    f"😔 Image generation failed. Error: {response.status_code}"
                )
                
    except httpx.TimeoutException:
        await update.message.reply_text(
            "⏳ Image generation timed out. Please try again."
        )
    except Exception as e:
        logger.error(f"Imagine error: {e}")
        await update.message.reply_text(
            "😔 Something went wrong. Please try again later."
        )




async def animate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /animate command for image-to-video generation (WAN 2.2)."""
    chat_id = update.effective_chat.id
    message = update.message or update.edited_message  # Handle edited messages
    
    # Check if user has an image stored
    if chat_id not in user_images or len(user_images[chat_id]) == 0:
        await message.reply_text(
            "📷 To animate an image, first send me a photo, then use:\n"
            "`/animate [frames=X] <motion description>`\n\n"
            "**Options:**\n"
            "🎞️ `frames=` 21-140 (default: 140)\n\n"
            "**Examples:**\n"
            "`/animate she slowly turns her head`\n"
            "`/animate frames=120 dancing motion`",
            parse_mode="Markdown"
        )
        return
    
    args = list(context.args) if context.args else []
    frames = 81  # default (81 frames = WAN 2.2 optimal context window @ 16fps)
    
    # Parse optional parameters
    new_args = []
    for arg in args:
        if arg.lower().startswith("frames="):
            try:
                frames = max(21, min(140, int(arg[7:])))
            except ValueError:
                pass
        else:
            new_args.append(arg)
    args = new_args
    
    prompt = " ".join(args) if args else "gentle movement and subtle animation"
    
    # Show typing action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")
    
    try:
        # Get raw base64 image (use latest)
        image_b64 = user_images[chat_id][-1]
        
        # Call WAN 2.2 Image-to-Video API (10 min timeout for high frame counts)
        async with httpx.AsyncClient(timeout=600.0) as http_client:
            request_body = {
                "seed": None,
                "image": image_b64,
                "prompt": prompt,
                "negative_prompt": "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
            }
            
            # Configure API parameters to match WAN 2.2 specification
            request_body["resolution"] = "720p"
            request_body["frames"] = frames
            request_body["fps"] = 16  # WAN 2.2 14B native frame rate
            request_body["fast"] = False  # Standard quality mode (9 inference steps)
            request_body["guidance_scale"] = 1.0  # API default
            request_body["guidance_scale_2"] = 1.0  # API default

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
                        await message.reply_video(video=video_data)
                    else:
                        logger.error(f"Could not find video in JSON: {json_response}")
                        await message.reply_text("😔 Unexpected response format from the API.")
                        
                except Exception:
                    # Raw video bytes
                    logger.info("Response is raw video bytes")
                    video_data = io.BytesIO(response.content)
                    video_data.name = "animated_video.mp4"
                    await message.reply_video(video=video_data)
            else:
                error_text = response.text[:500] if len(response.text) > 500 else response.text
                logger.error(f"Animation failed: {response.status_code} - {error_text}")
                await message.reply_text(
                    f"😔 Animation failed. Error: {response.status_code}\n{error_text[:200]}"
                )
                
    except httpx.TimeoutException:
        await message.reply_text(
            "⏳ The animation is taking too long. Please try again."
        )
    except Exception as e:
        logger.error(f"Animation error: {type(e).__name__}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await message.reply_text(
            f"😔 Animation error: {type(e).__name__}: {str(e)[:200]}"
        )
# ==================== END WAN 2.2 I2V ====================


# ==================== LTX VIDEO COMMANDS ====================

async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /video command for LTX text-to-video generation (LTX-2)."""
    chat_id = update.effective_chat.id
    
    # Resolution presets
    RES_MAP = {
        "sd": (768, 512),
        "hd": (1280, 720),
        "fhd": (1920, 1088),
    }
    
    # Get the prompt from command arguments
    if not context.args:
        await update.message.reply_text(
            "🎬 To generate a video from text, use:\n"
            "`/video [res=X] [steps=X] [frames=X] [fps=X] [mode=X] <prompt>`\n\n"
            "**Options:**\n"
            "📐 `res=` sd, hd (default), fhd\n"
            "🔢 `steps=` 20-80 (default: 40)\n"
            "🎞️ `frames=` 1-481 (default: 121)\n"
            "⚡ `fps=` 1-60 (default: 25)\n"
            "⚙️ `mode=` full (default), distilled\n\n"
            "**Examples:**\n"
            "`/video a sunset over the ocean`\n"
            "`/video res=fhd frames=240 epic scene`\n"
            "`/video steps=80 fps=60 mode=full max quality`",
            parse_mode="Markdown"
        )
        return
    
    args = list(context.args)
    width, height = 1920, 1088  # default FHD (max quality)
    steps = 60  # high quality (balanced with frames)
    frames = 240  # high quality (240*60=14,400 < 20,000 limit)
    fps = 24.0  # cinematic frame rate
    distilled = False  # Full mode default
    
    # Parse optional parameters
    new_args = []
    for arg in args:
        if arg.lower().startswith("res="):
            res_key = arg[4:].lower()
            if res_key in RES_MAP:
                width, height = RES_MAP[res_key]
        elif arg.lower().startswith("steps="):
            try:
                steps = max(20, min(80, int(arg[6:])))
            except ValueError:
                pass
        elif arg.lower().startswith("frames="):
            try:
                frames = max(1, min(481, int(arg[7:])))
            except ValueError:
                pass
        elif arg.lower().startswith("fps="):
            try:
                fps = max(1.0, min(60.0, float(arg[4:])))
            except ValueError:
                pass
        elif arg.lower().startswith("mode="):
            mode = arg[5:].lower()
            distilled = mode != "full"
        else:
            new_args.append(arg)
    args = new_args
    
    if not args:
        await update.message.reply_text("Please provide a prompt.")
        return
    
    prompt = " ".join(args)
    mode_str = "Distilled" if distilled else "Full"
    
    # Show typing action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")
    
    try:
        # Call LTX-2 Text-to-Video API
        import random
        async with httpx.AsyncClient(timeout=600.0) as http_client:
            request_body = {
                "prompt": prompt,
                "negative_prompt": "low-res, morphing, distortion, warping, flicker, jitter, stutter, shaky camera, erratic motion, temporal artifacts, frame blending, low quality, jpeg artifacts",
                "height": height,
                "width": width,
                "num_frames": frames,
                "frame_rate": fps,
                "num_inference_steps": steps,
                "cfg_guidance_scale": 3.0,
                "seed": random.randint(1, 2**32 - 1),
                "distilled": distilled,
                "enhance_prompt": False,
            }
            
            logger.info(f"LTX T2V request: {prompt[:50]}...")
            
            response = await http_client.post(
                "https://chutes-ltx-2.chutes.ai/generate",
                headers={
                    "Authorization": f"Bearer {CHUTES_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=request_body
            )
            
            logger.info(f"LTX T2V response status: {response.status_code}")
            
            if response.status_code == 200:
                # LTX-2 returns raw video/mp4 content directly
                video_data = io.BytesIO(response.content)
                video_data.name = "generated_video.mp4"
                await update.message.reply_video(video=video_data)
            else:
                error_text = response.text[:300]
                logger.error(f"LTX T2V failed: {response.status_code} - {error_text}")
                await update.message.reply_text(f"😔 Video generation failed. Error: {response.status_code}")
                
    except httpx.TimeoutException:
        await update.message.reply_text("⏳ Video generation timed out. Please try again.")
    except Exception as e:
        logger.error(f"LTX T2V error: {e}")
        await update.message.reply_text("😔 Something went wrong. Please try again later.")



# Camera LoRAs for cinematic effects
CAMERA_LORAS = [
    "camera-dolly-in",
    "camera-dolly-out",
    "camera-dolly-left",
    "camera-dolly-right",
    "camera-jib-up",
    "camera-jib-down",
    "camera-static",
]

async def video_cinematic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /video_cinematic command for cinematic video with camera movements."""
    import random
    chat_id = update.effective_chat.id
    
    # Get the prompt from command arguments
    if not context.args:
        await update.message.reply_text(
            "🎥 To generate cinematic video with camera motion, use:\n"
            "`/video_cinematic [cam=X] [res=X] [frames=X] [fps=X] <prompt>`\n\n"
            "**Options:**\n"
            "📷 `cam=` dolly-in/out, dolly-left/right, jib-up/down, static, random (default)\n"
            "📐 `res=` sd, hd (default), fhd\n"
            "🎞️ `frames=` 1-481 (default: 121)\n"
            "⚡ `fps=` 1-60 (default: 25)\n\n"
            "**Examples:**\n"
            "`/video_cinematic a beautiful sunset`\n"
            "`/video_cinematic cam=dolly-in a beautiful sunset`\n"
            "`/video_cinematic res=fhd frames=240 cam=jib-up epic landscape`",
            parse_mode="Markdown"
        )
        return
    
    args = list(context.args)
    width, height = 1920, 1088  # default FHD (max quality)
    camera_lora = "random"
    frames = 240  # high quality (stays within work unit limit)
    fps = 24.0  # cinematic frame rate
    
    # Parse optional parameters
    new_args = []
    for arg in args:
        if arg.lower().startswith("cam="):
            cam = arg[4:].lower()
            if cam in ["dolly-in", "dolly-out", "dolly-left", "dolly-right", "jib-up", "jib-down", "static"]:
                camera_lora = f"camera-{cam}"
            elif cam == "random":
                camera_lora = "random"
        elif arg.lower().startswith("res="):
            res_key = arg[4:].lower()
            if res_key in RES_MAP:
                width, height = RES_MAP[res_key]
        elif arg.lower().startswith("frames="):
            try:
                frames = max(1, min(481, int(arg[7:])))
            except ValueError:
                pass
        elif arg.lower().startswith("fps="):
            try:
                fps = max(1.0, min(60.0, float(arg[4:])))
            except ValueError:
                pass
        else:
            new_args.append(arg)
    args = new_args
    
    if not args:
        await update.message.reply_text("Please provide a prompt.")
        return
    
    prompt = " ".join(args)
    
    # Pick random camera if requested
    if camera_lora == "random":
        camera_lora = random.choice(CAMERA_LORAS)
    
    camera_name = camera_lora.replace("camera-", "").replace("-", " ").title()
    
    # Show typing action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")
    
    try:
        # Call LTX-2 with camera LoRA
        async with httpx.AsyncClient(timeout=600.0) as http_client:
            request_body = {
                "prompt": prompt,
                "negative_prompt": "low-res, morphing, distortion, warping, flicker, jitter, stutter, erratic motion, temporal artifacts, frame blending, low quality, jpeg artifacts",
                "height": height,
                "width": width,
                "num_frames": frames,
                "frame_rate": fps,
                "num_inference_steps": 40,
                "cfg_guidance_scale": 3.0,
                "seed": random.randint(1, 2**32 - 1),
                "distilled": False,  # Use full model for better LoRA results
                "enhance_prompt": False,
                "loras": [
                    {"name": camera_lora, "strength": 1.0}
                ]
            }
            
            logger.info(f"Cinematic request with {camera_lora}: {prompt[:50]}...")
            
            response = await http_client.post(
                "https://chutes-ltx-2.chutes.ai/generate",
                headers={
                    "Authorization": f"Bearer {CHUTES_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=request_body
            )
            
            logger.info(f"Cinematic response status: {response.status_code}")
            
            if response.status_code == 200:
                # LTX-2 returns raw video/mp4 content directly
                video_data = io.BytesIO(response.content)
                video_data.name = "cinematic_video.mp4"
                await update.message.reply_video(video=video_data)
            else:
                error_text = response.text[:300]
                logger.error(f"Cinematic failed: {response.status_code} - {error_text}")
                await update.message.reply_text(f"😔 Video generation failed. Error: {response.status_code}")
                
    except httpx.TimeoutException:
        await update.message.reply_text("⏳ Video generation timed out. Please try again.")
    except Exception as e:
        logger.error(f"Cinematic error: {e}")
        await update.message.reply_text("😔 Something went wrong. Please try again later.")


async def ltxanimate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ltxanimate command for LTX image-to-video (LTX-2)."""
    chat_id = update.effective_chat.id
    
    # Check if user has an image stored
    if chat_id not in user_images or len(user_images[chat_id]) == 0:
        await update.message.reply_text(
            "📷 To animate with LTX, first send me a photo, then use:\n"
            "`/ltxanimate [steps=X] <motion description>`\n\n"
            "**Options:**\n"
            "🔢 `steps=` 30 (fast), 50 (balanced), 80 (high)\n\n"
            "**Examples:**\n"
            "`/ltxanimate gentle camera movement`\n"
            "`/ltxanimate steps=80 slow zoom with bokeh`",
            parse_mode="Markdown"
        )
        return
    
    args = list(context.args) if context.args else []
    steps = 80  # max quality (was 50) balanced
    
    # Parse optional parameters
    new_args = []
    for arg in args:
        if arg.lower().startswith("steps="):
            try:
                steps = max(30, min(80, int(arg[6:])))
            except ValueError:
                pass
        else:
            new_args.append(arg)
    args = new_args
    
    prompt = " ".join(args) if args else "gentle camera movement"
    
    # Show typing action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")
    
    try:
        import random
        # Get raw base64 image (use latest)
        image_b64 = user_images[chat_id][-1]
        
        # Call LTX-2 Image-to-Video API
        async with httpx.AsyncClient(timeout=600.0) as http_client:
            request_body = {
                "prompt": prompt,
                "negative_prompt": "low-res, morphing, distortion, warping, flicker, jitter, stutter, shaky camera, erratic motion, temporal artifacts, frame blending, low quality, jpeg artifacts",
                "image_b64": image_b64,
                "image_strength": 1.0,
                "height": 512,
                "width": 768,
                "num_frames": 121,
                "frame_rate": 25.0,
                "num_inference_steps": steps,
                "cfg_guidance_scale": 3.0,
                "seed": random.randint(1, 2**32 - 1),
                "distilled": False,  # Full mode default
                "enhance_prompt": False
            }
            
            logger.info(f"LTX I2V request: steps={steps}")
            
            response = await http_client.post(
                "https://chutes-ltx-2.chutes.ai/generate",
                headers={
                    "Authorization": f"Bearer {CHUTES_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=request_body
            )
            
            logger.info(f"LTX I2V response status: {response.status_code}")
            
            if response.status_code == 200:
                # LTX-2 returns raw video/mp4 content directly
                video_data = io.BytesIO(response.content)
                video_data.name = "ltx_animated.mp4"
                await update.message.reply_video(video=video_data)
            else:
                error_text = response.text[:300]
                logger.error(f"LTX I2V failed: {response.status_code} - {error_text}")
                await update.message.reply_text(f"😔 Animation failed. Error: {response.status_code}")
                
    except httpx.TimeoutException:
        await update.message.reply_text("⏳ Animation timed out. Please try again.")
    except Exception as e:
        logger.error(f"LTX I2V error: {e}")
        await update.message.reply_text("😔 Something went wrong. Please try again later.")
# ==================== END LTX VIDEO COMMANDS ====================


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photos and store them for editing/combining."""
    chat_id = update.effective_chat.id
    
    # Get the largest photo size
    photo = update.message.photo[-1]
    
    try:
        # Download the photo
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        
        # Convert to base64
        photo_b64 = base64.b64encode(photo_bytes).decode('utf-8')
        
        # Initialize list if not exists
        if chat_id not in user_images:
            user_images[chat_id] = []
        
        # Append to list (max 5 images)
        if len(user_images[chat_id]) >= 5:
            user_images[chat_id].pop(0)  # Remove oldest
        user_images[chat_id].append(photo_b64)
        
        count = len(user_images[chat_id])
        
        await update.message.reply_text(
            f"📸 Image {count}/5 received!\n\n"
            f"**Available commands:**\n"
            f"`/edit <prompt>` - Edit latest image\n"
            f"`/combine <prompt>` - Combine all {count} images\n"
            f"`/clearimages` - Clear stored images\n\n"
            f"Send more photos to add (max 5)",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Photo handling error: {e}")
        await update.message.reply_text(
            "😔 I couldn't process that image. Please try sending it again."
        )


async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /edit command for image editing (Qwen Image Edit)."""
    chat_id = update.effective_chat.id
    
    # Check if user has an image stored
    if chat_id not in user_images or len(user_images[chat_id]) == 0:
        await update.message.reply_text(
            "📷 To edit an image, first send me a photo, then use:\n"
            "`/edit [width height] [cfg=X] [steps=X] <prompt>`\n\n"
            "**Examples:**\n"
            "`/edit make it look like a painting`\n"
            "`/edit 1920 1080 transform to anime`\n"
            "`/edit cfg=6 steps=60 add dramatic lighting`\n\n"
            "Default: 1328×1328, cfg=4, steps=40",
            parse_mode="Markdown"
        )
        return
    
    # Get the prompt from command arguments
    if not context.args:
        await update.message.reply_text(
            "✨ To edit your image, use:\n"
            "`/edit [width height] [cfg=X] [steps=X] <prompt>`\n\n"
            "Example: `/edit add sunglasses`",
            parse_mode="Markdown"
        )
        return
    
    args = list(context.args)
    width = 1328  # default
    height = 1328  # default
    cfg_scale = 4  # default
    steps = 40  # default
    negative_prompt = ""
    
    # Check if first two args are dimensions
    if len(args) >= 3 and args[0].isdigit() and args[1].isdigit():
        width = max(256, min(2048, int(args[0])))
        height = max(256, min(2048, int(args[1])))
        args = args[2:]
    
    # Check for cfg=X and steps=X parameters
    new_args = []
    for arg in args:
        if arg.lower().startswith("cfg="):
            try:
                cfg_scale = max(1, min(10, int(float(arg[4:]))))
            except ValueError:
                pass
        elif arg.lower().startswith("steps="):
            try:
                steps = max(10, min(100, int(arg[6:])))
            except ValueError:
                pass
        elif arg.lower().startswith("neg="):
            negative_prompt = arg[4:]
        else:
            new_args.append(arg)
    args = new_args
    
    if not args:
        await update.message.reply_text("Please provide a prompt.")
        return
    
    prompt = " ".join(args)
    
    # Show upload photo action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    
    try:
        # Call Chutes Qwen Image Edit API
        async with httpx.AsyncClient(timeout=180.0) as http_client:
            response = await http_client.post(
                "https://chutes-qwen-image-edit-2511.chutes.ai/generate",
                headers={
                    "Authorization": f"Bearer {CHUTES_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "seed": None,
                    "width": width,
                    "height": height,
                    "prompt": prompt,
                    "image_b64s": [user_images[chat_id][-1]],  # Use latest image
                    "true_cfg_scale": cfg_scale,
                    "negative_prompt": negative_prompt,
                    "num_inference_steps": steps
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
                            await update.message.reply_photo(photo=image_data)
                            # Replace stored images with the edited result
                            user_images[chat_id] = [image_b64]
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
                    await update.message.reply_photo(photo=image_data)
                    # Store the edited image for further edits
                    edited_b64 = base64.b64encode(response.content).decode('utf-8')
                    user_images[chat_id] = [edited_b64]
                
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


async def combine_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /combine command for combining multiple images (Qwen Image Edit)."""
    chat_id = update.effective_chat.id
    
    # Check if user has multiple images stored
    if chat_id not in user_images or len(user_images[chat_id]) < 2:
        await update.message.reply_text(
            "📷 To combine images, first send me 2-5 photos, then use:\n"
            "`/combine [width height] [cfg=X] [steps=X] <prompt>`\n\n"
            "**Examples:**\n"
            "`/combine merge these images together`\n"
            "`/combine 1920 1080 create a collage`\n"
            "`/combine cfg=6 blend into one scene`\n\n"
            f"You have {len(user_images.get(chat_id, []))} image(s). Need at least 2.",
            parse_mode="Markdown"
        )
        return
    
    # Get the prompt from command arguments
    if not context.args:
        count = len(user_images[chat_id])
        await update.message.reply_text(
            f"✨ To combine your {count} images, use:\n"
            "`/combine <prompt>`\n\n"
            "Example: `/combine merge these into one scene`",
            parse_mode="Markdown"
        )
        return
    
    args = list(context.args)
    width = 1328  # default
    height = 1328  # default
    cfg_scale = 4  # default
    steps = 40  # default
    negative_prompt = ""
    
    # Check if first two args are dimensions
    if len(args) >= 3 and args[0].isdigit() and args[1].isdigit():
        width = max(256, min(2048, int(args[0])))
        height = max(256, min(2048, int(args[1])))
        args = args[2:]
    
    # Check for cfg=X and steps=X parameters
    new_args = []
    for arg in args:
        if arg.lower().startswith("cfg="):
            try:
                cfg_scale = max(1, min(10, int(float(arg[4:]))))
            except ValueError:
                pass
        elif arg.lower().startswith("steps="):
            try:
                steps = max(10, min(100, int(arg[6:])))
            except ValueError:
                pass
        elif arg.lower().startswith("neg="):
            negative_prompt = arg[4:]
        else:
            new_args.append(arg)
    args = new_args
    
    if not args:
        await update.message.reply_text("Please provide a prompt.")
        return
    
    prompt = " ".join(args)
    count = len(user_images[chat_id])
    
    # Show upload photo action
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    
    try:
        # Call Chutes Qwen Image Edit API with all stored images
        async with httpx.AsyncClient(timeout=180.0) as http_client:
            response = await http_client.post(
                "https://chutes-qwen-image-edit-2511.chutes.ai/generate",
                headers={
                    "Authorization": f"Bearer {CHUTES_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "seed": None,
                    "width": width,
                    "height": height,
                    "prompt": prompt,
                    "image_b64s": user_images[chat_id],  # All stored images
                    "true_cfg_scale": cfg_scale,
                    "negative_prompt": negative_prompt,
                    "num_inference_steps": steps
                }
            )
            
            if response.status_code == 200:
                try:
                    json_response = response.json()
                    
                    if isinstance(json_response, dict):
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
                            image_bytes = base64.b64decode(image_b64)
                            image_data = io.BytesIO(image_bytes)
                            image_data.name = "combined_image.png"
                            await update.message.reply_photo(photo=image_data)
                            # Replace stored images with the combined result
                            user_images[chat_id] = [image_b64]
                        else:
                            await update.message.reply_text("😔 Could not parse the response.")
                    else:
                        await update.message.reply_text("😔 Unexpected response format.")
                        
                except Exception:
                    # Raw image bytes
                    image_data = io.BytesIO(response.content)
                    image_data.name = "combined_image.png"
                    await update.message.reply_photo(photo=image_data)
                    combined_b64 = base64.b64encode(response.content).decode('utf-8')
                    user_images[chat_id] = [combined_b64]
                
            else:
                logger.error(f"Image combine failed: {response.status_code} - {response.text}")
                await update.message.reply_text(
                    f"😔 I couldn't combine those images. Error: {response.status_code}"
                )
                
    except httpx.TimeoutException:
        await update.message.reply_text(
            "⏳ The image combination is taking too long. Please try again."
        )
    except Exception as e:
        logger.error(f"Image combine error: {e}")
        await update.message.reply_text(
            "😔 Something went wrong while combining your images. Please try again later."
        )


async def clearimages_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clearimages command to clear stored images."""
    chat_id = update.effective_chat.id
    
    if chat_id in user_images:
        count = len(user_images[chat_id])
        user_images[chat_id] = []
        await update.message.reply_text(f"🗑️ Cleared {count} stored image(s). Send new photos to start fresh!")
    else:
        await update.message.reply_text("📭 No images stored. Send a photo to get started!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    chat_id = update.effective_chat.id
    user_message = update.message.text
    
    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Get AI response (async - allows concurrent message handling)
    response = await get_ai_response(chat_id, user_message)
    
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
    
    # Create application with concurrent updates enabled for parallel request handling
    application = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("generate", generate_command))
    application.add_handler(CommandHandler("imagine", imagine_command))  # Qwen-Image-2512
    application.add_handler(CommandHandler("edit", edit_command))
    application.add_handler(CommandHandler("combine", combine_command))  # Combine multiple images
    application.add_handler(CommandHandler("clearimages", clearimages_command))  # Clear stored images
    application.add_handler(CommandHandler("animate", animate_command))  # WAN 2.2 Image-to-Video
    application.add_handler(CommandHandler("video", video_command))  # LTX Text-to-Video
    application.add_handler(CommandHandler("video_cinematic", video_cinematic_command))  # LTX Cinematic with camera LoRAs
    application.add_handler(CommandHandler("ltxanimate", ltxanimate_command))  # LTX Image-to-Video
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Register commands with Telegram (so they appear in / menu)
    async def post_init(application):
        await application.bot.set_my_commands([
            ("start", "Start the bot"),
            ("clear", "Clear conversation history"),
            ("generate", "Generate image [w h]"),
            ("imagine", "HQ Image [w h] [cfg]"),
            ("edit", "Edit Image [w h] [cfg] [steps]"),
            ("combine", "Combine 2-5 images [w h] [cfg]"),
            ("clearimages", "Clear stored images"),
            ("video", "Text-to-Video [res] [steps] [mode]"),
            ("video_cinematic", "Cinematic Video [cam] [res]"),
            ("animate", "Animate Image [frames]"),
            ("ltxanimate", "LTX Animate Image [steps]"),
        ])
    
    application.post_init = post_init
    
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