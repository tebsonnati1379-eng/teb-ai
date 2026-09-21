FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی صریح تمام فایل‌های پایتون برای جلوگیری از مشکل کش داکر
COPY main.py .
COPY database.py .
COPY diagnosis.py .
COPY knowledge.py .

# کپی بقیه فایل‌ها
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
