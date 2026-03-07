import { Module } from "@nestjs/common";
import { TelegrafModule } from "nestjs-telegraf";
import { AppConfigService } from "./app-config.service.js";
import { GeminiService } from "./gemini.service.js";
import { ConversationStateService } from "./conversation-state.service.js";
import { TelegramUpdateHandler } from "./telegram.update.js";
import { TelegramWebhookService } from "./telegram-webhook.service.js";

@Module({
  imports: [
    TelegrafModule.forRootAsync({
      inject: [AppConfigService],
      useFactory: (appConfig: AppConfigService) => ({
        token: appConfig.config.telegramToken,
        launchOptions: false,
      }),
    }),
  ],
  providers: [
    AppConfigService,
    ConversationStateService,
    GeminiService,
    TelegramUpdateHandler,
    TelegramWebhookService,
  ],
  exports: [TelegramWebhookService],
})
export class AppModule {}