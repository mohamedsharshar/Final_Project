FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

WORKDIR /app

# تثبيت المكتبات اللازمة لـ OpenCV و Paddle و PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تحميل الموديلات مسبقاً (اختياري، لكن يفضل لعدم التحميل عند التشغيل)
# هنا نعتمد على التحميل عند أول طلب داخل الكود لتبسيط الـ Dockerfile

COPY main.py .

RUN useradd -m -u 1000 user
USER user

ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]