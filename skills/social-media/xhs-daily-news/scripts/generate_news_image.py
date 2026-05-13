#!/usr/bin/python3
"""
每日新闻摘要配图生成器
- 读取新闻 Markdown 文件
- 生成纵版和横版封面图片（参考化工日报风格）
- 直接使用原始解析的板块名称（国际焦点、地区动态、经济与市场、其他国际新闻）

用法:
    python3 generate-news-image.py --input /path/to/daily-briefing-2026-03-04.md --output-dir /home/jason/clawd/daily-news
"""

import os
import sys
import re
from datetime import datetime
from pathlib import Path

from _agent_home import get_default_output_dir


# 板块配色方案（支持新旧两种格式）
SECTOR_COLORS = {
    # 旧格式
    "国际焦点": {"accent": "#F4A460", "icon": "🌍"},
    "地区动态": {"accent": "#66BBDD", "icon": "📍"},
    "经济与市场": {"accent": "#88DD88", "icon": "📈"},
    "其他国际新闻": {"accent": "#DD88BB", "icon": "📰"},
    # 新格式（任务实际使用的格式）
    "🔥 国际要闻": {"accent": "#FF6B6B", "icon": "🔥"},
    "💼 商业财经": {"accent": "#95E1D3", "icon": "💼"},
    "🚀 科技动态": {"accent": "#A8D8EA", "icon": "🚀"},
    "📌 其他要闻": {"accent": "#C9B1FF", "icon": "📌"},
}


def parse_news_markdown(md_path):
    """解析新闻 Markdown 文件，提取标题、日期、板块和新闻内容"""
    content = Path(md_path).read_text(encoding='utf-8')
    
    # 提取主标题
    title_match = re.search(r'^## 标题：(.+)$', content, re.MULTILINE)
    main_title = title_match.group(1).strip() if title_match else "每日新闻摘要"
    
    # 提取日期
    date_match = re.search(r'\*\*日期\*\*: (.+)$', content, re.MULTILINE)
    date_str = date_match.group(1).strip() if date_match else datetime.now().strftime("%Y年%m月%d日")
    
    # 提取来源
    source_match = re.search(r'\*\*来源\*\*: (.+)$', content, re.MULTILINE)
    source_str = source_match.group(1).strip() if source_match else "BBC, Al Jazeera"
    
    # 按原始板块解析新闻
    sectors = {}
    current_sector = None
    
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # 识别板块标题（接受任意 ## 开头，排除"标题："行）
        if re.match(r'^##\s+', line):
            sector_name = line.lstrip('#').strip()
            if not sector_name.startswith('标题'):
                current_sector = sector_name
                sectors[current_sector] = []
                i += 1
                continue
        
        # 识别新闻条目
        if re.match(r'^###\s+\d+\.', line) and current_sector:
            # 提取序号和标题
            parts = line.lstrip('#').strip().split('.', 1)
            if len(parts) == 2:
                news_num = parts[0].strip()
                news_title = parts[1].strip()
            
            # 收集该新闻的所有要点（支持列表格式和普通段落格式）
            news_points = []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                # 遇到新的新闻或板块，停止收集
                if re.match(r'^###\s+\d+\.', next_line) or re.match(r'^##\s+', next_line):
                    break
                # 跳过空行和分隔线
                if not next_line or next_line == '---':
                    i += 1
                    continue
                # 收集要点行（支持三种格式）
                if next_line.startswith('- '):
                    # 格式 1: 列表项 - **要点**: 内容
                    if '**' in next_line:
                        clean_line = re.sub(r'^-\s+\*\*.*?\*\*[：:]\s*', '', next_line)
                    else:
                        # 格式 2: 列表项 - 内容
                        clean_line = re.sub(r'^-\s+', '', next_line)
                    if clean_line:
                        news_points.append(clean_line)
                elif next_line and not next_line.startswith('#') and not next_line.startswith('|'):
                    # 格式 3: 普通段落（新格式）
                    # 将长段落按句子分割成多个要点
                    sentences = re.split(r'(?<=[。！？])\s*', next_line)
                    for sent in sentences:
                        sent = sent.strip()
                        if sent and len(sent) > 5:  # 过滤太短的片段
                            news_points.append(sent)
                i += 1
            
            news_item = {
                "num": news_num,
                "title": news_title,
                "points": news_points[:5],  # 最多 5 个要点
                "summary": ' | '.join(news_points[:2])[:300]  # 兼容字段
            }
            sectors[current_sector].append(news_item)
            continue
        
        i += 1
    
    # 统计总数
    total_news = sum(len(news_list) for news_list in sectors.values())
    
    return {
        "main_title": main_title,
        "date": date_str,
        "source": source_str,
        "sectors": sectors,
        "total_news": total_news
    }


