FROM node:20-alpine

WORKDIR /app

# bun.lock is the lockfile this project ships, but npm resolves the same
# package.json and avoids adding a second toolchain to the image.
COPY package.json ./
RUN npm install

COPY . .

# 5173 deliberately: FRONTEND_BASE_URL and the OAuth allow-lists registered with
# Google, Microsoft, GitHub, Slack and Zoom all point at this port. Changing it
# means re-registering redirect URLs with five providers.
EXPOSE 5173

CMD ["npm", "run", "dev"]
