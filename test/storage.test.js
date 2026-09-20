const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const {
  addMember,
  addSpending,
  calculateSettlement,
  closeTrip,
  createTrip,
  readTrip
} = require('../src/storage');

test('calculateSettlement splits spendings correctly', () => {
  const result = calculateSettlement(
    ['Alice', 'Bob', 'Charlie'],
    [
      {
        amountEur: 90,
        payer: 'Alice',
        sharedWith: ['Alice', 'Bob', 'Charlie']
      },
      {
        amountEur: 30,
        payer: 'Bob',
        sharedWith: ['Bob', 'Charlie']
      }
    ]
  );

  assert.deepEqual(result, [
    { from: 'Bob', to: 'Alice', amountEur: 15 },
    { from: 'Charlie', to: 'Alice', amountEur: 45 }
  ]);
});

test('trip data is persisted in csv and closed', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'spendingsbot-'));

  await createTrip(1, 'Weekend', dir);
  await addMember(1, 'Alice', dir);
  await addMember(1, 'Bob', dir);
  await addSpending(1, {
    amountEur: 10,
    date: '2026-09-20',
    description: 'Taxi',
    payer: 'Alice',
    sharedWith: ['Alice', 'Bob']
  }, dir);

  const beforeClose = await readTrip(1, dir);
  assert.equal(beforeClose.spendings.length, 1);

  const settlements = await closeTrip(1, dir);
  assert.deepEqual(settlements, [{ from: 'Bob', to: 'Alice', amountEur: 5 }]);

  const afterClose = await readTrip(1, dir);
  assert.equal(afterClose.trip.closed, true);
});

test('csv storage supports commas and quotes', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'spendingsbot-'));

  await createTrip(2, 'Weekend, "City"', dir);
  await addMember(2, 'Alice, "A"', dir);
  await addMember(2, 'Bob', dir);
  await addSpending(2, {
    amountEur: 12.5,
    date: '2026-09-20',
    description: 'Dinner, "Pasta"',
    payer: 'Alice, "A"',
    sharedWith: ['Alice, "A"', 'Bob']
  }, dir);

  const state = await readTrip(2, dir);
  assert.equal(state.trip.name, 'Weekend, "City"');
  assert.deepEqual(state.members, ['Alice, "A"', 'Bob']);
  assert.equal(state.spendings[0].description, 'Dinner, "Pasta"');
});

test('createTrip does not overwrite existing trip and multiline values are rejected', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'spendingsbot-'));

  await createTrip(3, 'Trip', dir);
  await assert.rejects(() => createTrip(3, 'Another', dir), /Trip already exists/);

  await addMember(3, 'Alice', dir);
  await assert.rejects(
    () => addMember(3, 'Bob\nB', dir),
    /Multiline values are not supported/
  );
});

test('closeTrip cannot run twice', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'spendingsbot-'));

  await createTrip(4, 'Trip', dir);
  await addMember(4, 'Alice', dir);
  await closeTrip(4, dir);
  await assert.rejects(() => closeTrip(4, dir), /Trip is already closed/);
});
