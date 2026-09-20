FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend/ .
RUN npm run build

FROM nginx:1.29-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
