FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libxcb1 \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /app/certs

# Impede publicar uma imagem que apenas abre o artefato, mas falha ao extrair
# HOG/classificar na primeira requisição. Não importa Settings nem usa segredos.
RUN python -c "from app.services.portable_knn import PortableKnnModel; c = PortableKnnModel('/app/app/assets/meter-field-v3-20260622.yml'); assert c.is_trained(); c.verify_runtime()"

ENV PORT=8000

CMD ["python", "startup.py"]
