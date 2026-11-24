# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci

# Includes dev dependencies and sources: used for tests and type checks (compose service frontend-dev).
FROM deps AS dev
COPY . .

FROM dev AS build
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build --chown=node:node /app/build ./build
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node package.json ./
USER node
EXPOSE 3000
CMD ["node", "build"]
