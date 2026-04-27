# Frontend image — Next.js 15 app served via `next start` in production.
#
# Multi-stage so the final runtime image only carries the built output
# and a slim node_modules — no source, no dev deps.
#
# NEXT_PUBLIC_* variables are inlined into the JS bundle at build time,
# so we accept NEXT_PUBLIC_API_BASE as a build arg.  Browsers running
# the resulting bundle will hit that URL directly (it's the URL the
# *user's browser* sees, not the in-cluster service hostname).

# ---------- Stage 1: install deps ---------- #
FROM node:20-alpine AS deps
WORKDIR /app
COPY web/package.json web/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ---------- Stage 2: build ---------- #
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY web/ ./
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build

# ---------- Stage 3: runtime ---------- #
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Copy only what `next start` needs.
COPY --from=builder /app/public        ./public
COPY --from=builder /app/.next         ./.next
COPY --from=builder /app/node_modules  ./node_modules
COPY --from=builder /app/package.json  ./package.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs

EXPOSE 3005

CMD ["npx", "next", "start", "-p", "3005"]
