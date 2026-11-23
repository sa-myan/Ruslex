import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [svelte(), tailwindcss()],
  base: '/static/',
  build: { outDir: '../backend/frontend_static', emptyOutDir: true },
  server: { proxy: { '/api': 'http://localhost:8000', '/healthz': 'http://localhost:8000' } }
});
