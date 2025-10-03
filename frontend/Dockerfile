# -------- Build Stage --------
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Copy tracks_cache from backend to frontend assets before build
COPY backend/app/tracks_cache ./public/assets/tracks_cache
ARG ANGULAR_PROJECT=frontend
RUN npm run build -- --configuration production \
 && mkdir -p /app/build \
 && if [ -d "/app/dist/${ANGULAR_PROJECT}/browser" ]; then \
      cp -r /app/dist/${ANGULAR_PROJECT}/browser/* /app/build/; \
    elif [ -d "/app/dist/${ANGULAR_PROJECT}" ]; then \
      cp -r /app/dist/${ANGULAR_PROJECT}/* /app/build/; \
    else \
      FIRST_DIR="$(ls -d /app/dist/*/ 2>/dev/null | head -n1)"; \
      [ -n "$FIRST_DIR" ] && cp -r "$FIRST_DIR"* /app/build/ || (echo "No build output"; exit 1); \
    fi

# -------- Runtime Stage (Nginx) --------
FROM nginx:alpine
RUN rm -f /etc/nginx/conf.d/default.conf && rm -rf /usr/share/nginx/html/* \
 && printf "server {\n\
  listen 80;\n\
  server_name _;\n\
  root /usr/share/nginx/html;\n\
  index index.html;\n\
  location / {\n\
    try_files \$uri \$uri/ /index.html;\n\
  }\n\
}\n" > /etc/nginx/conf.d/spa.conf
COPY --from=build /app/build /usr/share/nginx/html
RUN if [ -f /usr/share/nginx/html/index.csr.html ]; then \
      mv /usr/share/nginx/html/index.csr.html /usr/share/nginx/html/index.html; \
    fi
EXPOSE 80