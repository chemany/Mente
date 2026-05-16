#!/usr/bin/env python3
"""
每日新闻生成脚本
使用 Tavily API 获取国际新闻，生成爆款标题，保存为 Markdown

用法:
    python3 generate_daily_news.py [--date YYYY-MM-DD] [--output-dir DIR]

环境变量:
    TAVILY_API_KEY: Tavily API Key
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from _agent_home import display_agent_home, get_agent_env_path, get_default_output_dir

# 尝试导入 requests，如果没有则使用 urllib
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request
    import urllib.error


# RSS 源配置
RSS_SOURCES = {
    "bbc_world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc_top": "https://feeds.bbci.co.uk/news/rss.xml",
    "bbc_business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "bbc_tech": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "al_jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}


def get_tavily_api_key():
    """获取 Tavily API Key"""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        # 尝试从 .env 文件读取
        env_file = get_agent_env_path()
        if env_file.exists():
            content = env_file.read_text()
            match = re.search(r'TAVILY_API_KEY=(.+)', content)
            if match:
                api_key = match.group(1).strip()
    return api_key


def get_tavily_api_url():
    """获取 Tavily API URL，支持从环境变量或 .env 文件读取"""
    url = os.environ.get("TAVILY_API_URL", "").strip()
    if not url:
        env_file = get_agent_env_path()
        if env_file.exists():
            env_content = env_file.read_text()
            match = re.search(r'TAVILY_API_URL=(.+)', env_content)
            if match:
                url = match.group(1).strip()
    return url or "https://api.tavily.com/search"


def tavily_search(query, max_results=10, topic="news", time_range="day"):
    """使用 Tavily API 搜索新闻"""
    api_key = get_tavily_api_key()
    if not api_key:
        print("❌ 未找到 TAVILY_API_KEY")
        return None
    
    url = get_tavily_api_url()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "query": query,
        "search_depth": "advanced",
        "topic": topic,
        "max_results": max_results,
        "include_answer": True,
        "time_range": time_range,
        "include_raw_content": True
    }
    
    try:
        if HAS_REQUESTS:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            return response.json()
        else:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"❌ Tavily 搜索失败: {e}")
        return None


def fetch_rss_feed(url):
    """获取 RSS feed"""
    try:
        if HAS_REQUESTS:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        else:
            with urllib.request.urlopen(url, timeout=10) as response:
                return response.read().decode('utf-8')
    except Exception as e:
        print(f"⚠️ RSS 获取失败 {url}: {e}")
        return None


def parse_rss_items(xml_content):
    """解析 RSS XML，提取新闻条目"""
    if not xml_content:
        return []
    
    items = []
    # 简单的正则提取
    title_matches = re.findall(r'<title>([^<]+)</title>', xml_content)
    desc_matches = re.findall(r'<description>([^<]+)</description>', xml_content)
    link_matches = re.findall(r'<link>([^<]+)</link>', xml_content)
    
    # 跳过第一个（通常是 feed 标题）
    for i in range(1, min(len(title_matches), len(desc_matches), len(link_matches))):
        title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title_matches[i])
        desc = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', desc_matches[i])
        link = link_matches[i]
        
        # 清理 HTML 标签
        desc = re.sub(r'<[^>]+>', '', desc)
        
        items.append({
            "title": title.strip(),
            "description": desc.strip(),
            "url": link.strip()
        })
    
    return items


def generate_viral_title(news_items):
    """生成爆款风格标题"""
    if not news_items:
        return "今日国际要闻速览"
    
    # 取第一条新闻
    top_news = news_items[0]
    title = top_news.get("title", "")
    
    # 爆款标题公式：[时间/程度词] + [核心事件] + [关键影响/反应]
    prefixes = ["突发", "震惊", "重磅", "刚刚", "全球", "2026"]
    suffixes = ["引发关注", "影响深远", "局势紧张", "各方反应强烈", "市场震荡"]
    
    # 简化处理：取原标题核心部分
    # 移除常见前缀
    title = re.sub(r'^(BBC|Reuters|Al Jazeera)[\s:]+', '', title, flags=re.I)
    
    # 构建爆款标题
    prefix = prefixes[hash(title) % len(prefixes)]
    
    # 限制长度
    if len(title) > 25:
        title = title[:25] + "..."
    
    viral_title = f"{prefix}：{title}"
    
    return viral_title


def categorize_news(news_items):
    """将新闻分类"""
    categories = {
        "🔥 国际要闻": [],
        "💼 商业财经": [],
        "🚀 科技动态": [],
        "📌 其他要闻": []
    }
    
    business_keywords = ["economy", "economic", "market", "trade", "business", "finance", "financial", "stock", "investment", "GDP", "inflation", "bank", "company", "企业", "市场", "经济", "金融", "贸易", "投资"]
    tech_keywords = ["technology", "tech", "AI", "artificial intelligence", "digital", "cyber", "internet", "software", "app", "smartphone", "科技", "人工智能", "数字化", "互联网", "软件"]
    
    for item in news_items[:15]:  # 最多取 15 条
        title = item.get("title", "").lower()
        desc = item.get("description", "").lower()
        text = title + " " + desc
        
        # 分类
        if any(kw in text for kw in business_keywords):
            categories["💼 商业财经"].append(item)
        elif any(kw in text for kw in tech_keywords):
            categories["🚀 科技动态"].append(item)
        elif len(categories["🔥 国际要闻"]) < 5:
            categories["🔥 国际要闻"].append(item)
        else:
            categories["📌 其他要闻"].append(item)
    
    return categories


def generate_news_content(categories, viral_title, date_str):
    """生成 Markdown 内容"""
    
    # 格式化日期
    year, month, day = date_str.split('-')
    date_display = f"{year}年{month}月{day}日"
    time_display = datetime.now().strftime('%H:%M')
    
    content = f"""---
