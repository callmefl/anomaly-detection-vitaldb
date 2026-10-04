FROM python:3.12-slim

WORKDIR /app

# 1. Pre-installa PyTorch CPU-only (~180 MB anziché ~4 GB con runtime CUDA)
RUN pip install --no-cache-dir torch>=2.0 --index-url https://download.pytorch.org/whl/cpu

# 2. Copia e installa le restanti dipendenze applicative
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice del progetto
COPY . .

# Espone la porta dell'API FastAPI
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
