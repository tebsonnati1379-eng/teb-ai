FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ⭐ این خط جادویی باعث می‌شود داکر کش خود را پاک کند و از صفر بسازد
ARG CACHEBUST=1

COPY . .

# این خط برای دیباگ است تا در لاگ‌های ساخت ببینیم فایل‌ها کجا هستند
RUN ls -la /app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
