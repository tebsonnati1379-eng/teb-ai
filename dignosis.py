# -*- coding: utf-8 -*-
"""
موتور تشخیص مزاج و بیماری
"""

def detect_mizaj(answers: dict) -> dict:
    score = {"گرم": 0, "سرد": 0, "تر": 0, "خشک": 0}

    temp = answers.get("body_temp")
    if temp == "گرم": score["گرم"] += 3
    elif temp == "سرد": score["سرد"] += 3

    thirst = answers.get("thirst")
    if thirst == "زیاد": score["گرم"] += 2; score["خشک"] += 1
    elif thirst == "کم": score["سرد"] += 2; score["تر"] += 1

    mood = answers.get("mood")
    if mood == "عصبانی و پرانرژی": score["گرم"] += 2; score["خشک"] += 2
    elif mood == "آرام و کم‌حرف": score["سرد"] += 2; score["تر"] += 1
    elif mood == "مضطرب": score["خشک"] += 2; score["گرم"] += 1

    skin = answers.get("skin")
    if skin == "خشک": score["خشک"] += 3
    elif skin == "چرب": score["تر"] += 3
    elif skin == "مخلوط": score["خشک"] += 1; score["تر"] += 1

    sleep = answers.get("sleep")
    if sleep == "کم و سبک": score["خشک"] += 2; score["گرم"] += 1
    elif sleep == "زیاد و سنگین": score["تر"] += 2; score["سرد"] += 1
    elif sleep == "بی‌خوابی": score["خشک"] += 3

    stool = answers.get("stool")
    if stool == "یبوست": score["خشک"] += 3
    elif stool == "اسهال": score["تر"] += 2; score["سرد"] += 1

    hair = answers.get("hair")
    if hair == "خشک و شکننده": score["خشک"] += 2
    elif hair == "چرب": score["تر"] += 2
    elif hair == "ریزش زیاد": score["خشک"] += 1; score["سرد"] += 1

    energy = answers.get("energy")
    if energy == "بالا": score["گرم"] += 2
    elif energy == "پایین": score["سرد"] += 2

    appetite = answers.get("appetite")
    if appetite == "زیاد": score["گرم"] += 2
    elif appetite == "کم": score["سرد"] += 2

    digestion = answers.get("digestion")
    if digestion == "سریع": score["گرم"] += 1; score["خشک"] += 1
    elif digestion == "کند": score["سرد"] += 2; score["تر"] += 1
    elif digestion == "نفخ و سنگینی": score["تر"] += 2; score["سرد"] += 1

    hot_cold = "گرم" if score["گرم"] > score["سرد"] else "سرد"
    wet_dry = "خشک" if score["خشک"] > score["تر"] else "تر"

    mizaj_map = {
        ("گرم", "خشک"): "صفراوی",
        ("گرم", "تر"): "دموی",
        ("سرد", "تر"): "بلغمی",
        ("سرد", "خشک"): "سوداوی"
    }
    mizaj = mizaj_map.get((hot_cold, wet_dry), "معتدل")
    return {"mizaj": mizaj, "hot_cold": hot_cold, "wet_dry": wet_dry, "score": score}


def calculate_bmi(weight, height_cm):
    try:
        h = float(height_cm) / 100
        bmi = float(weight) / (h * h)
        if bmi < 18.5: cat = "کمبود وزن"
        elif bmi < 25: cat = "وزن نرمال"
        elif bmi < 30: cat = "اضافه وزن"
        else: cat = "چاقی"
        return round(bmi, 1), cat
    except Exception:
        return None, "نامشخص"


DISEASE_KEYWORDS = {
    "کبد چرب": ["کبد چرب", "چربی کبد", "کبد"],
    "دیابت": ["دیابت", "قند خون", "قند بالا"],
    "فشار خون": ["فشار خون", "پرفشاری"],
    "چربی خون": ["چربی خون", "کلسترول", "تری گلیسیرید"],
    "یبوست": ["یبوست", "دفع سخت"],
    "سردرد": ["سردرد", "میگرن", "سر درد"],
    "اضطراب": ["اضطراب", "استرس", "نگرانی", "دلشوره"],
    "افسردگی": ["افسردگی", "غم"],
    "بی‌خوابی": ["بی‌خوابی", "خواب"],
    "کم‌خونی": ["کم‌خونی", "آنمی"],
    "معده": ["معده", "نفخ", "سوزش معده", "رفلاکس"],
    "مفاصل": ["مفاصل", "درد زانو", "آرتروز"],
    "ریزش مو": ["ریزش مو", "کم‌پشتی مو"]
}


def detect_disease(complaint_text: str):
    if not complaint_text:
        return None, []
    matches = []
    for disease, keywords in DISEASE_KEYWORDS.items():
        for kw in keywords:
            if kw in complaint_text:
                matches.append(disease)
                break
    return (matches[0] if matches else None), matches