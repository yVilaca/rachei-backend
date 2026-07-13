FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências primeiro (camada cacheável); requirements-dev só existe em build de teste
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY . .

# Default de produção (o container de teste sobrescreve o command)
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
