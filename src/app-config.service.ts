import { Injectable } from "@nestjs/common";
import { loadConfig, type BotConfig } from "./config.js";

@Injectable()
export class AppConfigService {
  readonly config: BotConfig;

  constructor() {
    this.config = loadConfig();
  }
}