# -------- Build Stage --------
FROM node:20-alpine AS build
WORKDIR /app

# (Optional) mehr RAM für den Angular Build
# ENV NODE_OPTIONS=--max_old_space_size=4096

COPY frontend/package*.json ./
RUN npm ci

# Projektcode
COPY frontend/ ./

# Name deines Angular-Projekts (Ordner unter dist/ nach Build)
ARG ANGULAR_PROJECT=frontend

# Produziere den Build
RUN npm run build -- --configuration production \
  && echo ">>> Dist root:" \
  && ls -lah /app/dist || true \
  && echo ">>> Dist project dir (if exists): /app/dist/${ANGULAR_PROJECT}" \
  && ls -lah "/app/dist/${ANGULAR_PROJECT}" || true \
  && echo ">>> Dist project/browser (if exists): /app/dist/${ANGULAR_PROJECT}/browser" \
  && ls -lah "/app/dist/${ANGULAR_PROJECT}/browser" || true \
  && mkdir -p /app/build \
  && if [ -d "/app/dist/${ANGULAR_PROJECT}/browser" ]; then \
       echo "Using /app/dist/${ANGULAR_PROJECT}/browser"; \
       cp -r /app/dist/${ANGULAR_PROJECT}/browser/* /app/build/; \
     elif [ -d "/app/dist/${ANGULAR_PROJECT}" ]; then \
       echo "Using /app/dist/${ANGULAR_PROJECT}"; \
       cp -r /app/dist/${ANGULAR_PROJECT}/* /app/build/; \
     else \
       echo "Project dir not found, falling back to first dist subdir"; \
       FIRST_DIR="$(ls -d /app/dist/*/ 2>/dev/null | head -n1)"; \
       if [ -n "$FIRST_DIR" ]; then \
         echo "Using $FIRST_DIR"; \
         cp -r "$FIRST_DIR"* /app/build/; \
       else \
         echo "ERROR: no build output found under /app/dist"; \
         exit 1; \
       fi; \
     fi

# -------- Runtime Stage (Nginx) --------
FROM nginx:alpine
# Statische Dateien bereitstellen
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
