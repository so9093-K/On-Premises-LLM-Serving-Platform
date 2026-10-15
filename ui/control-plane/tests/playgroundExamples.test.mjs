import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, statSync } from 'node:fs';
import { chatControls, DEFAULT_CHAT_SETTINGS, buildChatRequest } from '../src/chatSession.ts';
import {
  EXAMPLE_SAMPLE_BYTES, PLAYGROUND_EXAMPLES, exampleAvailability, exampleRequiresFreshConversation, exampleSettingsConflict, exampleSettingsPatch,
} from '../src/playgroundExamples.ts';

const chat = {
  id: 'local-main',
  backend: 'vllm-cuda',
  capabilities: ['chat.completions'],
  input_modalities: ['text', 'image'],
  request_parameters: {
    stream: { type: 'boolean' },
    response_format: { type: 'object', allowed_types: ['text', 'json_schema'], json_schema: { max_schema_bytes: 8192, max_depth: 10, max_total_properties: 50, require_root_object: true, require_additional_properties_false: true, strict_allowed: true } },
  },
  request_limits: { image: { max_inputs: 1, max_bytes: 100000, allowed_mime_types: ['image/png'] } },
};
const availability = (example, model) => exampleAvailability(
  example,
  model,
  chatControls(model),
  (candidate) => {
    const settings = { ...DEFAULT_CHAT_SETTINGS, ...exampleSettingsPatch(candidate, DEFAULT_CHAT_SETTINGS) };
    return buildChatRequest(model, settings, [], candidate.prompt).error;
  },
);
const get = (id) => {
  const found = PLAYGROUND_EXAMPLES.find((example) => example.id === id);
  assert.ok(found, `missing example: ${id}`);
  return found;
};

test('example catalog has stable unique identifiers and honest sample references', () => {
  assert.equal(PLAYGROUND_EXAMPLES.length, 5);
  assert.equal(new Set(PLAYGROUND_EXAMPLES.map((example) => example.id)).size, PLAYGROUND_EXAMPLES.length);
  assert.deepEqual(PLAYGROUND_EXAMPLES.filter((example) => example.sample).map((example) => example.sample), ['chart', 'order']);
  assert.ok(PLAYGROUND_EXAMPLES.every((example) => example.title && example.description && example.prompt));
});

test('image examples are unavailable to text-only models and structured example obeys advertised format', () => {
  const textOnly = { ...chat, input_modalities: ['text'], request_parameters: { stream: { type: 'boolean' } } };
  assert.equal(availability(get('summarize'), textOnly).available, true);
  assert.equal(availability(get('chart'), textOnly).available, false);
  assert.match(availability(get('chart'), textOnly).reason, /이미지/);
  assert.equal(availability(get('structured'), textOnly).available, false);
  assert.equal(availability(get('structured'), chat).available, true);
  const jpegOnly = { ...chat, request_limits: { image: { allowed_mime_types: ['image/jpeg'] } } };
  assert.equal(availability(get('chart'), jpegOnly).available, false);
  const tooSmall = { ...chat, request_limits: { image: { allowed_mime_types: ['image/png'], max_bytes: 24098 } } };
  assert.equal(availability(get('chart'), tooSmall).available, false);
  assert.equal(availability(get('order'), tooSmall).available, false);
  const largeEnough = { ...chat, request_limits: { image: { allowed_mime_types: ['image/png'], max_bytes: 34473 } } };
  assert.equal(availability(get('order'), largeEnough).available, true);
  const restrictiveSchema = {
    ...chat, request_parameters: {
      ...chat.request_parameters,
      response_format: {
        ...chat.request_parameters.response_format,
        json_schema: { max_schema_bytes: 8, require_root_object: true },
      },
    },
  };
  assert.equal(availability(get('structured'), restrictiveSchema).available, false);
  const noChat = { ...chat, capabilities: [] };
  assert.equal(availability(get('summarize'), noChat).available, false);
});

test('only example-owned settings are reset; advanced settings are preserved by patch', () => {
  const current = { ...DEFAULT_CHAT_SETTINGS, temperature: '0.4', systemPrompt: 'old', toolDrafts: [{ id: 'a', name: 'legacy', description: '', parametersText: '{}', strict: null }] };
  const next = { ...current, ...exampleSettingsPatch(get('structured'), DEFAULT_CHAT_SETTINGS) };
  assert.equal(next.temperature, '0.4');
  assert.equal(next.systemPrompt, '');
  assert.deepEqual(next.toolDrafts, []);
  assert.equal(next.responseFormat, 'json_schema');
  assert.equal(JSON.parse(next.jsonSchemaText).additionalProperties, false);
  const cleared = { ...next, ...exampleSettingsPatch(get('summarize'), DEFAULT_CHAT_SETTINGS) };
  assert.equal(cleared.responseFormat, 'default');
  assert.equal(cleared.jsonSchemaText, '');
});

