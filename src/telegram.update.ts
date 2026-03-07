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
  private static readonly CHAT_COOLDOWN_MS = 2500;
  private static readonly INLINE_COOLDOWN_MS = 1500;
  private static readonly INLINE_MIN_QUERY_LENGTH = 2;

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
      "Hello.\n\nUse /ask <your prompt> anywhere I am present, or chat directly with me.\nUse /clear to reset conversation history.",
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

  private extractAskPrompt(ctx: Context): string {
    const message = ctx.message;
    if (!message || !("text" in message)) {
      return "";
    }

    const text = message.text.trim();
    const match = text.match(/^\/ask(?:@\w+)?\s*([\s\S]*)$/i);
    return (match?.[1] || "").trim();
  }

  @Command("ask")
  async onAsk(@Ctx() ctx: Context): Promise<void> {
    const chatId = ctx.chat?.id;
    if (!chatId) {
      return;
    }

    const prompt = this.extractAskPrompt(ctx);
    if (!prompt) {
      await ctx.reply("Usage: /ask <your prompt>");
      return;
    }

    await this.processPrompt(ctx, chatId, prompt);
  }

  private makeInlineId(input: string): string {
    let hash = 0;
    for (let i = 0; i < input.length; i += 1) {
      hash = (hash << 5) - hash + input.charCodeAt(i);
      hash |= 0;
    }
    return `q-${Math.abs(hash).toString(36)}`;
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

  @On("inline_query")
  async onInlineQuery(@Ctx() ctx: Context): Promise<void> {
    const inlineQuery = ctx.inlineQuery;
    if (!inlineQuery) {
      return;
    }

    const userId = inlineQuery.from.id;
    const query = inlineQuery.query.trim().replace(/\s+/g, " ");
    const now = Date.now();

    if (query.length < TelegramUpdateHandler.INLINE_MIN_QUERY_LENGTH) {
      await ctx.answerInlineQuery(
        [
          this.makeInlineResult({
            id: `hint-${userId}`,
            title: "Type your prompt",
            description: "Example: @ItsZaraBot write a caption",
            messageText: "Type your prompt after the bot username.",
          }),
        ],
        { cache_time: 1, is_personal: true },
      );
      return;
    }

    const lastAt = this.inlineLastRequestAt.get(userId) || 0;
    if (now - lastAt < TelegramUpdateHandler.INLINE_COOLDOWN_MS) {
      await ctx.answerInlineQuery(
        [
          this.makeInlineResult({
            id: `wait-${userId}`,
            title: "Please wait",
            description: "Inline request rate limit active.",
            messageText: "Please wait a second and try again.",
          }),
        ],
        { cache_time: 1, is_personal: true },
      );
      return;
    }

    this.inlineLastRequestAt.set(userId, now);

    const commandText = `/ask ${query}`.slice(0, 3800);
    await ctx.answerInlineQuery(
      [
        this.makeInlineResult({
          id: this.makeInlineId(`${userId}:${query}`),
          title: "Send query to Zara",
          description: "Sends /ask and Zara replies in the chat",
          messageText: commandText,
        }),
      ],
      { cache_time: 1, is_personal: true },
    );
  }

  private async processPrompt(ctx: Context, chatId: number, prompt: string): Promise<void> {
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
      const output = await this.gemini.generate(chatId, prompt);
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

    await this.processPrompt(ctx, chatId, text);
  }
}