FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /app/certs

# Railway usa PORT dinâmico via env var
ENV PORT=8000

EXPOSE ${PORT}

# Script de startup que cria certs a partir de env vars se necessário
COPY start.sh .
RUN chmod +x start.sh

CMD ["./start.sh"]