test('structured example generates a request accepted by the existing serialization contract', () => {
  const example = get('structured');
  const settings = { ...DEFAULT_CHAT_SETTINGS, ...exampleSettingsPatch(example, DEFAULT_CHAT_SETTINGS) };
  const { body, error } = buildChatRequest(chat, settings, [], example.prompt);
  assert.equal(error, null);
  assert.equal(body.response_format.type, 'json_schema');
  assert.equal(body.response_format.json_schema.name, example.schema.name);
  assert.equal(body.messages.at(-1).content, example.prompt);
});

test('system and schema examples demand a fresh conversation; other examples can continue', () => {
  assert.equal(exampleRequiresFreshConversation(get('system-prompt')), true);
  assert.equal(exampleRequiresFreshConversation(get('structured')), true);
  assert.equal(exampleRequiresFreshConversation(get('chart')), false);
  assert.equal(exampleRequiresFreshConversation(get('summarize')), false);
});

test('bundled image sizes are pinned to the original public demo assets', () => {
  for (const [id, filename] of [['chart', 'sample-chart.png'], ['order', 'sample-order.png']]) {
    const assetUrl = new URL(`../src/playgroundAssets/${filename}`, import.meta.url);
    const originalUrl = new URL(`../../../assets/demos/inputs/${filename}`, import.meta.url);
    const bundled = readFileSync(assetUrl);
    const original = readFileSync(originalUrl);
    assert.equal(statSync(assetUrl).size, EXAMPLE_SAMPLE_BYTES[id]);
    assert.deepEqual(bundled, original);
    // PNG IHDR: dimensions are available for max_pixels validation in the UI.
    assert.equal(bundled.subarray(1, 4).toString(), 'PNG');
    assert.ok(bundled.readUInt32BE(16) > 0 && bundled.readUInt32BE(20) > 0);
  }
});

test('replacement confirmation includes every example-owned field, not only visible top-level settings', () => {
  const example = get('summarize');
  const patch = exampleSettingsPatch(example, DEFAULT_CHAT_SETTINGS);
  assert.equal(exampleSettingsConflict(DEFAULT_CHAT_SETTINGS, patch), false);
  assert.equal(exampleSettingsConflict({ ...DEFAULT_CHAT_SETTINGS, toolChoiceName: 'existing' }, patch), true);
  assert.equal(exampleSettingsConflict({ ...DEFAULT_CHAT_SETTINGS, jsonSchemaStrict: true }, patch), true);
  assert.equal(exampleSettingsConflict({ ...DEFAULT_CHAT_SETTINGS, jsonSchemaText: '{"type":"object"}' }, patch), true);
  assert.equal(exampleSettingsConflict({ ...DEFAULT_CHAT_SETTINGS, temperature: '0.7' }, patch), false);
  assert.equal(exampleSettingsConflict({ ...DEFAULT_CHAT_SETTINGS, systemPrompt: 'existing' }, patch), true);
});

test('browser-facing apply workflow guards preserve old conversation and focus only after re-enabling the input', () => {
  const chatPage = readFileSync(new URL('../src/ChatPage.tsx', import.meta.url), 'utf8');
  assert.match(chatPage, /useState\(\(\) => exchanges\.length === 0\)/);
  assert.match(chatPage, /if \(error === null\) \{[\s\S]{0,250}setShowExamples\(false\)/);
  assert.match(chatPage, /exampleSettingsConflict\(session\.settings, patch\)/);
  assert.match(chatPage, /setFocusComposerAfterExample\(true\)/);
  assert.match(chatPage, /if \(!focusComposerAfterExample \|\| exampleLoading \|\| attachmentBusy/);
  assert.match(chatPage, /composerRef\.current\?\.focus\(\)/);
  assert.doesNotMatch(chatPage, /document\.getElementById\('chat-input'\)\?\.focus\(\)/);
  assert.match(chatPage, /exampleSnapshotRef\.current\.settings === initialContext\.settings/);
  assert.match(chatPage, /exampleSnapshotRef\.current\.exchanges === initialContext\.exchanges/);
  assert.match(chatPage, /const bitmap = await createImageBitmap\(file\)/);
  assert.match(chatPage, /validateChatAttachments\(model, \[\.\.\.conversationAttachments\(exchanges\), candidate\]\)/);
});
