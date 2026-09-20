const { createBot } = require('./src/bot');

if (!process.env.BOT_TOKEN) {
  throw new Error('BOT_TOKEN is required');
}

const bot = createBot(process.env.BOT_TOKEN);

bot.launch();

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
