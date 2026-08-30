FROM node:22-alpine AS dependencies
WORKDIR /app
RUN npm install --global pnpm@11.22.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS build
WORKDIR /app
RUN npm install --global pnpm@11.22.0
ARG NEXT_PUBLIC_BRANDFLOW_API_URL
# Format-valid placeholder (decodes to "docker-build-placeholder.clerk.example$"):
# Clerk validates key STRUCTURE at build time but never contacts the API
# during static prerender, so the image builds reproducibly without secrets.
# Real deployments pass their public key via --build-arg.
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_ZG9ja2VyLWJ1aWxkLXBsYWNlaG9sZGVyLmNsZXJrLmV4YW1wbGUk
ARG BRANDFLOW_AGENT_INTERNAL_URL=http://agent-api:8000
ENV NEXT_PUBLIC_BRANDFLOW_API_URL=$NEXT_PUBLIC_BRANDFLOW_API_URL
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV BRANDFLOW_AGENT_INTERNAL_URL=$BRANDFLOW_AGENT_INTERNAL_URL
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
EXPOSE 3000
CMD ["./node_modules/.bin/next", "start", "-H", "0.0.0.0"]