def _render_html_to_png(html_content, output_path, width, height):
    """用 Playwright 把 HTML 字符串渲染为 PNG"""
    from playwright.sync_api import sync_playwright
    from pathlib import Path as _Path

    temp_html = _Path(output_path).parent / f"{_Path(output_path).stem}_temp.html"
    temp_html.write_text(html_content, encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox",
                      "--disable-dev-shm-usage", "--no-zygote", "--disable-gpu"]
            )
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            page.goto(f"file://{temp_html.absolute()}")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(output_path), full_page=False)
            browser.close()
    finally:
        temp_html.unlink(missing_ok=True)


# 根据板块名称动态推断强调色
_ACCENT_PALETTE = ["#FF6B6B", "#95E1D3", "#A8D8EA", "#C9B1FF", "#F39C12", "#66BBDD", "#88DD88", "#F4A460"]

def _sector_accent(name, idx):
    """按已知板块名或顺序 idx 返回强调色"""
    mapping = {
        "国际焦点": "#F4A460", "地区动态": "#66BBDD", "经济与市场": "#88DD88", "其他国际新闻": "#DD88BB",
        "🔥 国际要闻": "#FF6B6B", "🔥 国际头条": "#FF6B6B",
        "💼 商业财经": "#95E1D3", "💼 商业经济": "#95E1D3",
        "🚀 科技动态": "#A8D8EA", "🔬 科技前沿": "#A8D8EA",
        "📌 其他要闻": "#C9B1FF", "📌 其他新闻": "#C9B1FF", "其他国际新闻": "#C9B1FF",
        "🌍 全球动态": "#66BBDD", "🌍 地区动态": "#66BBDD",
    }
    return mapping.get(name, _ACCENT_PALETTE[idx % len(_ACCENT_PALETTE)])


def _build_sector_card_html(sector_name, sector_news, idx=0, max_items=None):
    accent = _sector_accent(sector_name, idx)
    items = sector_news if max_items is None else sector_news[:max_items]
    html = (f'<div class="sector-card" style="border-left-color:{accent}">'
            f'<div class="sector-header">'
            f'<div class="sector-title">{sector_name}</div>'
            f'<div class="sector-count" style="background:{accent}">{len(sector_news)} 条</div>'
            f'</div>')
    for news in items:
        title = (news.get("title") or "").replace("<", "&lt;").replace(">", "&gt;")
        points = news.get("points") or []
        summary = " ".join(points[:2])[:200] if points else (news.get("summary") or "")
        summary = summary.replace("<", "&lt;").replace(">", "&gt;")
        html += f'<div class="news-item"><div class="news-title">{title}</div>'
        if summary:
            html += f'<div class="news-summary">{summary}</div>'
        html += '</div>'
    html += '</div>'
    return html


