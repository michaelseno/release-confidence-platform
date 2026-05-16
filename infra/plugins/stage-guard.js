"use strict";

const ALLOWED_STAGES = new Set(["dev", "staging", "prod"]);

class StageGuardPlugin {
  constructor(serverless, options) {
    this.serverless = serverless;
    this.options = options || {};
    this.hooks = {
      initialize: this.validateStage.bind(this),
      "before:package:initialize": this.validateStage.bind(this),
      "before:deploy:deploy": this.validateStage.bind(this),
    };

    this.validateStage();
  }

  validateStage() {
    const stage = this.options.stage || this.serverless.service.provider.stage || "dev";

    if (!ALLOWED_STAGES.has(stage)) {
      const allowedStages = Array.from(ALLOWED_STAGES).join(", ");
      throw new Error(
        `Unsupported Serverless stage '${stage}'. Expected one of: ${allowedStages}`,
      );
    }
  }
}

module.exports = StageGuardPlugin;
