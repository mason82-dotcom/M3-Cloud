FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_MAP_STYLE_URL
ARG VITE_MAP_FALLBACK_TILE_URL
ENV VITE_MAP_STYLE_URL=${VITE_MAP_STYLE_URL}
ENV VITE_MAP_FALLBACK_TILE_URL=${VITE_MAP_FALLBACK_TILE_URL}

COPY frontend/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend/ .
RUN npm run build

FROM nginx:1.29-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
