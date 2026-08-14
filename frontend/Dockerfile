# Node 20, not 18: @tailwindcss/oxide (the Rust engine behind Tailwind v4)
# declares "engines.node": ">= 20", so an 18 base is not a supported build
# platform for this dependency set. Vite 5 accepts both.
FROM node:20-bookworm-slim AS build

WORKDIR /app

# Dependencies are installed from the lockfile inside Linux so npm resolves the
# linux-x64 native binaries for Tailwind's oxide engine. Copying host
# node_modules would drop Windows/macOS binaries into a Linux image.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

# Serves the built SPA on :3000 and proxies /api to the backend container.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
