FROM python:3.10-slim

WORKDIR /app

# Copy dependency definition
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
# Assuming the root of the context is the ai_service directory
COPY app/ /app/app/

# Expose the API port
EXPOSE 8000

# Start FastAPI using Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

