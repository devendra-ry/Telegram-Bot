import type { INestApplicationContext } from "@nestjs/common";
import { NestFactory } from "@nestjs/core";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import "reflect-metadata";
import type { Update } from "telegraf/types";
import { AppModule } from "../src/app.module.js";
import { TelegramWebhookService } from "../src/telegram-webhook.service.js";

let appContextPromise: Promise<INestApplicationContext> | null = null;

async function getAppContext(): Promise<INestApplicationContext> {
  if (!appContextPromise) {
    appContextPromise = NestFactory.createApplicationContext(AppModule, {
      logger: ["error", "warn", "log"],
      abortOnError: false,
    });
  }

  return appContextPromise;
}

function getSecretHeader(req: VercelRequest): string {
  const value = req.headers["x-telegram-bot-api-secret-token"];
  if (Array.isArray(value)) {
    return value[0] || "";
  }
  return value || "";
}

function parseUpdate(body: unknown): Update | null {
  try {
    const data = typeof body === "string" ? JSON.parse(body) : body;
    if (!data || typeof data !== "object") {
      return null;
    }

    const maybeUpdate = data as { update_id?: unknown };
    if (typeof maybeUpdate.update_id !== "number") {
      return null;
    }

    return data as Update;
  } catch {
    return null;
  }
}

let cachedSecret: string | undefined;

export default async function handler(req: VercelRequest, res: VercelResponse): Promise<void> {
  if (req.method !== "POST") {
    res.status(405).json({ ok: false, error: "Method not allowed" });
    return;
  }

  if (cachedSecret === undefined) {
    cachedSecret = process.env.TELEGRAM_WEBHOOK_SECRET || "";
  }

  const expectedSecret = cachedSecret;
  if (expectedSecret) {
    const incoming = getSecretHeader(req);
    if (incoming && incoming !== expectedSecret) {
      res.status(401).json({ ok: false, error: "Unauthorized" });
      return;
    }
  }

  const update = parseUpdate(req.body);
  if (!update) {
    console.log("Webhook ignored: invalid update body");
    res.status(200).json({ ok: true, ignored: true });
    return;
  }

  console.log(`Webhook received update_id=${update.update_id}`);

  try {
    const appContext = await getAppContext();
    const webhookService = appContext.get(TelegramWebhookService);
    await webhookService.handleUpdate(update);
    res.status(200).json({ ok: true });
  } catch (error) {
    const message = (error as Error).message || "Unknown error";
    console.error("Webhook processing failed", error);
    res.status(200).json({ ok: false, error: message });
  }
}