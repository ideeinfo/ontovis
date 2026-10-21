import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  server: {proxy: {'/api': {target: 'http://127.0.0.1:18084', changeOrigin: false}}},
  build: {outDir: '../../output/current-evidence-preview-20261021/workbench-dist', emptyOutDir: true},
});
