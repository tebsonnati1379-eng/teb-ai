from fastapi import FastAPI

app = FastAPI(title="Teb AI - ربات طب سنتی")


@app.get("/")
def home():
    return {
        "status": "ok",
        "message": "سلام! ربات طب سنتی و اسلامی آماده است 🌿"
    }