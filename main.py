import os
import requests
import json
from fastapi import FastAPI, HTTPException, Request, Response, Body
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from seokar import Seokar
from datetime import datetime
import traceback
from urllib.parse import urljoin, urlparse
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
import httpx

app = FastAPI(title="SEO Analyzer Professional")

@app.middleware("http")
async def trace_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        # Это выведет ВСЮ ошибку в браузер в виде текста
        return PlainTextResponse(traceback.format_exc(), status_code=500)
    
# Настройка шаблонов
templates = Jinja2Templates(directory="templates")

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
async def fetch_seo_data(url: str) -> dict:
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) SEO-Analyzer/1.0'}
    
    # Используем асинхронный клиент httpx вместо requests
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=10.0)
        response.raise_for_status()
        html_content = response.text
    
    # Обязательно добавляем await, так как process_html_content теперь асинхронная
    return await process_html_content(html_content, url=url)


@app.post("/api/analyze-html")
async def analyze_raw_html(html_content: str = Body(..., media_type="text/html")):
    try:
        if not html_content.strip():
            raise HTTPException(status_code=400, detail="Тело запроса пустое. Пришлите HTML-код.")
            
        # Так как html_content теперь сразу строка, разбирать request.body() вручную не нужно
        report_data = await process_html_content(html_content)
        return jsonable_encoder(report_data)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка анализа HTML: {str(e)}")

async def process_html_content(html_content: str, url: str = "http://localhost") -> dict:
    """Анализирует HTML-код и отправляет его на валидацию."""
    # 1. Анализ через Seokar (БЕЗ await, так как библиотека синхронная)
    analyzer = Seokar(html_content=html_content, url=url)
    report = analyzer.analyze()  # <-- Убрали await здесь

    # 2. Валидация HTML через асинхронный клиент (Здесь await нужен!)
    try:
        async with httpx.AsyncClient() as client:
            v_headers = {'Content-Type': 'text/html; charset=utf-8'}
            v_response = await client.post(
                VALIDATOR_URL, 
                content=html_content.encode('utf-8'), 
                headers=v_headers, 
                timeout=5.0
            )
            html_validation = v_response.json().get('messages', [])
    except Exception:
        html_validation = [{"message": "Validator unavailable", "type": "error"}]

    report['html_validation'] = html_validation
    return report

# --- 1. Эндпоинт для JSON (для ботов и кода) ---
@app.post("/api/analyze")
async def analyze_json(payload: AnalyzeRequest):  # Добавили async и переименовали переменную для ясности
    try:
        url_str = str(payload.url)
        # Добавляем await перед вызовом асинхронной функции
        report_data = await fetch_seo_data(url_str)
        return jsonable_encoder(report_data)
        
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=400, detail=f"Сайт вернул ошибку: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка анализа: {str(e)}")

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

def get_links(url, base_domain):
    """Вспомогательная функция для сбора внутренних ссылок на странице"""
    try:
        res = requests.get(url, timeout=5, headers={'User-Agent': 'Sitemap-Generator/1.0'})
        soup = BeautifulSoup(res.text, 'html.parser')
        links = set()
        for a in soup.find_all('a', href=True):
            full_url = urljoin(url, a['href']).split('#')[0].rstrip('/')
            # Проверяем, что ссылка ведет на тот же домен
            if urlparse(full_url).netloc == base_domain:
                links.add(full_url)
        return links
    except:
        return set()

@app.get("/sitemap.xml")
async def generate_sitemap(url: str, max_depth: int = 1):
    # Crawl4AI автоматически классифицирует ссылки
    parsed_input = urlparse(url)
    main_domain = ".".join(parsed_input.netloc.split('.')[-2:])
    visited = {url.rstrip('/')}
    to_visit = [url.rstrip('/')]

    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        for _ in range(max_depth):
            new_links = []
            for current_url in to_visit:
                # Crawl4AI обрабатывает динамический контент и JS
                result = await crawler.arun(url=current_url, config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS))
                
                if result.success:
                    for link_data in result.links.get("internal", []):
                        href = link_data.get("href", "").rstrip('/')
                        if href and href not in visited and main_domain in urlparse(href).netloc:
                            visited.add(href)
                            new_links.append(href)
            to_visit = new_links
            if not to_visit: break

    # Формирование XML
    url_tags = "\n".join([f"    <url><loc>{link}</loc></url>" for link in sorted(visited)])
    sitemap_xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://sitemaps.org">\n{url_tags}\n</urlset>'
    return Response(content=sitemap_xml, media_type="application/xml")

@app.get("/debug-content")
async def debug_content(url: str):
    # Настраиваем браузер так, чтобы он не выглядел как бот
    browser_config = BrowserConfig(
        headless=True,
        # Это база для обхода детекта
        extra_args=["--disable-blink-features=AutomationControlled"],
        # Игнорируем проблемы с SSL на дев-стендах
        ignore_https_errors=True
    )

    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        # Вместо magic_mode используем эмуляцию ожидания
        wait_until="networkidle",
        # Даем время на выполнение тяжелых скриптов
        page_timeout=30000 
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)
        
        if result.success:
            return PlainTextResponse(result.html)
        
        # Выводим детали, если не пробились
        return PlainTextResponse(
            f"Status: {result.status_code}\nError: {result.error_message}\nHTML: {result.html[:300]}", 
            status_code=500
        )