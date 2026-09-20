const test = require('node:test');
const assert = require('node:assert/strict');

const { _test } = require('../src/bot');

test('getCommandArgs removes only command token', () => {
  assert.equal(_test.getCommandArgs('/newtrip my /newtrip plan'), 'my /newtrip plan');
  assert.equal(_test.getCommandArgs('/addmember'), '');
});

test('splitSpendingArguments requires exactly five fields', () => {
  assert.equal(_test.splitSpendingArguments('10;2026-09-20;Dinner;late;Alice;Bob'), null);
  assert.deepEqual(
    _test.splitSpendingArguments('10; 2026-09-20; Dinner; Alice; Bob,Charlie'),
    ['10', '2026-09-20', 'Dinner', 'Alice', 'Bob,Charlie']
  );
});

test('isValidIsoDate validates real calendar dates', () => {
  assert.equal(_test.isValidIsoDate('2026-02-28'), true);
  assert.equal(_test.isValidIsoDate('2026-02-31'), false);
  assert.equal(_test.isValidIsoDate('2026-99-99'), false);
});

test('parseSharedMembers supports quoted commas', () => {
  assert.deepEqual(_test.parseSharedMembers('"Alice, A",Bob'), ['Alice, A', 'Bob']);
  assert.deepEqual(_test.parseSharedMembers('"Alice ""The A"" , A",Bob'), ['Alice "The A" , A', 'Bob']);
  assert.equal(_test.parseSharedMembers('"Alice,Bob'), null);
});
