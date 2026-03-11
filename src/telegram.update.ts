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

function toTelegramHtml(text: string): string {
  // First cleanly escape unescaped ampersands
  let result = text.replace(/&(?!amp;|lt;|gt;|quot;|#\d+;)/g, "&amp;");
  
  // Then preserve valid Telegram HTML tags, while escaping raw < and >
  result = result.replace(
    /<(\/?)(b|strong|i|em|u|ins|s|strike|del|code|pre|a|tg-spoiler)(?:\s+[^>]*)?>|(<)|(>)/gi,
    (match, slash, tag, open, close) => {
      if (open) return "&lt;";
      if (close) return "&gt;";
      return match;
    }
  );

  // Still preserve this replacement in case there is some stray "**" bold generated
  return result
    .replace(/\*\*(.+?)\*\*/gs, "<b>$1</b>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>");
}

function closeUnclosedTags(html: string): string {
  const stack: string[] = [];
  const regex = /<(\/?)(b|strong|i|em|u|ins|s|strike|del|code|pre|a|tg-spoiler)(?:\s+[^>]*)?>/gi;
  let match;

  while ((match = regex.exec(html)) !== null) {
    const isClosing = match[1] === "/";
    const tag = match[2].toLowerCase();

    if (!isClosing) {
      stack.push(tag);
    } else {
      // Find the last open tag and pop it off if it matches
      const index = stack.lastIndexOf(tag);
      if (index !== -1) {
        stack.splice(index, 1);
      }
    }
  }

  // Close remaining unclosed tags
  let closedHtml = html;
  for (let i = stack.length - 1; i >= 0; i--) {
    closedHtml += `</${stack[i]}>`;
  }
  return closedHtml;
}

@Injectable()
@Update()
export class TelegramUpdateHandler {
  private readonly logger = new Logger(TelegramUpdateHandler.name);
  private readonly lastRequestAt = new Map<number, number>();
  private readonly inFlightChats = new Set<number>();
  private static readonly CHAT_COOLDOWN_MS = 2500;
  private static readonly INLINE_MIN_QUERY_LENGTH = 1;

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

  private extractAskPrompt(ctx: Context): string | null {
    const message = ctx.message;
    if (!message || !("text" in message)) {
      return null;
    }

    const text = message.text.trim();
    const match = text.match(/^\/ask(?:@\w+)?\s*([\s\S]*)$/i);
    if (!match) {
      return null;
    }
    return (match[1] || "").trim();
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

    const botUsername = ctx.me || "ItsZaraBot";
    const commandText = `/ask@${botUsername} ${query}`.slice(0, 3800);
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
      
      let fullText = "";
      let lastEditTime = Date.now();
      const EDIT_INTERVAL_MS = 1000;
      let streamId: string | null = null;
      let messageId: number | null = null;

      const stream = this.gemini.generateStream(chatId, prompt);
      for await (const chunk of stream) {
        fullText += chunk;
        const nowMs = Date.now();

        const safeHtml = closeUnclosedTags(toTelegramHtml(fullText));

        if (!streamId && !messageId) {
           // Establish stream natively on telegram api 
           try {
             const payload = {
                chat_id: chatId,
                text: safeHtml,
                parse_mode: "HTML",
                // Enable streaming on the message natively
                reply_markup: {
                  is_streaming: true
                }
             } as any;

             // We use native callApi because telegraf types might not have it yet fully mapped
             const response = await ctx.telegram.callApi("sendMessage", payload) as any; // Cast since types might lag behind 9.5 officially
             messageId = response.message_id;
           } catch (e: any) {
              // fallback if the lib/API completely refuses `is_streaming` structure
              console.error("Native streaming unsupported structure fallback", e);
              const fallbackMsg = await ctx.reply(safeHtml, { parse_mode: "HTML" });
              messageId = fallbackMsg.message_id;
           }
           lastEditTime = nowMs;
        } else if (messageId && nowMs - lastEditTime > EDIT_INTERVAL_MS) {
          lastEditTime = nowMs;
          try {
            await ctx.telegram.editMessageText(chatId, messageId, undefined, safeHtml, { parse_mode: "HTML" });
          } catch (editError) {
             // Ignore "message is not modified" or parsing issues during partial chunks
          }
        }
      }

      // Final edit to ensure the complete message is visible and cap the string natively
      const finalHtml = closeUnclosedTags(toTelegramHtml(fullText));
      if (messageId) {
        try {
          await ctx.telegram.editMessageText(chatId, messageId, undefined, finalHtml, { parse_mode: "HTML" });
        } catch (finalEditError) {
          // Only fails if the final text is identical to the last chunk edit
        }
      } else {
         await ctx.reply(finalHtml, { parse_mode: "HTML" });
      }

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

    const askPrompt = this.extractAskPrompt(ctx);
    if (askPrompt !== null) {
      if (!askPrompt) {
        await ctx.reply("Usage: /ask <your prompt>");
        return;
      }
      await this.processPrompt(ctx, chatId, askPrompt);
      return;
    }

    const text = message.text.trim();
    if (text.startsWith("/")) {
      return;
    }

    await this.processPrompt(ctx, chatId, text);
  }
}