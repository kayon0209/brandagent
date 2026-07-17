FROM node:20-alpine AS dependencies
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:20-alpine AS build
WORKDIR /app
RUN corepack enable
ARG NEXT_PUBLIC_BRANDFLOW_API_URL
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ARG BRANDFLOW_AGENT_INTERNAL_URL=http://agent-api:8000
ENV NEXT_PUBLIC_BRANDFLOW_API_URL=$NEXT_PUBLIC_BRANDFLOW_API_URL
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV BRANDFLOW_AGENT_INTERNAL_URL=$BRANDFLOW_AGENT_INTERNAL_URL
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
EXPOSE 3000
CMD ["./node_modules/.bin/next", "start", "-H", "0.0.0.0"]
