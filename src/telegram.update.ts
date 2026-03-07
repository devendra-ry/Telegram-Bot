import { Injectable, Logger } from "@nestjs/common";
import { Ctx, Start, Command, On, Update } from "nestjs-telegraf";
import type { Context } from "telegraf";
import { GeminiService } from "./gemini.service.js";
import { ConversationStateService } from "./conversation-state.service.js";

function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function toTelegramHtml(text: string): string {
  const escaped = escapeHtml(text);
  return escaped
    .replace(/\*\*(.+?)\*\*/gs, "<b>$1</b>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>");
}

@Injectable()
@Update()
export class TelegramUpdateHandler {
  private readonly logger = new Logger(TelegramUpdateHandler.name);
  private readonly lastRequestAt = new Map<number, number>();
  private readonly inFlightChats = new Set<number>();
  private static readonly CHAT_COOLDOWN_MS = 2500;

  constructor(
    private readonly gemini: GeminiService,
    private readonly state: ConversationStateService,
  ) {}

  @Start()
  async onStart(@Ctx() ctx: Context): Promise<void> {
    const chatId = ctx.chat?.id;
    if (!chatId) {
      return;
    }

    this.state.clearHistory(chatId);
    await ctx.reply(
      "Hello.\n\nThis bot uses Google Gemini for text responses. Use /clear to reset conversation history.",
    );
  }

  @Command("clear")
  async onClear(@Ctx() ctx: Context): Promise<void> {
    const chatId = ctx.chat?.id;
    if (!chatId) {
      return;
    }

    this.state.clearHistory(chatId);
    await ctx.reply("Conversation history cleared.");
  }

  @Command("ping")
  async onPing(@Ctx() ctx: Context): Promise<void> {
    await ctx.reply("pong");
  }

  @On("inline_query")
  async onInlineQuery(@Ctx() ctx: Context): Promise<void> {
    await ctx.answerInlineQuery(
      [
        {
          type: "article",
          id: "use-private-chat",
          title: "Use direct chat with bot",
          description: "Inline generation is disabled to prevent API spam.",
          input_message_content: {
            message_text: "Open the bot chat and send your prompt there.",
          },
        },
      ],
      {
        cache_time: 30,
        is_personal: true,
      },
    );
  }

  @On("text")
  async onMessage(@Ctx() ctx: Context): Promise<void> {
    const chatId = ctx.chat?.id;
    const message = ctx.message;

    if (!chatId || !message || !("text" in message)) {
      return;
    }

    const text = message.text.trim();

    if (text.startsWith("/")) {
      return;
    }

    const now = Date.now();
    const lastAt = this.lastRequestAt.get(chatId) || 0;
    if (now - lastAt < TelegramUpdateHandler.CHAT_COOLDOWN_MS) {
      await ctx.reply("Please wait a moment and send again.");
      return;
    }

    if (this.inFlightChats.has(chatId)) {
      await ctx.reply("Please wait, I am still generating your previous response.");
      return;
    }

    this.lastRequestAt.set(chatId, now);
    this.inFlightChats.add(chatId);

    try {
      await ctx.sendChatAction("typing");
      const output = await this.gemini.generate(chatId, text);
      await ctx.reply(toTelegramHtml(output), { parse_mode: "HTML" });
    } catch (error) {
      const messageText = (error as Error).message || "Unknown error";
      this.logger.error(`Failed to generate response for chat ${chatId}: ${messageText}`);

      if (messageText.includes("GEMINI_API_KEY is required")) {
        await ctx.reply("Server is missing GEMINI_API_KEY. Please configure it in Vercel.");
      } else {
        await ctx.reply("Something went wrong. Please try again later.");
      }
    } finally {
      this.inFlightChats.delete(chatId);
    }
  }
}