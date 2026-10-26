# Multi-stage build for the Next.js dashboard.
#
# NEXT_PUBLIC_API_BASE_URL must be the address the USER'S BROWSER can
# reach (e.g. http://localhost:8000) -- never a Docker-internal service
# name like "http://backend:8000", since Next.js inlines every
# NEXT_PUBLIC_* value into the client JS bundle at `next build` time, and
# the browser runs outside the Compose network entirely. docker-compose.yml
# passes this as a build ARG for exactly that reason.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# `output: "standalone"` (next.config.ts) traces the minimal node_modules
# this app actually needs into .next/standalone -- the full node_modules
# tree from the builder stage is never copied into this final image.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -q -O - http://127.0.0.1:3000/ >/dev/null 2>&1 || exit 1

CMD ["node", "server.js"]
