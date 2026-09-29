# -*- coding: utf-8 -*-
"""تست اتصال به Metis AI"""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.getenv("METIS_API_KEY", "")
print(f"🔑 کلید: {API_KEY[:20]}...")
print(f"📏 طول کلید: {len(API_KEY)} کاراکتر")

# آدرس Metis
BASE_URL = "https://api.metisai.ir/openai/v1"

client = OpenAI(
    base_url=BASE_URL,
    api_key=API_KEY,
)

# لیست مدل‌هایی که باید امتحان کنیم
models_to_test = [
    "gpt-4o-mini",
    "Qwen/Qwen2.5-72B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
]

for model_name in models_to_test:
    print(f"\n🧪 تست مدل: {model_name}")
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "سلام، خودت را در یک جمله معرفی کن"}],
            max_tokens=100
        )
        print("✅ موفق:")
        print(response.choices[0].message.content)
        break
    except Exception as e:
        print(f"❌ خطا: {str(e)[:200]}")