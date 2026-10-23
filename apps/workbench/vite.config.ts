import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  publicDir: loadEnv('production', '.', 'ONTOVIS_').ONTOVIS_LOGIN_MEDIA_PUBLIC_DIR || false,
  server: {proxy: {'/api': {target: 'http://127.0.0.1:18084', changeOrigin: false}}},
  build: {outDir: '../../output/compact-workbench-20261021/workbench-dist', emptyOutDir: true},
});
