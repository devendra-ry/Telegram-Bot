export type BotConfig = {
  telegramToken: string;
  geminiApiKey: string;
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

export function loadConfig(): BotConfig {
  return {
    telegramToken: requiredEnv("TELEGRAM_BOT_TOKEN"),
    geminiApiKey: requiredEnv("GEMINI_API_KEY"),
    geminiModel: process.env.GEMINI_MODEL || "gemini-2.0-flash",
    telegramWebhookSecret: process.env.TELEGRAM_WEBHOOK_SECRET || "",
    maxHistory: Number(process.env.MAX_HISTORY || "20"),
  };
}