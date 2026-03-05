import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHUTES_API_KEY = os.getenv("CHUTES_API_KEY")
CHUTES_BASE_URL = "https://llm.chutes.ai/v1"
AI_MODEL = "moonshotai/Kimi-K2.5-TEE"
MAX_HISTORY = 20

RES_MAP = {
    "sd": (768, 512),
    "hd": (1280, 768),
    "fhd": (1920, 1088),
}

CAMERA_LORAS = [
    "camera-dolly-in",
    "camera-dolly-out",
    "camera-dolly-left",
    "camera-dolly-right",
    "camera-jib-up",
    "camera-jib-down",
    "camera-static",
]

API_URLS = {
    "z_image": "https://chutes-z-image-turbo.chutes.ai/generate",
    "qwen_image": "https://chutes-qwen-image-2512.chutes.ai/generate",
    "qwen_edit": "https://chutes-qwen-image-edit-2511.chutes.ai/generate",
    "wan_i2v": "https://chutes-wan-2-2-i2v-14b-fast.chutes.ai/generate",
    "ltx": "https://chutes-ltx-2.chutes.ai/generate",
    "hunyuan": "https://chutes-hunyuan-image-3.chutes.ai/generate",
}
