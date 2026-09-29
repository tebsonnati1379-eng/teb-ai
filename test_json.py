# -*- coding: utf-8 -*-
"""تست فایل knowledge.json"""
import json

try:
    with open("knowledge.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    diseases = data.get("diseases", {})
    print(f"✅ فایل JSON سالم است")
    print(f"📊 تعداد بیماری‌ها: {len(diseases)}")
    print(f"\n📋 لیست بیماری‌ها:")
    for i, name in enumerate(diseases.keys(), 1):
        print(f"  {i}. {name}")
    
    # بررسی وجود بیماری‌های جدید
    print(f"\n🔍 بررسی بیماری‌های جدید:")
    for check in ["چربی مو", "افتادگی پا", "درد پا", "ریزش موی چرب"]:
        if check in diseases:
            print(f"  ✅ {check}: موجود")
        else:
            print(f"  ❌ {check}: پیدا نشد")

except json.JSONDecodeError as e:
    print(f"❌ خطای JSON در خط {e.lineno}، ستون {e.colno}:")
    print(f"   {e.msg}")
    print(f"\n💡 راهنما: به خط {e.lineno} فایل knowledge.json بروید و اشکال را برطرف کنید.")
except FileNotFoundError:
    print("❌ فایل knowledge.json پیدا نشد!")
except Exception as e:
    print(f"❌ خطای دیگر: {e}")