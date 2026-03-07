import { Injectable } from "@nestjs/common";
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
  private readonly lastRequestAt = new Map<number, number>();
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

  @On("inline_query")
  async onInlineQuery(@Ctx() ctx: Context): Promise<void> {
    await ctx.answerInlineQuery([], {
      cache_time: 2,
      is_personal: true,
    });
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
      return;
    }
    this.lastRequestAt.set(chatId, now);

    await ctx.sendChatAction("typing");

    try {
      const output = await this.gemini.generate(chatId, text);
      await ctx.reply(toTelegramHtml(output), { parse_mode: "HTML" });
    } catch {
      await ctx.reply("Something went wrong. Please try again later.");
    }
  }
}