def generate_portrait_image(news_data, output_path):
    """生成纵版图片 (1179x2556) - HTML/Playwright 渲染"""
    try:
        from playwright.sync_api import sync_playwright  # noqa: just check import
    except ImportError:
        print("❌ 需要安装 playwright: pip install playwright && playwright install chromium")
        return None

    width, height = 1179, 2556
    sectors = news_data.get("sectors", {})

    content_html = ""
    for idx, sector_name in enumerate(sectors.keys()):
        sector_news = sectors[sector_name]
        if sector_news:
            content_html += _build_sector_card_html(sector_name, sector_news, idx=idx)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{width}px;height:{height}px;overflow:hidden;
  background:#F5F5F7;
  font-family:'Noto Sans CJK SC','Microsoft YaHei','PingFang SC',sans-serif;
  padding:32px 32px 72px}}
.header{{background:#fff;border-radius:20px;padding:30px 36px;margin-bottom:22px;
  text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.08);
  border-top:6px solid #FF4757}}
.header-title{{font-size:62px;font-weight:900;color:#1a1a1a;margin-bottom:8px;letter-spacing:2px}}
.header-sub{{font-size:24px;color:#888;margin-bottom:6px}}
.header-date{{font-size:30px;color:#FF4757;font-weight:700}}
.sector-card{{border-radius:16px;padding:26px 28px;margin-bottom:18px;
  background:#fff;box-shadow:0 2px 16px rgba(0,0,0,.07);border-left:7px solid #ccc}}
.sector-header{{display:flex;justify-content:space-between;align-items:center;
  margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid #f0f0f0}}
.sector-title{{font-size:36px;font-weight:800;color:#1a1a1a}}
.sector-count{{font-size:22px;color:#fff;padding:4px 16px;
  border-radius:20px;background:#ccc;font-weight:600}}
.news-item{{margin-bottom:14px;padding:16px;background:#FAFAFA;border-radius:12px}}
.news-item:last-child{{margin-bottom:0}}
.news-title{{font-size:32px;font-weight:700;color:#1a1a1a;margin-bottom:8px;
  line-height:1.4;overflow:hidden;text-overflow:ellipsis;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.news-summary{{font-size:26px;color:#555;line-height:1.45;
  overflow:hidden;text-overflow:ellipsis;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.footer{{position:absolute;bottom:22px;left:32px;right:32px;text-align:center;
  font-size:20px;color:#aaa;padding:12px;background:#fff;
  border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.05)}}
</style></head><body>
<div class="header">
  <div class="header-title">📰 每日新闻摘要</div>
  <div class="header-sub">{news_data.get("source","BBC · Al Jazeera · 全球媒体")}</div>
  <div class="header-date">{news_data.get("date","")}</div>
</div>
{content_html}
<div class="footer">数据来源：BBC、Al Jazeera 等 | 本内容仅供参考，不构成投资建议</div>
</body></html>"""

    _render_html_to_png(html, output_path, width, height)
    print(f"✅ 纵版图片已保存：{output_path}")
    return output_path


def generate_landscape_image(news_data, output_path):
    """生成横版图片 (1920x1080) - HTML/Playwright 渲染"""
    try:
        from playwright.sync_api import sync_playwright  # noqa
    except ImportError:
        print("❌ 需要安装 playwright")
        return None

    width, height = 1920, 1080
    sectors = news_data.get("sectors", {})

    left_html, right_html = "", ""
    for idx, sector_name in enumerate(sectors.keys()):
        sector_news = sectors[sector_name]
        if not sector_news:
            continue
        card = _build_sector_card_html(sector_name, sector_news, idx=idx, max_items=2)
        if idx % 2 == 0:
            left_html += card
        else:
            right_html += card

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{width}px;height:{height}px;overflow:hidden;
  background:#F5F5F7;
  font-family:'Noto Sans CJK SC','Microsoft YaHei','PingFang SC',sans-serif;
  padding:24px}}
.header{{background:#fff;border-radius:16px;padding:16px 36px;text-align:center;
  box-shadow:0 4px 16px rgba(0,0,0,.08);margin-bottom:20px;
  border-top:5px solid #FF4757}}
.header-title{{font-size:42px;font-weight:900;color:#1a1a1a;margin-bottom:4px;letter-spacing:1px}}
.header-meta{{font-size:18px;color:#888;display:inline;margin-right:18px}}
.header-date{{font-size:20px;color:#FF4757;font-weight:700;display:inline}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:20px;height:calc(100% - 118px)}}
.col{{display:flex;flex-direction:column;gap:16px}}
.sector-card{{border-radius:14px;padding:20px 22px;
  background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.07);
  border-left:6px solid #ccc;flex:1}}
.sector-header{{display:flex;justify-content:space-between;align-items:center;
  margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #f0f0f0}}
.sector-title{{font-size:28px;font-weight:800;color:#1a1a1a}}
.sector-count{{font-size:18px;color:#fff;padding:3px 14px;
  border-radius:16px;background:#ccc;font-weight:600}}
.news-item{{margin-bottom:10px;padding:12px;background:#FAFAFA;border-radius:10px}}
.news-item:last-child{{margin-bottom:0}}
.news-title{{font-size:24px;font-weight:700;color:#1a1a1a;margin-bottom:6px;
  line-height:1.35;overflow:hidden;text-overflow:ellipsis;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.news-summary{{font-size:20px;color:#555;line-height:1.35;
  overflow:hidden;text-overflow:ellipsis;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.footer{{position:absolute;bottom:14px;left:24px;right:24px;text-align:center;
  font-size:16px;color:#aaa}}
</style></head><body>
<div class="header">
  <div class="header-title">📰 每日新闻摘要</div>
  <span class="header-meta">{news_data.get("source","BBC · Al Jazeera · 全球媒体")}</span>
  <span class="header-date">{news_data.get("date","")}</span>
</div>
<div class="cols">
  <div class="col">{left_html}</div>
  <div class="col">{right_html}</div>
</div>
<div class="footer">数据来源：BBC、Al Jazeera 等 | 本内容仅供参考</div>
</body></html>"""

    _render_html_to_png(html, output_path, width, height)
    print(f"✅ 横版图片已保存：{output_path}")
    return output_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="每日新闻摘要配图生成器")
    parser.add_argument("--input", type=Path, required=True, help="输入 Markdown 文件路径")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=get_default_output_dir(),
        help="输出目录，默认使用 XHS_DAILY_NEWS_DIR 或 agent home 下的 xhs-daily-news",
    )
    parser.add_argument("--layout", choices=["portrait", "landscape", "both"], default="both", help="生成布局")
    args = parser.parse_args()
    
    if not args.input.exists():
        print(f"❌ 输入文件不存在：{args.input}")
        sys.exit(1)
    
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 解析 Markdown
    print(f"📰 解析新闻文件：{args.input}")
    news_data = parse_news_markdown(args.input)
    print(f"✓ 提取到 {news_data['total_news']} 条新闻，{len(news_data['sectors'])} 个板块")
    for sector, items in news_data['sectors'].items():
        print(f"  - {sector}: {len(items)} 条")
    
    # 生成文件名
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", args.input.name)
    date_str = date_match.group(1).replace("-", "") if date_match else datetime.now().strftime("%Y%m%d")
    base_name = f"daily-briefing-{date_str}"
    
    # 生成图片
    if args.layout in ["portrait", "both"]:
        portrait_path = output_dir / f"{base_name}_portrait.png"
        generate_portrait_image(news_data, portrait_path)
    
    if args.layout in ["landscape", "both"]:
        landscape_path = output_dir / f"{base_name}_landscape.png"
        generate_landscape_image(news_data, landscape_path)
    
    print(f"\n✅ 完成！图片已保存到：{output_dir}")
    
    # 输出路径
    if args.layout in ["portrait", "both"]:
        print(f"FILE_PATH_PORTRAIT:{portrait_path}")
    if args.layout in ["landscape", "both"]:
        print(f"FILE_PATH_LANDSCAPE:{landscape_path}")


if __name__ == "__main__":
    main()
