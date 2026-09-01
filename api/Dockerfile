FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Overridden by docker-compose.yml to add --reload for dev.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]