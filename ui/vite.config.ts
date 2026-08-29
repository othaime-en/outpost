import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    server: {
        port: 3000,
        // allow all host for cloudflare tunnelling
        allowedHosts: true,
        // Proxy API calls from the dev server to FastAPI.
        // This means the React app can call `/api/environments` in development
        // and Vite will forward it to http://localhost:8000/environments —
        // avoiding CORS issues entirely during local development.
        proxy: {
            '/api': {
                target: process.env.VITE_API_URL ?? 'http://localhost:8000',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, ''),
            },
        },
    },
})