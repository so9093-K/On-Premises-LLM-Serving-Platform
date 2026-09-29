import assert from 'node:assert/strict';
import test from 'node:test';

import { formatTimestamp, isoTimestamp } from '../src/timeFormat.ts';

test('valid epoch seconds render as a timestamp', () => {
  assert.equal(isoTimestamp(0), '1970-01-01T00:00:00.000Z');
  assert.notEqual(formatTimestamp(1790668297.45), '—');
});

test('missing or invalid timestamps never throw', () => {
  for (const value of [undefined, null, 'soon', Number.NaN, Number.POSITIVE_INFINITY, 1e20]) {
    assert.equal(formatTimestamp(value), '—');
    assert.equal(isoTimestamp(value), undefined);
  }
});
