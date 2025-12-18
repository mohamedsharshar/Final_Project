FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy app
COPY main.py .

# Create non-root user for HF Spaces
RUN useradd -m -u 1000 user
USER user

ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
