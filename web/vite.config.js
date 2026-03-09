import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
    plugins: [react()],
    build: {
        outDir: "dist",
        emptyOutDir: true
    },
    server: {
        port: 5173,
        proxy: {
            "^/(stats|active-jobs|history|config|current-chats|auth|chats|available-chats|enabled-chats)": {
                target: "http://localhost:8080",
                changeOrigin: true
            }
        }
    }
});
