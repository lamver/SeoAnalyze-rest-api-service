import asyncio
import json
from urllib.parse import urlparse
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

async def main():
    base_url = "https://datahunter.store"
    domain = urlparse(base_url).netloc
    max_depth = 2  # Укажите нужную глубину
    
    visited_urls = set()
    to_crawl = {base_url}
    all_reports = []

    async with AsyncWebCrawler() as crawler:
        config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

        for depth in range(max_depth + 1):
            if not to_crawl:
                break
            
            print(f"--- Анализ уровня {depth}. Страниц: {len(to_crawl)} ---")
            
            # Запускаем пачку URL текущего уровня
            current_urls = list(to_crawl)
            results = await crawler.arun_many(current_urls, config=config)
            
            visited_urls.update(current_urls)
            to_crawl = set() # Очищаем очередь для следующего уровня

            for res in results:
                if not res.success:
                    continue

                # 1. Анализируем текущую страницу
                analysis = {
                    "url": res.url,
                    "depth": depth,
                    "title": res.metadata.get('title', ''),
                    "warnings": []
                }
                
                # Мини-аудит
                if not analysis["title"]: analysis["warnings"].append("No Title")
                if res.status_code >= 400: analysis["warnings"].append(f"Broken link: {res.status_code}")
                
                all_reports.append(analysis)

                # 2. Собираем ссылки для следующего уровня (если еще не предел глубины)
                if depth < max_depth:
                    internal_links = res.links.get("internal", [])
                    for link in internal_links:
                        href = link["href"]
                        # Проверяем, что ссылка ведет на тот же домен и мы там еще не были
                        if domain in href and href not in visited_urls:
                            to_crawl.add(href)

        # Сохраняем всё в один файл
        with open("deep_seo_report.json", "w", encoding="utf-8") as f:
            json.dump(all_reports, f, ensure_ascii=False, indent=4)
        
        print(f"\nГотово! Проверено страниц: {len(all_reports)}")
        print("Результаты в deep_seo_report.json")

if __name__ == "__main__":
    asyncio.run(main())