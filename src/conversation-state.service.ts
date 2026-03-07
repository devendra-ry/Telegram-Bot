import { Injectable } from "@nestjs/common";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

@Injectable()
export class ConversationStateService {
  private readonly history = new Map<number, ChatMessage[]>();

  getHistory(chatId: number): ChatMessage[] {
    return this.history.get(chatId) || [];
  }

  clearHistory(chatId: number): void {
    this.history.set(chatId, []);
  }

  append(chatId: number, message: ChatMessage, maxHistory: number): void {
    const messages = this.getHistory(chatId);
    messages.push(message);

    if (messages.length > maxHistory) {
      messages.splice(0, messages.length - maxHistory);
    }

    this.history.set(chatId, messages);
  }
}