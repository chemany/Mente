#!/usr/bin/env python3
"""
小红书发布脚本
使用 rednote-cli 发布图片笔记到小红书

用法:
    python3 publish_to_xhs.py --date 2026-04-13 [--dry-run]

环境变量:
    REDNOTE_INSTANCE: rednote 实例名称 (默认: seller-main)
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from _agent_home import get_default_output_dir

# 配置
DEFAULT_OUTPUT_DIR = get_default_output_dir()
DEFAULT_INSTANCE = os.environ.get("REDNOTE_INSTANCE", "seller-main")


def run_command(cmd, description, check=True):
    """执行命令"""
    print(f"\n📌 {description}")
    print(f"命令: {shlex.join(cmd)}")

    result = subprocess.run(cmd, shell=False, capture_output=True, text=True)

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr, file=sys.stderr)

    if check and result.returncode != 0:
        print(f"❌ 命令失败 (exit code: {result.returncode})")
        return None

    return result


def check_rednote_status(instance):
    """检查 rednote 状态"""
    result = run_command(
        ["rednote", "status", "--instance", instance],
        f"检查 rednote 实例状态: {instance}",
        check=False,
    )
    if result and result.returncode == 0:
        return True
    return False


def check_login(instance):
    """检查是否已登录"""
    result = run_command(
        ["rednote", "check-login", "--instance", instance],
        "检查登录状态",
        check=False,
    )
    if result and result.returncode == 0:
        return True
    return False


def extract_title_from_markdown(md_file):
    """从 Markdown 提取标题"""
    content = md_file.read_text(encoding='utf-8')
    
    # 尝试从 YAML frontmatter 提取
    match = re.search(r'title:\s*"([^"]+)"', content)
    if match:
        return match.group(1)
    
    # 尝试从 # 标题提取
    match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if match:
        return match.group(1)
    
    return "每日新闻摘要"


def publish_to_xhs(date_str, output_dir=DEFAULT_OUTPUT_DIR, instance=DEFAULT_INSTANCE, dry_run=False):
    """发布到小红书"""
    output_dir = Path(output_dir).expanduser()
    
    # 路径
    xhs_md = output_dir / f"xhs_daily_{date_str}.md"
    image_dir = output_dir / f"xhs_output_{date_str}"
    
    # 检查文件
    if not xhs_md.exists():
        print(f"❌ 小红书 Markdown 不存在: {xhs_md}")
        return False
    
    if not image_dir.exists():
        print(f"❌ 输出目录不存在: {image_dir}")
        return False
    
    # 获取图片
    images = sorted(image_dir.glob("*.png"))
    if not images:
        print(f"❌ 没有找到图片文件")
        return False
    
    print(f"📸 找到 {len(images)} 张图片")
    for img in images:
        print(f"   - {img.name}")
    
    # 提取标题
    title = extract_title_from_markdown(xhs_md)
    print(f"📝 标题: {title}")
    
    # 构建内容
    content = f"""📰 {date_str} 国际要闻

🔥 每日精选全球热点新闻
💡 3分钟了解世界动态

📌 点击主页查看更多

#国际新闻 #时事热点 #全球视野 #新闻早报"""

    # 构建图片参数
    image_args: list[str] = []
    for img in images:
        image_args.extend(["--image", str(img)])

    # 构建命令
    cmd = [
        "rednote",
        "publish",
        "--instance",
        instance,
        "--type",
        "image",
        *image_args,
        "--title",
        title,
        "--content",
        content,
        "--tag",
        "国际新闻",
        "--tag",
        "时事热点",
        "--tag",
        "全球视野",
        "--tag",
        "新闻早报",
        "--publish",
    ]

    if dry_run:
        print("\n🔍 [DRY RUN] 将要执行的命令:")
        print(shlex.join(cmd))
        return True
    
    # 检查状态
    if not check_rednote_status(instance):
        print(f"❌ rednote 实例未连接: {instance}")
        print("请先运行: rednote browser connect")
        return False
    
    if not check_login(instance):
        print(f"❌ 未登录，请先登录")
        print("运行: rednote login")
        return False
    
    # 执行发布
    result = run_command(cmd, "发布到小红书")
    
    if result and result.returncode == 0:
        print("\n✅ 发布成功!")
        
        # 尝试解析返回的 JSON
        try:
            output = result.stdout.strip()
            # 查找 JSON 部分
            json_match = re.search(r'\{.*\}', output, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if data.get('ok'):
                    print(f"📝 返回数据:")
                    print(json.dumps(data, indent=2, ensure_ascii=False))
        except:
            pass
        
        return True
    else:
        print("\n❌ 发布失败")
        return False


def main():
    parser = argparse.ArgumentParser(description="发布每日新闻到小红书")
    parser.add_argument("--date", required=True, help="日期 (YYYY-MM-DD)")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="工作目录，默认使用 XHS_DAILY_NEWS_DIR 或 agent home 下的 xhs-daily-news",
    )
    parser.add_argument("--instance", default=DEFAULT_INSTANCE, help=f"rednote 实例 (默认: {DEFAULT_INSTANCE})")
    parser.add_argument("--dry-run", action="store_true", help="仅显示命令，不实际执行")
    args = parser.parse_args()
    
    print(f"🚀 小红书发布脚本")
    print(f"📅 日期: {args.date}")
    print(f"📁 工作目录: {args.output_dir}")
    print(f"🔧 实例: {args.instance}")
    
    success = publish_to_xhs(args.date, args.output_dir, args.instance, args.dry_run)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
