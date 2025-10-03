FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
# Install all deps (including devDependencies needed for build like react-scripts)
# Using npm install instead of npm ci to handle any lock file sync issues
RUN npm install
COPY . .
# Build the React app
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=8080
COPY --from=build /app/package*.json ./
RUN npm install --omit=dev
COPY --from=build /app/build ./build
COPY server.js ./
EXPOSE 8080
CMD ["node", "server.js"]
