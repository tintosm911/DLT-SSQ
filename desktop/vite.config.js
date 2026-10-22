import { defineConfig } from 'vite'

// Tauri 期望固定端口 (devUrl), 且要打包出 dist/
export default defineConfig({
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: '127.0.0.1',
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'chrome105',
  },
})
