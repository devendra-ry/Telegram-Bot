import { Injectable, Logger } from "@nestjs/common";
import { Ctx, Start, Command, On, Update } from "nestjs-telegraf";
import type { Context } from "telegraf";
import { GeminiService } from "./gemini.service.js";
import { ConversationStateService } from "./conversation-state.service.js";

type InlineArticleResult = {
  type: "article";
  id: string;
  title: string;
  description?: string;
  input_message_content: {
    message_text: string;
  };
};

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
  private readonly inlineLastRequestAt = new Map<number, number>();
  private readonly inlineInFlightUsers = new Set<number>();
  private readonly inlineCache = new Map<string, { text: string; expiresAt: number }>();
  private static readonly CHAT_COOLDOWN_MS = 2500;
  private static readonly INLINE_COOLDOWN_MS = 3000;
  private static readonly INLINE_CACHE_TTL_MS = 60_000;
  private static readonly INLINE_TIMEOUT_MS = 4500;
  private static readonly INLINE_MIN_QUERY_LENGTH = 6;

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

  private makeInlineId(input: string): string {
    let hash = 0;
    for (let i = 0; i < input.length; i += 1) {
      hash = (hash << 5) - hash + input.charCodeAt(i);
      hash |= 0;
    }
    return `r-${Math.abs(hash).toString(36)}`;
  }

  private makeInlineResult(params: {
    id: string;
    title: string;
    description?: string;
    messageText: string;
  }): InlineArticleResult {
    return {
      type: "article",
      id: params.id,
      title: params.title,
      description: params.description,
      input_message_content: {
        message_text: params.messageText,
      },
    };
  }

  private pruneInlineCache(now: number): void {
    for (const [key, entry] of this.inlineCache) {
      if (entry.expiresAt <= now) {
        this.inlineCache.delete(key);
      }
    }
  }

  @On("inline_query")
  async onInlineQuery(@Ctx() ctx: Context): Promise<void> {
    const inlineQuery = ctx.inlineQuery;
    if (!inlineQuery) {
      return;
    }

    const userId = inlineQuery.from.id;
    const query = inlineQuery.query.trim();
    const now = Date.now();

    this.pruneInlineCache(now);

    if (query.length < TelegramUpdateHandler.INLINE_MIN_QUERY_LENGTH) {
      await ctx.answerInlineQuery(
        [
          this.makeInlineResult({
            id: `short-${userId}`,
            title: "Type a longer prompt",
            description: "Use at least 6 characters for inline generation.",
            messageText: "Please type a longer prompt (at least 6 characters).",
          }),
        ],
        { cache_time: 2, is_personal: true },
      );
      return;
    }

    const lastAt = this.inlineLastRequestAt.get(userId) || 0;
    if (now - lastAt < TelegramUpdateHandler.INLINE_COOLDOWN_MS) {
      await ctx.answerInlineQuery(
        [
          this.makeInlineResult({
            id: `cooldown-${userId}`,
            title: "Please wait",
            description: "Inline requests are rate-limited.",
            messageText: "You are sending requests too quickly. Please wait a moment.",
          }),
        ],
        { cache_time: 2, is_personal: true },
      );
      return;
    }

    const cacheKey = `${userId}:${query.toLowerCase()}`;
    const cached = this.inlineCache.get(cacheKey);
    if (cached && cached.expiresAt > now) {
      await ctx.answerInlineQuery(
        [
          this.makeInlineResult({
            id: this.makeInlineId(cacheKey),
            title: "Inline answer",
            description: "Cached result",
            messageText: cached.text,
          }),
        ],
        { cache_time: 5, is_personal: true },
      );
      return;
    }

    if (this.inlineInFlightUsers.has(userId)) {
      await ctx.answerInlineQuery(
        [
          this.makeInlineResult({
            id: `busy-${userId}`,
            title: "Still generating",
            description: "Previous inline request is in progress.",
            messageText: "Still generating previous request. Please retry in a second.",
          }),
        ],
        { cache_time: 2, is_personal: true },
      );
      return;
    }

    this.inlineLastRequestAt.set(userId, now);
    this.inlineInFlightUsers.add(userId);

    try {
      const output = await Promise.race([
        this.gemini.generateInline(query),
        new Promise<string>((_, reject) => {
          setTimeout(() => reject(new Error("Inline request timed out")), TelegramUpdateHandler.INLINE_TIMEOUT_MS);
        }),
      ]);

      const finalText = output.slice(0, 900);
      this.inlineCache.set(cacheKey, {
        text: finalText,
        expiresAt: now + TelegramUpdateHandler.INLINE_CACHE_TTL_MS,
      });

      await ctx.answerInlineQuery(
        [
          this.makeInlineResult({
            id: this.makeInlineId(cacheKey),
            title: "Inline answer",
            description: "Generated with Gemini",
            messageText: finalText,
          }),
        ],
        { cache_time: 5, is_personal: true },
      );
    } catch (error) {
      this.logger.warn(`Inline generation failed for user ${userId}: ${(error as Error).message}`);
      await ctx.answerInlineQuery(
        [
          this.makeInlineResult({
            id: `fallback-${userId}`,
            title: "Open bot chat",
            description: "Inline generation is temporarily unavailable.",
            messageText: "Inline generation is temporarily unavailable. Open the bot chat for full responses.",
          }),
        ],
        { cache_time: 3, is_personal: true },
      );
    } finally {
      this.inlineInFlightUsers.delete(userId);
    }
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