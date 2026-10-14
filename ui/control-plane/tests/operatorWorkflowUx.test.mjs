import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

function source(file) {
  return readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8');
}

test('operator navigation keeps group labels separate from server-authorized actions', () => {
  const app = source('App.tsx');
  assert.match(app, /const sections = SECTIONS\.filter\(\(section\) => section\.enabled\(bootstrap\)\)/);
  assert.match(app, /const visible = sections\.filter\(\(section\) => group\.paths\.includes\(section\.path\)\)/);
  assert.match(app, /NAV_GROUPS\.map/);
});

test('overview quick actions only advertise chat and model controls under active target features', () => {
  const overview = source('OverviewPage.tsx');
  assert.match(overview, /bootstrap\.deployment\.features\.includes\('chat'\) \? \(/);
  assert.match(overview, /modelSwitchingEnabled \? \(/);
  assert.match(overview, /외부 관리 런타임/);
  assert.match(overview, /실제 추론 응답은 Playground에서 확인/);
});

test('GPU admission reservations are not presented as measured VRAM utilization', () => {
  const runtime = source('RuntimePage.tsx');
  assert.match(runtime, /정책상 GPU 예약 예산/);
  assert.match(runtime, /실제 GPU 메모리 사용량은 별도의 관측 지표로 확인/);
  assert.match(runtime, /VRAM 정책 비율/);
});

test('configuration filter consumes the schema group rather than key prefix guesses', () => {
  const config = source('ConfigurationPage.tsx');
  assert.match(config, /new Set\(schemaItems\.map\(\(item\) => item\.group\)\)/);
  assert.match(config, /schemaItems\.filter\(\(item\) => item\.group === groupFilter\)/);
  assert.match(config, /configurationItemApplies\(metadata, deploymentFeatures\)/);
});
