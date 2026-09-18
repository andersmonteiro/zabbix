FROM node:20-slim

# Dependências do Chromium para o whatsapp-web.js
RUN apt-get update && apt-get install -y \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libnss3 \
    libnspr4 \
    libatspi2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxshmfence1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY server.js .

EXPOSE 3000

CMD ["node", "server.js"]
