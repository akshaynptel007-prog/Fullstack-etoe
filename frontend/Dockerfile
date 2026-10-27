# syntax=docker/dockerfile:1.7
# Build context: repository root (needs ./frontend and ./nginx).
#   docker build -f frontend/Dockerfile .                 -> NGINX image (local stack)
#   docker build -f frontend/Dockerfile --target build .  -> just the SPA (deploy.sh -> S3)

FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
# The bundle budget is part of the build: an oversized bundle never ships.
RUN npm run build && npm run check:size

FROM nginx:1.28-alpine AS runtime
ENV API_UPSTREAM=api:8000 \
    NGINX_RESOLVER=127.0.0.11 \
    NGINX_API_RATE=100r/s \
    NGINX_API_BURST=200 \
    NGINX_CHECKOUT_RATE=20r/s \
    NGINX_CHECKOUT_BURST=40 \
    NGINX_BOT_FILTER=1 \
    NGINX_ACCESS_LOG=all
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/snippets /etc/nginx/snippets
COPY nginx/templates /etc/nginx/templates
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
