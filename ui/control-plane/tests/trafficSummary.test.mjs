import assert from 'node:assert/strict';
import test from 'node:test';

import { formatSeconds, trafficTiles, trafficWindowLabel } from '../src/trafficSummary.ts';

function summary(overrides = {}) {
  return {
    window_seconds: 300,
    observed_seconds: 300,
    minimum_samples: { p50: 10, p95: 20 },
    requests: { total: 120, client_errors: 3, server_errors: 0 },
    completion_latency_seconds: { samples: 40, p50: 0.61, p95: 1.93 },
    time_to_first_chunk_seconds: { samples: 5, p50: null, p95: null },
    ...overrides,
  };
}

test('server errors are the only traffic signal colored as a warning', () => {
  const healthy = trafficTiles(summary());
  assert.equal(healthy.find((tile) => tile.key === 'server-errors').tone, 'good');
  assert.ok(healthy.filter((tile) => tile.key !== 'server-errors').every((tile) => tile.tone === 'neutral'));

  const failing = trafficTiles(summary({ requests: { total: 200, client_errors: 0, server_errors: 1 } }));
  const errors = failing.find((tile) => tile.key === 'server-errors');
  assert.equal(errors.tone, 'warning');
  assert.match(errors.detail, /0\.50%/);
});

test('latency is withheld with an explanation until the contract minimum is reached', () => {
  const tiles = trafficTiles(summary());
  const firstChunk = tiles.find((tile) => tile.key === 'first-chunk');
  assert.equal(firstChunk.value, '표본 부족');
  assert.match(firstChunk.detail, /20건 이상/);
  assert.match(firstChunk.detail, /현재 5건/);

  const completion = tiles.find((tile) => tile.key === 'completion-latency');
  assert.equal(completion.value, '1.9초');
  assert.match(completion.detail, /p50 610ms/);
});

test('an idle window reads as no traffic rather than as missing data', () => {
  const idle = trafficTiles(summary({
    requests: { total: 0, client_errors: 0, server_errors: 0 },
    completion_latency_seconds: { samples: 0, p50: null, p95: null },
  }));
  assert.equal(idle.find((tile) => tile.key === 'completion-latency').value, '요청 없음');
  assert.match(idle.find((tile) => tile.key === 'requests').detail, /요청이 없습니다/);
});

test('window label discloses a partially observed window after restart', () => {
  assert.equal(trafficWindowLabel(summary()), '최근 5분');
  assert.equal(trafficWindowLabel(summary({ observed_seconds: 95 })), '최근 5분 (Gateway 시작 후 2분 관측)');
  assert.equal(formatSeconds(null), '—');
});
