const fs = require('node:fs/promises');
const path = require('node:path');
const writeLocks = new Map();

const HEADER = [
  'recordType',
  'tripName',
  'member',
  'amountEur',
  'date',
  'description',
  'payer',
  'sharedWith',
  'closed',
  'createdAt'
];

function escapeCsvValue(value) {
  const text = String(value ?? '');
  if (text.includes('\n') || text.includes('\r')) {
    throw new Error('Multiline values are not supported in CSV storage');
  }
  if (text.includes(',') || text.includes('"') || text.includes('\n')) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function parseCsvLine(line) {
  const values = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];

    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (ch === ',' && !inQuotes) {
      values.push(current);
      current = '';
      continue;
    }

    current += ch;
  }

  values.push(current);
  return values;
}

function serializeRows(rows) {
  const lines = [HEADER.join(',')];
  for (const row of rows) {
    const line = HEADER.map((key) => escapeCsvValue(row[key] ?? '')).join(',');
    lines.push(line);
  }
  return `${lines.join('\n')}\n`;
}

function parseRows(content) {
  const lines = content.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length === 0) {
    return [];
  }

  const [, ...dataLines] = lines;
  return dataLines.map((line) => {
    const fields = parseCsvLine(line);
    const row = {};
    HEADER.forEach((key, index) => {
      row[key] = fields[index] ?? '';
    });
    return row;
  });
}

function getStoragePath(chatId, dataDir = process.env.DATA_DIR || path.join(process.cwd(), 'data')) {
  return path.join(dataDir, `trip_${chatId}.csv`);
}

async function readTrip(chatId, dataDir) {
  const storagePath = getStoragePath(chatId, dataDir);
  try {
    const content = await fs.readFile(storagePath, 'utf8');
    const rows = parseRows(content);
    const trip = rows.find((row) => row.recordType === 'trip') || null;
    const members = rows.filter((row) => row.recordType === 'member').map((row) => row.member);
    const spendings = rows
      .filter((row) => row.recordType === 'spending')
      .map((row) => ({
        amountEur: Number(row.amountEur),
        date: row.date,
        description: row.description,
        payer: row.payer,
        sharedWith: row.sharedWith ? row.sharedWith.split('|') : []
      }));

    return {
      trip: trip
        ? {
            name: trip.tripName,
            closed: trip.closed === 'true'
          }
        : null,
      members,
      spendings,
      storagePath,
      rows
    };
  } catch (error) {
    if (error.code === 'ENOENT') {
      return { trip: null, members: [], spendings: [], storagePath, rows: [] };
    }
    throw error;
  }
}

async function writeRows(storagePath, rows) {
  await fs.mkdir(path.dirname(storagePath), { recursive: true });
  await fs.writeFile(storagePath, serializeRows(rows), 'utf8');
}

function withChatLock(chatId, operation) {
  const key = String(chatId);
  const previous = writeLocks.get(key) || Promise.resolve();
  const run = previous.then(operation);
  const tail = run.catch(() => {});
  writeLocks.set(key, tail);
  return run.finally(() => {
    if (writeLocks.get(key) === tail) {
      writeLocks.delete(key);
    }
  });
}

async function createTrip(chatId, name, dataDir) {
  await withChatLock(chatId, async () => {
    const { storagePath, trip } = await readTrip(chatId, dataDir);
    if (trip) {
      throw new Error('Trip already exists for this chat');
    }
    const rows = [
      {
        recordType: 'trip',
        tripName: name,
        closed: 'false',
        createdAt: new Date().toISOString()
      }
    ];
    await writeRows(storagePath, rows);
  });
}

async function addMember(chatId, memberName, dataDir) {
  await withChatLock(chatId, async () => {
    const state = await readTrip(chatId, dataDir);
    if (!state.trip) {
      throw new Error('Trip is not created');
    }
    if (state.trip.closed) {
      throw new Error('Trip is already closed');
    }
    if (state.members.includes(memberName)) {
      throw new Error(`Member ${memberName} already exists`);
    }

    state.rows.push({
      recordType: 'member',
      member: memberName,
      createdAt: new Date().toISOString()
    });

    await writeRows(state.storagePath, state.rows);
  });
}

async function addSpending(chatId, spending, dataDir) {
  await withChatLock(chatId, async () => {
    const state = await readTrip(chatId, dataDir);
    if (!state.trip) {
      throw new Error('Trip is not created');
    }
    if (state.trip.closed) {
      throw new Error('Trip is already closed');
    }

    const unknownMembers = spending.sharedWith.filter((member) => !state.members.includes(member));
    if (!state.members.includes(spending.payer) || unknownMembers.length > 0) {
      throw new Error('All payer and shared members must be added first');
    }

    state.rows.push({
      recordType: 'spending',
      amountEur: spending.amountEur,
      date: spending.date,
      description: spending.description,
      payer: spending.payer,
      sharedWith: spending.sharedWith.join('|'),
      createdAt: new Date().toISOString()
    });

    await writeRows(state.storagePath, state.rows);
  });
}

function calculateSettlement(members, spendings) {
  const balances = Object.fromEntries(members.map((member) => [member, 0]));

  for (const spending of spendings) {
    const split = spending.amountEur / spending.sharedWith.length;
    balances[spending.payer] += spending.amountEur;
    for (const member of spending.sharedWith) {
      balances[member] -= split;
    }
  }

  const creditors = [];
  const debtors = [];

  for (const [member, balance] of Object.entries(balances)) {
    if (balance > 0.005) {
      creditors.push({ member, amount: balance });
    } else if (balance < -0.005) {
      debtors.push({ member, amount: -balance });
    }
  }

  const settlements = [];
  let i = 0;
  let j = 0;

  while (i < debtors.length && j < creditors.length) {
    const payment = Math.min(debtors[i].amount, creditors[j].amount);
    settlements.push({
      from: debtors[i].member,
      to: creditors[j].member,
      amountEur: Number(payment.toFixed(2))
    });

    debtors[i].amount -= payment;
    creditors[j].amount -= payment;

    if (debtors[i].amount <= 0.005) i += 1;
    if (creditors[j].amount <= 0.005) j += 1;
  }

  return settlements;
}

async function closeTrip(chatId, dataDir) {
  return withChatLock(chatId, async () => {
    const state = await readTrip(chatId, dataDir);
    if (!state.trip) {
      throw new Error('Trip is not created');
    }
    if (state.trip.closed) {
      throw new Error('Trip is already closed');
    }

    const settlements = calculateSettlement(state.members, state.spendings);
    const tripRow = state.rows.find((row) => row.recordType === 'trip');
    tripRow.closed = 'true';
    await writeRows(state.storagePath, state.rows);

    return settlements;
  });
}

module.exports = {
  addMember,
  addSpending,
  calculateSettlement,
  closeTrip,
  createTrip,
  readTrip,
  getStoragePath
};
