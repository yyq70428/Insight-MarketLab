const assert = require('node:assert/strict');

function validateHold(entry, bars, thresholdPct) {
  const maxUp = Math.max(...bars.map(bar => (bar.high - entry) / entry * 100));
  const maxDown = Math.max(...bars.map(bar => (entry - bar.low) / entry * 100));
  return maxUp <= thresholdPct && maxDown <= thresholdPct;
}

function chooseExit(bar, target, stop, side = 'BUY') {
  const stopHit = side === 'BUY' ? bar.low <= stop : bar.high >= stop;
  const targetHit = side === 'BUY' ? bar.high >= target : bar.low <= target;
  if (stopHit) return 'stop';
  if (targetHit) return 'target';
  return null;
}

assert.equal(chooseExit({high: 112, low: 88}, 110, 90), 'stop');
assert.equal(validateHold(100, [{high: 102, low: 98}], 2), true);
assert.equal(validateHold(100, [{high: 102.01, low: 99}], 2), false);

module.exports = { validateHold, chooseExit };
