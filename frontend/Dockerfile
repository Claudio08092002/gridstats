# -------- Build Stage --------
FROM node:20-alpine AS build
WORKDIR /app

# Optional, falls Builds viel RAM brauchen:
# ENV NODE_OPTIONS=--max_old_space_size=4096

COPY frontend/package*.json ./
RUN npm ci

# Projektcode
COPY frontend/ ./

# Name deines Angular-Projekts (Ordner unter dist/)
ARG ANGULAR_PROJECT=frontend

# Produziere den Build (klassisch SPA)
RUN npm run build -- --configuration production

# Robust: kopiere das Build-Resultat in /app/build
# - Angular 16+ (non-SSR): dist/<project>
# - Angular 16+ (builder mit SSR): dist/<project>/browser
RUN if [ -d "/app/dist/${ANGULAR_PROJECT}/browser" ]; then \
      echo "Using dist/${ANGULAR_PROJECT}/browser"; \
      cp -r /app/dist/${ANGULAR_PROJECT}/browser /app/build; \
    else \
      echo "Using dist/${ANGULAR_PROJECT}"; \
      cp -r /app/dist/${ANGULAR_PROJECT} /app/build; \
    fi

# -------- Runtime Stage (Nginx) --------
FROM nginx:alpine

# Statische Files bereitstellen
COPY --from=build /app/build /usr/share/nginx/html

# Healthcheck optional (curl installieren oder weglassen)
# RUN apk add --no-cache curl
# HEALTHCHECK CMD curl -fsS http://127.0.0.1/ || exit 1

# Expose ist optional; Compose mapped den Port
EXPOSE 80
