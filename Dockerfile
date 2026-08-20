FROM python:3.12-slim

WORKDIR /app

# Copia e installa solo le dipendenze necessarie per il container
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice del progetto
COPY . .

# Espone la porta dell'API FastAPI
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
