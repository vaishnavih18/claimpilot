# syntax=docker/dockerfile:1

# Stage 1: build the static bundle. Not shipped - only /app/dist is copied out.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: nginx serving the bundle. The "unprivileged" image runs as a
# non-root user and listens on 8080 (non-root can't bind port 80); the k8s
# Service maps 80 -> 8080.
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# Runtime config: the image is built once and the Cognito/API settings come
# from environment variables (a k8s ConfigMap) when the container starts.
# The official nginx entrypoint runs every *.sh in /docker-entrypoint.d/
# before starting nginx. config.js must be writable by the non-root user.
USER root
COPY docker-entrypoint.d/40-config.sh /docker-entrypoint.d/40-config.sh
RUN chmod +x /docker-entrypoint.d/40-config.sh \
 && chown nginx:nginx /usr/share/nginx/html/config.js
USER nginx

# Makes the base image export NGINX_LOCAL_RESOLVERS (from /etc/resolv.conf) for the
# nginx template's `resolver` line.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1

EXPOSE 8080
