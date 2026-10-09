# Node 20, not 18: @tailwindcss/oxide (the Rust engine behind Tailwind v4)
# declares "engines.node": ">= 20", so an 18 base is not a supported build
# platform for this dependency set (React Router 7 also requires Node 20+).
FROM node:20-bookworm-slim AS build

WORKDIR /app

# Dependencies are installed from the lockfile inside Linux so npm resolves the
# linux-x64 native binaries for Tailwind's oxide engine. Copying host
# node_modules would drop Windows/macOS binaries into a Linux image.
COPY package.json package-lock.json ./
# esbuild's install script runs its own binary straight after writing it, and
# on Docker Desktop that occasionally fails with ETXTBSY ("text file busy").
# npm also skips an optional native package silently when its download fails
# (2.2.1: lightningcss-linux-x64-gnu went missing and the build broke later).
# So: install, prove the native modules load, and reinstall cleanly once if not.
RUN (npm ci || (rm -rf node_modules && npm ci)) \
    && (node -e "require('lightningcss'); require('@tailwindcss/oxide'); require('rollup')" \
        || (rm -rf node_modules && npm ci \
            && node -e "require('lightningcss'); require('@tailwindcss/oxide'); require('rollup')"))

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

# Serves the built SPA on :3000 and proxies /api to the backend container.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/foriflow-security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html

# Run as the image's unprivileged "nginx" user (uid 101) instead of root:
# drop the "user" directive (only root may switch users), move the pid file to
# a writable place and give nginx its cache and content directories.
RUN sed -i -e '/^user /d' -e 's,^pid .*,pid /tmp/nginx.pid;,' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /var/cache/nginx /usr/share/nginx/html
USER nginx

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
