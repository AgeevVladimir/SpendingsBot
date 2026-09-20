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
