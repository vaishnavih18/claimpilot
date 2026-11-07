import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// strictPort: Cognito callback URLs are exact-match
// (http://localhost:5173/callback), so the dev server must not silently
// move to another port if 5173 is busy.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true },
});
