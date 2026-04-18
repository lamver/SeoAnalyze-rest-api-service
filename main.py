import os
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from seokar import Seokar

app = FastAPI(title="SEO Analyzer Professional")

# Настройка шаблонов
templates = Jinja2Templates(directory="templates")
VALIDATOR_URL = os.getenv('VALIDATOR_URL', 'http://html-validator:8888/?out=json')

class AnalyzeRequest(BaseModel):
    url: str

# --- Вспомогательная функция для сбора данных ---
def fetch_seo_data(url: str):
    # 1. Загрузка контента
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    html_content = response.text

    # 2. SEO Анализ
    analyzer = Seokar(html_content=html_content, url=url)
    seo_report = analyzer.analyze()

    # 3. Валидация HTML
    v_headers = {'Content-Type': 'text/html; charset=utf-8'}
    v_response = requests.post(VALIDATOR_URL, data=html_content.encode('utf-8'), headers=v_headers)
    html_errors = v_response.json().get('messages', [])

    return {
        "url": url,
        "seo_health": seo_report.get('seo_health', {}),
        "html_validation": {
            "total_issues": len(html_errors),
            "errors": [m for m in html_errors if m['type'] == 'error'],
            "warnings": [m for m in html_errors if (m['type'] == 'info' or m.get('subType') == 'warning')]
        },
        "meta": {
            "title": seo_report.get('basic_seo', {}).get('title'),
            "description": seo_report.get('basic_seo', {}).get('meta_description'),
        },
        "raw_data": seo_report
    }

# --- 1. Эндпоинт для JSON (для ботов и кода) ---
@app.post("/api/analyze")
def analyze_json(request: AnalyzeRequest):
    try:
        return fetch_seo_data(request.url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 2. Эндпоинт для Красивого HTML (для людей) ---
# Мы используем GET, чтобы можно было просто скинуть ссылку другу
@app.get("/view", response_class=HTMLResponse)
def analyze_view(request: Request, url: str):
    try:
        data = fetch_seo_data(url)
        # Передаем как один объект 'd'
        return templates.TemplateResponse("report.html", {"request": request, "d": data})
    except Exception as e:
        return HTMLResponse(content=f"<h1>Ошибка: {e}</h1>", status_code=500)
