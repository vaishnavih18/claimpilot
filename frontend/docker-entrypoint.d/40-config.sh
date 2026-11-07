#!/bin/sh
# Writes /usr/share/nginx/html/config.js (loaded by index.html before the
# app) from environment variables. None of these values are secrets.
#   API_BASE_URL     "" (default) = same origin; the ALB/nginx routes /api
#   COGNITO_DOMAIN   https://<prefix>.auth.<region>.amazoncognito.com
#   COGNITO_APP_CLIENT_ID  the frontend app client ID (same key as k8s/config.yaml;
#                          COGNITO_CLIENT_ID is accepted as a fallback)
#   GOOGLE_LOGIN     "true" shows the Sign in with Google button
set -eu

# Escape backslash and double quote so a value can't break out of the JS string.
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

cat > /usr/share/nginx/html/config.js <<JS
window.__CLAIMPILOT_CONFIG__ = {
  apiBaseUrl: "$(esc "${API_BASE_URL:-}")",
  cognitoDomain: "$(esc "${COGNITO_DOMAIN:-}")",
  cognitoClientId: "$(esc "${COGNITO_APP_CLIENT_ID:-${COGNITO_CLIENT_ID:-}}")",
  googleLogin: "$(esc "${GOOGLE_LOGIN:-}")"
};
JS
echo "40-config.sh: wrote config.js"
