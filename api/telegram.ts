import type { INestApplicationContext } from "@nestjs/common";
import { NestFactory } from "@nestjs/core";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import "reflect-metadata";
import { AppModule } from "../src/app.module.js";
import { TelegramWebhookService } from "../src/telegram-webhook.service.js";

let appContextPromise: Promise<INestApplicationContext> | null = null;

async function getAppContext(): Promise<INestApplicationContext> {
  if (!appContextPromise) {
    appContextPromise = NestFactory.createApplicationContext(AppModule, {
      logger: ["error", "warn"],
    });
  }

  return appContextPromise;
}

export default async function handler(req: VercelRequest, res: VercelResponse): Promise<void> {
  if (req.method !== "POST") {
    res.status(405).json({ ok: false, error: "Method not allowed" });
    return;
  }

  const expectedSecret = process.env.TELEGRAM_WEBHOOK_SECRET || "";
  if (expectedSecret) {
    const incoming = req.headers["x-telegram-bot-api-secret-token"];
    if (incoming !== expectedSecret) {
      res.status(401).json({ ok: false, error: "Unauthorized" });
      return;
    }
  }

  try {
    const appContext = await getAppContext();
    const webhookService = appContext.get(TelegramWebhookService);
    await webhookService.handleUpdate(req.body);
    res.status(200).json({ ok: true });
  } catch (error) {
    res.status(200).json({ ok: false, error: (error as Error).message });
  }
}