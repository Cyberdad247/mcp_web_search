FROM python:3.12-alpine

# Install system dependencies (Playwright/Chromium runtime + build tools)
RUN apk add --no-cache \
    xvfb-run xvfb chromium nss freetype harfbuzz ttf-freefont \
    gcompat libstdc++ libuuid gcc musl-dev python3-dev libffi-dev g++ make \
    bash

WORKDIR /app
COPY . .

# Prefer installing project requirements; add any extra packages here if needed
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
ENV BROWSER_PATH=/usr/bin/chromium-browser
ENV DISPLAY=:99

RUN pip install --no-cache-dir -r requirements.txt

# Entrypoint: run the MCP server inside a virtual X frame buffer
ENTRYPOINT ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1280x960x24", "python", "-m", "mcp_integration.server"]
