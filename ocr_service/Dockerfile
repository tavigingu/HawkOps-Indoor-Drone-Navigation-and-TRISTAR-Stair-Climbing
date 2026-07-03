FROM python:3.10-slim

WORKDIR /app

# System dependencies required for OpenCV and EasyOCR
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU PyTorch first to prevent huge CUDA downloads, then install the rest
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download EasyOCR models (en and ro) during the docker build phase so it runs instantly later
RUN python -c "import easyocr; easyocr.Reader(['en', 'ro'])"

COPY app/ /app/app/

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
