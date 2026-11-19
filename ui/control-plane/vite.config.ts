import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/admin/console/',
  plugins: [react()],
  experimental: {
    // HTML 진입점만 서버의 mount로 치환하고, JS·CSS 자원은 같은 자원 디렉터리를 따른다.
    renderBuiltUrl(filename, { hostType }) {
      return hostType === 'html' ? `/admin/console/${filename}` : { relative: true };
    },
  },
  build: {
    rolldownOptions: {
      input: { console: 'index.html', playground: 'playground.html' },
    },
    outDir: '../../src/ai_model_serving/static/control-plane',
    assetsDir: 'assets',
    emptyOutDir: true,
    manifest: 'asset-manifest.json',
    sourcemap: false,
    target: 'es2022',
  },
});
