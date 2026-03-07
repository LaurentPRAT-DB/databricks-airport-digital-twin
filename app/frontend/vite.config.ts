import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
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
