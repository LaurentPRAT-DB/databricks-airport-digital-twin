import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { execSync } from 'child_process'
import { readFileSync } from 'fs'

const pkg = JSON.parse(readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'))
let buildNumber = '0'
try {
  buildNumber = execSync('git rev-list --count HEAD', { encoding: 'utf-8' }).trim()
} catch { /* not in a git repo */ }
const buildTime = new Date().toISOString()

// https://vitejs.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __BUILD_NUMBER__: JSON.stringify(buildNumber),
    __BUILD_TIME__: JSON.stringify(buildTime),
  },
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1000,
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          // Split Three.js and 3D libraries into separate chunk
          three: ['three', '@react-three/fiber', '@react-three/drei'],
          // Split Leaflet/2D map into separate chunk
          leaflet: ['leaflet', 'react-leaflet'],
          // Split React core
          react: ['react', 'react-dom'],
        },
      },
    },
  },
})
