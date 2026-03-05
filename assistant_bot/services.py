from collections.abc import Awaitable, Callable

import httpx
from openai import AsyncOpenAI

from assistant_bot.config import (
    AI_MODEL,
    CHUTES_API_KEY,
    CHUTES_BASE_URL,
    MAX_HISTORY,
    TELEGRAM_TOKEN,
    logger,
)
from assistant_bot.state import conversation_history

client = AsyncOpenAI(api_key=CHUTES_API_KEY, base_url=CHUTES_BASE_URL)


async def call_api(endpoint: str, payload: dict, timeout: float = 120.0) -> httpx.Response:
    """Make authenticated API call to Chutes."""
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        return await http_client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {CHUTES_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )


def parse_api_error(response: httpx.Response) -> str:
    """Parse API error response and return a user-friendly message."""
    try:
        json_data = response.json()
        for key in ["error", "message", "detail", "error_message", "msg"]:
            if key not in json_data:
                continue

            val = json_data[key]
            if isinstance(val, str):
                return val[:200]
            if isinstance(val, dict) and "message" in val:
                return str(val["message"])[:200]

        return f"Error {response.status_code}"
    except Exception:
        return f"Error {response.status_code}"


def _trim_history(chat_id: int) -> None:
    if len(conversation_history[chat_id]) > MAX_HISTORY:
        conversation_history[chat_id] = conversation_history[chat_id][-MAX_HISTORY:]


async def _complete_chat(messages: list[dict[str, str]]) -> str:
    response = await client.chat.completions.create(
        model=AI_MODEL,
        messages=messages,
        temperature=1.0,
    )
    text = response.choices[0].message.content or ""
    return text


async def get_ai_response(chat_id: int, user_message: str) -> str:
    """Get AI response from Chutes API with conversation history."""
    conversation_history[chat_id].append({"role": "user", "content": user_message})
    _trim_history(chat_id)

    messages = conversation_history[chat_id]

    try:
        assistant_message = await _complete_chat(messages)
        conversation_history[chat_id].append({"role": "assistant", "content": assistant_message})
        return assistant_message
    except Exception as exc:
        logger.error(f"Chutes API error: {exc}")
        return "I apologize, I'm experiencing a brief interruption. Could you please try again in a moment?"


async def get_ai_response_with_stream(
    chat_id: int,
    user_message: str,
    on_partial: Callable[[str], Awaitable[None]] | None = None,
) -> str:
    """Get AI response while emitting partial text chunks as they are generated."""
    conversation_history[chat_id].append({"role": "user", "content": user_message})
    _trim_history(chat_id)

    messages = conversation_history[chat_id]
    chunks: list[str] = []

    try:
        stream = await client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            temperature=1.0,
            stream=True,
        )

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            delta = getattr(choice, "delta", None)
            token = getattr(delta, "content", None) if delta else None
            if not token:
                continue

            chunks.append(token)
            if on_partial is not None:
                await on_partial("".join(chunks))

        assistant_message = "".join(chunks).strip()
        if not assistant_message:
            assistant_message = await _complete_chat(messages)

        conversation_history[chat_id].append({"role": "assistant", "content": assistant_message})
        return assistant_message
    except Exception as exc:
        logger.error(f"Streaming Chutes API error: {exc}")
        try:
            assistant_message = await _complete_chat(messages)
            conversation_history[chat_id].append({"role": "assistant", "content": assistant_message})
            return assistant_message
        except Exception as inner_exc:
            logger.error(f"Chutes API fallback error: {inner_exc}")
            return "I apologize, I'm experiencing a brief interruption. Could you please try again in a moment?"


async def send_message_draft(
    chat_id: int,
    draft_id: int,
    text: str,
    message_thread_id: int | None = None,
) -> bool:
    """Send/refresh a Telegram draft message for streaming bot output."""
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
