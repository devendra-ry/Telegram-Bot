import { Injectable } from "@nestjs/common";
import { AppConfigService } from "./app-config.service.js";
import { ConversationStateService } from "./conversation-state.service.js";

type GeminiPart = { text?: string };

type GeminiCandidate = {
  content?: {
    parts?: GeminiPart[];
  };
};

type GeminiResponse = {
  candidates?: GeminiCandidate[];
};

@Injectable()
export class GeminiService {
  constructor(
    private readonly appConfig: AppConfigService,
    private readonly state: ConversationStateService,
  ) {}

  private buildPrompt(chatId: number): string {
    const lines = [
      "You are a concise and helpful assistant. Use plain text or Telegram-compatible HTML tags (<b>, <i>, <code>, <pre>) for formatting. Do not use Markdown syntax like **bold**.",
    ];

    for (const message of this.state.getHistory(chatId)) {
      const prefix = message.role === "user" ? "User" : "Assistant";
      lines.push(`${prefix}: ${message.content}`);
    }

    lines.push("Assistant:");
    return lines.join("\n");
  }

  async generate(chatId: number, userMessage: string): Promise<string> {
    const { geminiApiKey, geminiModel, maxHistory } = this.appConfig.config;

    if (!geminiApiKey) {
      throw new Error("GEMINI_API_KEY is required");
    }

    this.state.append(chatId, { role: "user", content: userMessage }, maxHistory);

    const prompt = this.buildPrompt(chatId);
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(geminiModel)}:generateContent?key=${encodeURIComponent(geminiApiKey)}`;

    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.6 },
      }),
    });

    if (!response.ok) {
      const raw = await response.text();
      throw new Error(`Gemini request failed (${response.status}): ${raw.slice(0, 300)}`);
    }

    const data = (await response.json()) as GeminiResponse;
    const output =
      data.candidates?.[0]?.content?.parts
        ?.map((part) => part.text || "")
        .join("")
        .trim() || "I could not generate a response. Please try again.";

    this.state.append(chatId, { role: "assistant", content: output }, maxHistory);
    return output;
  }
}