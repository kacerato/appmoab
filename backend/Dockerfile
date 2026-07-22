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

# Impede publicar uma imagem incapaz de abrir o classificador embarcado. O
# runtime usa FileStorage + NumPy e não depende do módulo opcional cv2.ml.
RUN python -c "from app.services.meter_vision import _PortableKnnClassifier; c = _PortableKnnClassifier('/app/app/assets/meter-field-v3-20260622.yml'); assert c.is_trained()"

ENV PORT=8000

CMD ["python", "startup.py"]
