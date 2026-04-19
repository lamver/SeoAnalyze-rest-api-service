import os
import requests
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from seokar import Seokar
from datetime import datetime
import traceback

app = FastAPI(title="SEO Analyzer Professional")

@app.middleware("http")
async def trace_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        # Это выведет ВСЮ ошибку в браузер в виде текста
        return PlainTextResponse(traceback.format_exc(), status_code=500)
    
# Настройка шаблонов
templates = Jinja2Templates(directory="app/templates")

# Добавляем пользовательские фильтры для Jinja2
def truncate_filter(s, length=100):
    if s and len(s) > length:
        return s[:length] + '...'
    return s

#templates.env.filters["truncate"] = truncate_filter

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

   # Собираем данные
    data = {
        "url": url,
        "seo_health": seo_report.get('seo_health', {}),
        "html_validation": {
            "total_issues": len(html_errors),
            "errors": [m for m in html_errors if m['type'] == 'error']
        },
        "meta": {
            "title": seo_report.get('basic_seo', {}).get('title', 'N/A'),
            "description": seo_report.get('basic_seo', {}).get('meta_description', 'N/A')
        },
        "headings": seo_report.get('headings', {}).get('all_headings', {})
    }
    
    # КРИТИЧЕСКИЙ МОМЕНТ: Превращаем всё в чистый JSON-словарь без объектов классов
    return json.loads(json.dumps(data, default=str))

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
        # Получаем данные
        data = fetch_seo_data(url)
        
        # ВАЖНО: Jinja2 иногда глючит, если передавать словари через именованные аргументы
        # Попробуем передать через явный словарь контекста
        return templates.TemplateResponse(
            request=request,               # 1. Передаем request ОТДЕЛЬНО
            name="report.html",       # 2. Имя шаблона
            context={                      # 3. Остальные данные
                "url": str(data.get("url")),
                "score": str(data.get("seo_health", {}).get("score", "0")),
                "title": str(data.get("meta", {}).get("title", "N/A")),
                "total_errors": str(data.get("html_validation", {}).get("total_issues", "0")),
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        )
    except Exception as e:
        return HTMLResponse(content=f"<h1>Ошибка: {e}</h1>", status_code=500)
