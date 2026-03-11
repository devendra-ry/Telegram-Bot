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

  private buildInlinePrompt(query: string): string {
    return [
      "You are a concise assistant for Telegram inline mode.",
      "Return a short plain-text answer in at most 450 characters.",
      "Do not use markdown.",
      `User query: ${query}`,
    ].join("\n");
  }

  private async requestGemini(prompt: string): Promise<string> {
    const { geminiApiKey, geminiModel } = this.appConfig.config;

    if (!geminiApiKey) {
      throw new Error("GEMINI_API_KEY is required");
    }

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
    return (
      data.candidates?.[0]?.content?.parts
        ?.map((part) => part.text || "")
        .join("")
        .trim() || "I could not generate a response. Please try again."
    );
  }

  async *generateStream(chatId: number, userMessage: string): AsyncGenerator<string, void, unknown> {
    const { maxHistory } = this.appConfig.config;
    // Push the user message first
    this.state.append(chatId, { role: "user", content: userMessage }, maxHistory);
    const prompt = this.buildPrompt(chatId);

    const { geminiApiKey, geminiModel } = this.appConfig.config;
    if (!geminiApiKey) {
      throw new Error("GEMINI_API_KEY is required");
    }

    const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(geminiModel)}:streamGenerateContent?alt=sse&key=${encodeURIComponent(geminiApiKey)}`;

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
      throw new Error(`Gemini stream failed (${response.status}): ${raw.slice(0, 300)}`);
    }

    if (!response.body) {
      throw new Error("Response body is null");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let fullOutput = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6).trim();
            if (!dataStr) continue;

            try {
              const data = JSON.parse(dataStr) as GeminiResponse;
              const textChunk = data.candidates?.[0]?.content?.parts
                ?.map((p) => p.text || "")
                .join("") || "";

              if (textChunk) {
                fullOutput += textChunk;
                yield textChunk;
              }
            } catch (e) {
              // Ignore parse errors for incomplete chunks just in case
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
      
      const finalOutput = fullOutput.trim() || "I could not generate a response.";
      this.state.append(chatId, { role: "assistant", content: finalOutput }, maxHistory);
    }
  }

  async generateInline(query: string): Promise<string> {
    const prompt = this.buildInlinePrompt(query);
    return this.requestGemini(prompt);
  }
}