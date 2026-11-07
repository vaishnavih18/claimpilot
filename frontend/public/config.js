// Runtime config, overwritten in the nginx container at start-up (see
// docker-entrypoint.d/40-config.sh) from environment variables. Empty here
// so local `npm run dev` falls back to the VITE_* variables in .env.
window.__CLAIMPILOT_CONFIG__ = {};
