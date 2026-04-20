import os
import requests
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from seokar import Seokar
from datetime import datetime
import traceback
from fastapi import Response
from fastapi.responses import PlainTextResponse
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from urllib.parse import urlparse

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
def fetch_seo_data(url: str):
    # 1. Загрузка контента
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) SEO-Analyzer/1.0'}
    response = requests.get(url, timeout=10, headers=headers)
    response.raise_for_status()
    html_content = response.text

    # 2. Анализ (библиотека сама соберет все данные)
    analyzer = Seokar(html_content=html_content, url=url)
    report = analyzer.analyze()

    # 3. Валидация HTML (добавляем её отдельным ключом в общий отчет)
    try:
        v_headers = {'Content-Type': 'text/html; charset=utf-8'}
        v_response = requests.post(VALIDATOR_URL, data=html_content.encode('utf-8'), headers=v_headers, timeout=5)
        html_validation = v_response.json().get('messages', [])
    except Exception:
        html_validation = "Validator unavailable"

    # Добавляем валидацию прямо в основной отчет
    report['html_validation_raw'] = html_validation

    # 4. Выплевываем ВСЁ в JSON
    # jsonable_encoder превратит все вложенные объекты и специфические типы данных в чистый dict
    return jsonable_encoder(report)


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

@app.get("/debug-content") # Временно сменим имя, чтобы не путать с sitemap
async def debug_content(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()
        
        print(f">>> Захожу на: {url}")
        try:
            # Ждем загрузки
            await page.goto(url, wait_until="networkidle", timeout=20000)
            
            # Если это SPA, даем пару секунд на рендер
            await page.wait_for_timeout(2000) 
            
            # Получаем ВЕСЬ отрендеренный HTML
            raw_html = await page.content()
            
            await browser.close()
            
            # Возвращаем как обычный текст, чтобы браузер не пытался это исполнить
            return PlainTextResponse(raw_html)
            
        except Exception as e:
            await browser.close()
            return PlainTextResponse(f"Ошибка: {str(e)}")
        