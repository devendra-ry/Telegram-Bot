import { Injectable, Logger, type OnModuleInit } from "@nestjs/common";
import { InjectBot } from "nestjs-telegraf";
import { Telegraf, type Context } from "telegraf";
import type { Update } from "telegraf/types";

@Injectable()
export class TelegramWebhookService implements OnModuleInit {
  private readonly logger = new Logger(TelegramWebhookService.name);
  private readonly seenUpdates = new Map<number, number>();
  private readonly inFlightUpdates = new Set<number>();
  private static readonly DEDUPE_TTL_MS = 2 * 60 * 1000;

  constructor(
    @InjectBot()
    private readonly bot: Telegraf<Context>,
  ) {}

  async onModuleInit(): Promise<void> {
    try {
      await this.bot.telegram.setMyCommands([
        { command: "start", description: "Start the bot" },
        { command: "ask", description: "Ask Zara in current chat" },
        { command: "clear", description: "Clear conversation history" },
        { command: "ping", description: "Health check command" },
      ]);
    } catch (error) {
      this.logger.warn(`Failed to set bot commands: ${(error as Error).message}`);
    }
  }

  private prune(now: number): void {
    for (const [updateId, seenAt] of this.seenUpdates) {
      if (now - seenAt > TelegramWebhookService.DEDUPE_TTL_MS) {
        this.seenUpdates.delete(updateId);
      }
    }
  }

  async handleUpdate(update: Update): Promise<void> {
    const updateId = update.update_id;
    const now = Date.now();
    this.prune(now);

    if (typeof updateId === "number") {
      if (this.seenUpdates.has(updateId) || this.inFlightUpdates.has(updateId)) {
        return;
      }
      this.inFlightUpdates.add(updateId);
    }

    try {
      await this.bot.handleUpdate(update);
      if (typeof updateId === "number") {
        this.seenUpdates.set(updateId, now);
      }
    } finally {
      if (typeof updateId === "number") {
        this.inFlightUpdates.delete(updateId);
      }
    }
  }
}