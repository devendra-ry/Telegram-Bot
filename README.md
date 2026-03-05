# Assistant Bot (Telegram)

A Telegram bot that uses Google Gemini for text chat and supports Telegram draft streaming updates during response generation.

## Features

- Text chat with Gemini (`google-genai`)
- Streaming partial output via Telegram `sendMessageDraft` (private chats)
- Conversation history per chat (in-memory)
- Health endpoints via Flask (`/`, `/healthz`)

## Current Scope

Enabled:
- `/start`
- `/clear`
- Normal text messages

Disabled (intentional during migration from Chutes):
- `/generate`
- `/imagine`
- `/dream`
- `/edit`
- `/combine`
- `/clearimages`
- `/animate`
- `/video`
- `/video_cinematic`
- `/ltxanimate`

## Project Structure

- `bot.py` - Entry point
- `assistant_bot/app.py` - Telegram app/bootstrap and handler registration
- `assistant_bot/handlers.py` - Command/message handlers
- `assistant_bot/services.py` - Gemini generation + Telegram draft API calls
- `assistant_bot/config.py` - Environment/config values
- `assistant_bot/state.py` - In-memory conversation state

## Requirements

- Python 3.10+
- Telegram Bot API token
- Gemini API key

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment Variables

Create or update `.env`:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
# Optional:
# GEMINI_MODEL=gemini-3-flash-preview
# PORT=8080
```

## Run

```bash
python bot.py
```

## How Streaming Works

- Bot streams Gemini output in chunks.
- In private chats, chunks are pushed using `sendMessageDraft`.
- Final full response is still sent as a normal Telegram message.
- If draft updates fail, bot falls back to final message only.

## Health Endpoints

- `GET /` -> status text
- `GET /healthz` -> `OK`

## Security Notes

- Never commit `.env`.
- Rotate keys immediately if exposed.
- Prefer separate keys per environment (dev/prod).

## Deployment Notes

- Set `PORT` if your host requires a specific port.
- Polling mode is used (`application.run_polling`).