title: "{viral_title}"
date: "{date_display}"
source: "BBC, Al Jazeera, Tavily"
---

# 📰 每日新闻摘要

## 标题：{viral_title}

**日期**: {date_display}
**生成时间**: {time_display}
**来源**: BBC, Al Jazeera, Tavily Search

---

"""
    
    # 添加各分类新闻
    news_counter = 1
    for category, items in categories.items():
        if not items:
            continue
        
        content += f"## {category}\n\n"
        
        for item in items[:3]:  # 每个分类最多 3 条
            title = item.get("title", "")
            desc = item.get("description", "")
            url = item.get("url", "")
            
            # 提取要点
            points = []
            if desc:
                # 简单提取前两句
                sentences = re.split(r'[.!?。！？]\s+', desc)
                for sent in sentences[:2]:
                    sent = sent.strip()
                    if len(sent) > 10:
                        points.append(sent)
            
            content += f"### {news_counter}. {title}\n\n"
            
            if points:
                for point in points[:2]:
                    content += f"- **要点**: {point}\n"
            
            if url:
                content += f"- **来源**: {url}\n"
            
            content += "\n"
            news_counter += 1
    
    content += f"""---
*自动生成于 {date_display} {time_display}*
"""
    
    return content


def main():
    parser = argparse.ArgumentParser(description="生成每日新闻")
    parser.add_argument("--date", help="指定日期 (YYYY-MM-DD)，默认昨天")
    parser.add_argument(
        "--output-dir",
        default=str(get_default_output_dir()),
        help="输出目录，默认使用 XHS_DAILY_NEWS_DIR 或 agent home 下的 xhs-daily-news",
    )
    args = parser.parse_args()
    
    # 确定日期
    if args.date:
        date_str = args.date
    else:
        date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    print(f"🚀 生成每日新闻")
    print(f"📅 日期: {date_str}")
    
    # 检查 API Key
    api_key = get_tavily_api_key()
    if not api_key:
        print("❌ 未配置 TAVILY_API_KEY")
        print(f"请在环境变量或 {display_agent_home()}/.env 中添加: TAVILY_API_KEY=tvly-...")
        return 1
    
    print(f"🔑 API Key: {api_key[:10]}...{api_key[-4:]}")
    
    # 搜索新闻
    print("\n🔍 搜索国际新闻...")
    news_items = []
    
    # 使用 Tavily 搜索
    queries = [
        f"international news {date_str}",
        "world news today",
        "global headlines"
    ]
    
    for query in queries:
        result = tavily_search(query, max_results=5, topic="news", time_range="day")
        if result and "results" in result:
            for r in result["results"]:
                news_items.append({
                    "title": r.get("title", ""),
                    "description": r.get("content", ""),
                    "url": r.get("url", "")
                })
    
    # 去重
    seen_titles = set()
    unique_items = []
    for item in news_items:
        title = item.get("title", "")
        if title and title not in seen_titles:
            seen_titles.add(title)
            unique_items.append(item)
    
    news_items = unique_items
    
    print(f"✅ 获取到 {len(news_items)} 条新闻")
    
    if not news_items:
        print("⚠️ 未获取到新闻，使用示例数据")
        news_items = [
            {"title": "示例新闻标题 1", "description": "这是示例新闻描述", "url": "https://example.com/1"},
            {"title": "示例新闻标题 2", "description": "这是另一条示例新闻", "url": "https://example.com/2"},
        ]
    
    # 生成爆款标题
    print("\n🎯 生成爆款标题...")
    viral_title = generate_viral_title(news_items)
    print(f"标题: {viral_title}")
    
    # 分类
    print("\n📊 分类新闻...")
    categories = categorize_news(news_items)
    for cat, items in categories.items():
        print(f"  {cat}: {len(items)} 条")
    
    # 生成内容
    print("\n📝 生成 Markdown...")
    content = generate_news_content(categories, viral_title, date_str)
    
    # 保存文件
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / f"daily-briefing-{date_str}.md"
    output_file.write_text(content, encoding='utf-8')
    
    print(f"\n✅ 已保存: {output_file}")
    print(f"📊 总计: {sum(len(v) for v in categories.values())} 条新闻")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
