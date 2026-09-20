const { Telegraf } = require('telegraf');
const {
  addMember,
  addSpending,
  closeTrip,
  createTrip,
  readTrip
} = require('./storage');

function getCommandArgs(text) {
  const firstSpace = text.indexOf(' ');
  return firstSpace === -1 ? '' : text.slice(firstSpace + 1).trim();
}

function splitSpendingArguments(raw) {
  const parts = raw.split(';').map((part) => part.trim());
  if (parts.length !== 5) {
    return null;
  }
  return parts;
}

function isValidIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }

  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day
  );
}

function parseSharedMembers(sharedRaw) {
  const members = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < sharedRaw.length; i += 1) {
    const ch = sharedRaw[i];
    if (ch === '"') {
      if (inQuotes && sharedRaw[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (ch === ',' && !inQuotes) {
      if (current.trim()) {
        members.push(current.trim());
      }
      current = '';
      continue;
    }

    current += ch;
  }

  if (inQuotes) {
    return null;
  }
  if (current.trim()) {
    members.push(current.trim());
  }
  return members;
}

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
        'Use quotes for names with commas, e.g. "Alice, A",Bob',
        '/spendings',
        '/closetrip'
      ].join('\n')
    );
  });

  bot.command('newtrip', async (ctx) => {
    const name = getCommandArgs(ctx.message.text);
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
    const member = getCommandArgs(ctx.message.text);
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
    try {
      const state = await readTrip(ctx.chat.id);
      if (!state.trip) {
        return ctx.reply('Create a trip first with /newtrip');
      }

      if (state.members.length === 0) {
        return ctx.reply('No members yet. Use /addmember');
      }

      return ctx.reply(`Members:\n${state.members.map((member) => `- ${member}`).join('\n')}`);
    } catch (error) {
      return ctx.reply(error.message);
    }
  });

  bot.command('addspending', async (ctx) => {
    const raw = getCommandArgs(ctx.message.text);
    const parts = splitSpendingArguments(raw);
    if (!parts) {
      return ctx.reply('Usage: /addspending <amount>; <date>; <description>; <payer>; <shared1,shared2>');
    }

    const [amountRaw, date, description, payer, sharedRaw] = parts;
    if (!/^\d+(\.\d{1,2})?$/.test(amountRaw)) {
      return ctx.reply('Amount must be a positive number in EUR with up to 2 decimals.');
    }
    const amountEur = Number(amountRaw);
    const sharedWith = parseSharedMembers(sharedRaw);
    if (!sharedWith) {
      return ctx.reply('Shared members list has invalid quotes.');
    }

    if (!Number.isFinite(amountEur) || amountEur <= 0) {
      return ctx.reply('Amount must be a positive number in EUR.');
    }

    if (!isValidIsoDate(date)) {
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
    try {
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
    } catch (error) {
      return ctx.reply(error.message);
    }
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
  createBot,
  _test: {
    getCommandArgs,
    splitSpendingArguments,
    isValidIsoDate,
    parseSharedMembers
  }
};
