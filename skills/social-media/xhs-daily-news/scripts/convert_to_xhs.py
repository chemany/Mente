#!/usr/bin/env python3
"""
将每日新闻转换为小红书格式
"""

import argparse
import re
from datetime import datetime
from pathlib import Path


def convert_to_xhs(input_path, output_path):
    """转换新闻为小红书格式"""
    content = Path(input_path).read_text(encoding='utf-8')
    
    # 提取日期
    date_match = re.search(r'(\d{4})\s*年\s*(\d{2})\s*月\s*(\d{2})\s*日', content)
    if date_match:
        year, month, day = date_match.groups()
        date_str = f"{year}-{month}-{day}"
    else:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    # 提取第一条国际新闻作为标题
    title = "今日新闻摘要"
    headline_match = re.search(r'## 1\.\s*(.+?)\n', content)
    if headline_match:
        title = headline_match.group(1).strip()[:30]  # 限制30字
    
    # 构建小红书格式
    xhs_content = f"""---
emoji: "📰"
title: "{title}"
subtitle: "{date_str}"
---

# 📰 {date_str} 要闻速览

> 每日精选国际热点，3分钟了解全球动态

"""
    
    # 提取各板块新闻
    sections = []
    current_section = None
    current_news = []
    
    lines = content.split('\n')
    for line in lines:
        # 检测板块标题
        section_match = re.match(r'^#+\s*([🔥🌍💼💻])\s*(.+)', line)
        if section_match:
            if current_section and current_news:
                sections.append({'name': current_section, 'news': current_news})
            current_section = section_match.group(2)
            current_news = []
            continue
        
        # 检测新闻标题
        news_match = re.match(r'^#+\s*(\d+)\.\s*(.+)', line)
        if news_match and current_section:
            current_news.append({
                'num': news_match.group(1),
                'title': news_match.group(2).strip()
            })
    
    # 添加最后一个板块
    if current_section and current_news:
        sections.append({'name': current_section, 'news': current_news})
    
    # 构建输出
    for section in sections[:4]:  # 最多4个板块
        emoji = "🌍" if "国际" in section['name'] else \
                "💼" if "商业" in section['name'] or "财经" in section['name'] else \
                "💻" if "科技" in section['name'] else "📌"
        
        xhs_content += f"# {emoji} {section['name']}\n\n"
        
        for news in section['news'][:3]:  # 每个板块最多3条
            xhs_content += f"## {news['num']}. {news['title']}\n\n"
        
        xhs_content += "\n"
    
    # 添加标签
    xhs_content += """# 🏷️ 今日标签

#国际新闻 #时事热点 #全球视野 #新闻早报 #每日精选
"""
    
    # 保存
    Path(output_path).write_text(xhs_content, encoding='utf-8')
    print(f"✅ 已生成: {output_path}")
    return title


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help='输入新闻文件')
    parser.add_argument('--output', required=True, help='输出小红书格式文件')
    args = parser.parse_args()
    
    title = convert_to_xhs(args.input, args.output)
    print(f"标题: {title}")
