FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md requirements.txt ./
COPY config ./config
COPY src ./src
RUN pip install --no-cache-dir -e .
COPY data/demo ./data/demo
COPY --from=ui /ui/dist ./frontend/dist
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["sitewatch", "ui"]
