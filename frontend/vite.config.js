import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

/**
 * 开发环境把 /api、/auth、/healthz 全部代理到后端（8000），
 * 这样前端一律使用相对路径：既没有跨域，Cookie 也落在同一个 host 上。
 * 长连接同样走代理（ws: true），因此 WebSocket 地址可以直接由 location 推导。
 */
const BACKEND = process.env.VITE_BACKEND || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: false, ws: true },
      '/auth': { target: BACKEND, changeOrigin: false },
      '/healthz': { target: BACKEND, changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    // 全量注册 Element Plus（含全部图标）后，UI 库压缩前约 1.1MB，
    // 高于 Vite 默认的 500kB 阈值。这是「组件与图标全局可用」的既定取舍，
    // 因此把阈值提到略高于该体积，避免每次构建都刷一条无行动价值的告警。
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // Element Plus 是全量注册的（组件 + 图标），不打进入口 chunk 的话
        // 主包会超过 1.2MB 并触发体积告警；拆成独立 vendor 包后，
        // 业务代码改动不会让用户重新下载整份 UI 库。
        manualChunks: {
          'vendor-element': ['element-plus', '@element-plus/icons-vue'],
          'vendor-vue': ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
})
