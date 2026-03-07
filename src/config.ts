export type BotConfig = {
  telegramToken: string;
  geminiApiKey: string | null;
  geminiModel: string;
  telegramWebhookSecret: string;
  maxHistory: number;
};

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

function optionalEnv(name: string): string | null {
  const value = process.env[name];
  return value ? value : null;
}

export function loadConfig(): BotConfig {
  return {
    telegramToken: requiredEnv("TELEGRAM_BOT_TOKEN"),
    geminiApiKey: optionalEnv("GEMINI_API_KEY"),
    geminiModel: process.env.GEMINI_MODEL || "gemini-2.0-flash",
    telegramWebhookSecret: process.env.TELEGRAM_WEBHOOK_SECRET || "",
    maxHistory: Number(process.env.MAX_HISTORY || "20"),
  };
}