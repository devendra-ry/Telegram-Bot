# Assistant Bot (Telegram) - NestJS + Telegraf + Vercel

A Telegram bot built with NestJS and Telegraf, deployed as Vercel serverless functions using Telegram webhooks.

## Stack

- NestJS (`@nestjs/core`, `@nestjs/common`)
- Telegraf via `nestjs-telegraf`
- Vercel serverless route for webhook ingestion (`/api/telegram`)
- Gemini REST API for LLM responses

## Features

- Direct chat text responses with per-chat history
- Inline mode support with safeguards:
  - minimum query length
  - per-user cooldown
  - in-memory short TTL cache
  - timeout fallback

## Project Structure

- `api/telegram.ts` - Vercel webhook endpoint, forwards updates into Nest app context
- `api/index.ts` - Status endpoint
- `api/healthz.ts` - Health endpoint
- `src/app.module.ts` - Nest module + Telegraf module wiring
- `src/telegram.update.ts` - Telegraf update handlers (`/start`, `/clear`, `/ping`, text, inline)
- `src/telegram-webhook.service.ts` - Injected bot wrapper for `handleUpdate`
- `src/gemini.service.ts` - Gemini integration
- `src/conversation-state.service.ts` - In-memory history store
- `src/app-config.service.ts` - Environment-backed config service

## Environment Variables

Set in Vercel Project Settings:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.0-flash
TELEGRAM_WEBHOOK_SECRET=your_random_secret
MAX_HISTORY=20
```

## Local Validation

```bash
npm install
npm run check
```

## Deploy on Vercel

1. Push repo to GitHub.
2. Import project in Vercel.
3. Set environment variables.
4. Deploy.

Then set Telegram webhook:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<your-vercel-domain>/api/telegram" \
  -d "allowed_updates=[\"message\",\"inline_query\"]"
```

## Notes

- This is webhook mode (not polling), suitable for Vercel.
- Conversation history is in-memory and can reset across cold starts.
- Inline cache/rate-limit state is also in-memory.