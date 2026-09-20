const { Telegraf } = require('telegraf');
const {
  addMember,
  addSpending,
  closeTrip,
  createTrip,
  readTrip
} = require('./storage');

function createBot(token) {
  const bot = new Telegraf(token);

  bot.start((ctx) => {
    ctx.reply(
      [
        'SpendingsBot is ready.',
        'Commands:',
        '/newtrip <trip name>',
        '/addmember <name>',
        '/members',
        '/addspending <amount>; <date YYYY-MM-DD>; <description>; <payer>; <shared1,shared2>',
        '/spendings',
        '/closetrip'
      ].join('\n')
    );
  });

  bot.command('newtrip', async (ctx) => {
    const name = ctx.message.text.replace('/newtrip', '').trim();
    if (!name) {
      return ctx.reply('Usage: /newtrip <trip name>');
    }

    try {
      await createTrip(ctx.chat.id, name);
      return ctx.reply(`Trip "${name}" is created.`);
    } catch (error) {
      return ctx.reply(error.message);
    }
  });

  bot.command('addmember', async (ctx) => {
    const member = ctx.message.text.replace('/addmember', '').trim();
    if (!member) {
      return ctx.reply('Usage: /addmember <name>');
    }

    try {
      await addMember(ctx.chat.id, member);
      return ctx.reply(`Member "${member}" added.`);
    } catch (error) {
      return ctx.reply(error.message);
    }
  });

  bot.command('members', async (ctx) => {
    const state = await readTrip(ctx.chat.id);
    if (!state.trip) {
      return ctx.reply('Create a trip first with /newtrip');
    }

    if (state.members.length === 0) {
      return ctx.reply('No members yet. Use /addmember');
    }

    return ctx.reply(`Members:\n${state.members.map((member) => `- ${member}`).join('\n')}`);
  });

  bot.command('addspending', async (ctx) => {
    const raw = ctx.message.text.replace('/addspending', '').trim();
    const parts = raw.split(';').map((part) => part.trim());
    if (parts.length !== 5) {
      return ctx.reply('Usage: /addspending <amount>; <date>; <description>; <payer>; <shared1,shared2>');
    }

    const [amountRaw, date, description, payer, sharedRaw] = parts;
    const amountEur = Number(amountRaw);
    const sharedWith = sharedRaw.split(',').map((member) => member.trim()).filter(Boolean);

    if (!Number.isFinite(amountEur) || amountEur <= 0) {
      return ctx.reply('Amount must be a positive number in EUR.');
    }

    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      return ctx.reply('Date must be in format YYYY-MM-DD.');
    }

    if (!description || !payer || sharedWith.length === 0) {
      return ctx.reply('Description, payer and shared members are required.');
    }

    try {
      await addSpending(ctx.chat.id, {
        amountEur,
        date,
        description,
        payer,
        sharedWith
      });
      return ctx.reply('Spending added.');
    } catch (error) {
      return ctx.reply(error.message);
    }
  });

  bot.command('spendings', async (ctx) => {
    const state = await readTrip(ctx.chat.id);
    if (!state.trip) {
      return ctx.reply('Create a trip first with /newtrip');
    }

    if (state.spendings.length === 0) {
      return ctx.reply('No spendings yet.');
    }

    const lines = state.spendings.map((spending, index) => (
      `${index + 1}. ${spending.date} - €${spending.amountEur.toFixed(2)} - ${spending.description} (paid by ${spending.payer}, shared: ${spending.sharedWith.join(', ')})`
    ));

    return ctx.reply(lines.join('\n'));
  });

  bot.command('closetrip', async (ctx) => {
    try {
      const settlements = await closeTrip(ctx.chat.id);
      if (settlements.length === 0) {
        return ctx.reply('Trip closed. Everybody is settled up.');
      }

      const lines = settlements.map(
        (settlement) => `${settlement.from} owes ${settlement.to} €${settlement.amountEur.toFixed(2)}`
      );
      return ctx.reply(`Trip closed. Settlements:\n${lines.join('\n')}`);
    } catch (error) {
      return ctx.reply(error.message);
    }
  });

  return bot;
}

module.exports = {
  createBot
};
