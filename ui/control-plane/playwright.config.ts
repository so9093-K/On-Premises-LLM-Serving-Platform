import { defineConfig } from '@playwright/test';

const previewPort = 4173;
const previewOutDir = 'node_modules/.cache/playwright-preview';
const previewUrl = `http://127.0.0.1:${previewPort}`;

export default defineConfig({
  testDir: './tests/browser',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: previewUrl,
    browserName: 'chromium',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `npm run check:toolchain && npm run generate:types && npm exec -- vite build --outDir ${previewOutDir} --emptyOutDir && npm exec -- vite preview --outDir ${previewOutDir} --host 127.0.0.1 --port ${previewPort} --strictPort`,
    url: previewUrl,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
