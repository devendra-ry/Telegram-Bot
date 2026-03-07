from collections.abc import Awaitable, Callable
import asyncio
import threading

import httpx
from google import genai
from google.genai import types

from assistant_bot.config import GEMINI_API_KEY, GEMINI_MODEL, MAX_HISTORY, TELEGRAM_TOKEN, logger
from assistant_bot.state import conversation_history

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def _trim_history(chat_id: int) -> None:
    if len(conversation_history[chat_id]) > MAX_HISTORY:
        conversation_history[chat_id] = conversation_history[chat_id][-MAX_HISTORY:]


def _build_prompt(chat_id: int) -> str:
    lines = ["You are a concise and helpful assistant."]
    for message in conversation_history[chat_id]:
        role = message.get("role", "user")
        content = message.get("content", "")
        prefix = "User" if role == "user" else "Assistant"
        lines.append(f"{prefix}: {content}")
    lines.append("Assistant:")
    return "\n".join(lines)


def _generation_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
    )


def _stream_gemini_sync(prompt: str, callback: Callable[[str], None]) -> str:
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    chunks: list[str] = []
    for chunk in client.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents=prompt,
        config=_generation_config(),
    ):
        text = getattr(chunk, "text", None)
        if not text:
            continue
        chunks.append(text)
        callback("".join(chunks))

    return "".join(chunks).strip()


def _generate_gemini_sync(prompt: str) -> str:
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=_generation_config(),
    )
    return (getattr(response, "text", "") or "").strip()


async def get_ai_response_with_stream(
    chat_id: int,
    user_message: str,
    on_partial: Callable[[str], Awaitable[None]] | None = None,
) -> str:
    """Get AI response from Gemini with streamed partial text updates."""
    conversation_history[chat_id].append({"role": "user", "content": user_message})
    _trim_history(chat_id)

    prompt = _build_prompt(chat_id)

    if client is None:
        return "GEMINI_API_KEY is not configured. Please set it in your environment."

    queue: asyncio.Queue[str | object] = asyncio.Queue()
    done = object()
    loop = asyncio.get_running_loop()

    result_text = ""
    error: Exception | None = None

    def worker() -> None:
        nonlocal result_text, error

        def push_partial(text: str) -> None:
            asyncio.run_coroutine_threadsafe(queue.put(text), loop)

        try:
            result_text = _stream_gemini_sync(prompt, push_partial)
        except Exception as exc:
            error = exc
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(done), loop)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = await queue.get()
        if item is done:
            break
        if on_partial is not None and isinstance(item, str):
            await on_partial(item)

    if error is not None:
        logger.error("Gemini stream error: %s", error)
        try:
            result_text = await asyncio.to_thread(_generate_gemini_sync, prompt)
        except Exception as fallback_error:
            logger.error("Gemini fallback error: %s", fallback_error)
            return "I hit an error while generating a response. Please try again."

    if not result_text:
        result_text = "I could not generate a response. Please try again."

    conversation_history[chat_id].append({"role": "assistant", "content": result_text})
    _trim_history(chat_id)
    return result_text


async def send_message_draft(
    chat_id: int,
    draft_id: int,
    text: str,
    message_thread_id: int | None = None,
) -> bool:
    """Send or refresh a Telegram draft message for streaming bot output."""
    if not TELEGRAM_TOKEN or not text:
        return False

    payload: dict[str, object] = {
        "chat_id": chat_id,
        "draft_id": draft_id,
        "text": text[:4096],
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessageDraft"

    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(url, json=payload)

        if response.status_code != 200:
            logger.warning("sendMessageDraft failed with status %s", response.status_code)
            return False

        data = response.json()
        return bool(data.get("ok"))
    except Exception as exc:
        logger.warning("sendMessageDraft request failed: %s", exc)
        return False
