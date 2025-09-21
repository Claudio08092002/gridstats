# -------- Build Stage --------
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Falls dein Projektname anders ist, via ARG steuern
ARG ANGULAR_PROJECT=frontend
RUN npm run build -- --configuration production

# -------- Runtime Stage (Nginx) --------
FROM nginx:alpine
# Nginx Config mit API-Proxy
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
# Statische Files kopieren (Angular 16+: dist/<project>/browser)
ARG ANGULAR_PROJECT=frontend
COPY --from=build /app/dist/${ANGULAR_PROJECT}/browser /usr/share/nginx/html
# Optional: Healthcheck
HEALTHCHECK CMD wget -qO- http://127.0.0.1/ || exit 1
