#!/usr/bin/python3
"""
小红书每日新闻完整工作流
一键执行：新闻获取 → 配图生成 → 小红书格式化 → 卡片渲染 → 发布

用法:
    python3 run_full_workflow.py [--date YYYY-MM-DD] [--skip-publish]

示例:
    python3 run_full_workflow.py
    python3 run_full_workflow.py --date 2026-04-13
    python3 run_full_workflow.py --skip-publish  # 只生成内容，不发布
"""

import argparse
import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from _agent_home import get_default_output_dir

# 配置
SKILL_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
DEFAULT_OUTPUT_DIR = get_default_output_dir()


def run_command(cmd, description, check=True):
    """执行命令并打印结果"""
    print(f"\n{'='*60}")
    print(f"📌 {description}")
    print(f"{'='*60}")
    print(f"命令: {cmd}")
    print("-" * 60)
    
    # 使用系统 Python 环境
    env = os.environ.copy()
    env['PATH'] = '/usr/bin:' + env.get('PATH', '')
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env, executable='/bin/bash')
    
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr, file=sys.stderr)
    
    if check and result.returncode != 0:
        print(f"❌ 失败 (exit code: {result.returncode})")
        return False
    
    print(f"✅ 成功")
    return True


def step1_generate_news(date_str, output_dir):
    """步骤 1: 生成每日新闻"""
    output_file = output_dir / f"daily-briefing-{date_str}.md"
    
    if output_file.exists():
        print(f"⚠️ 新闻文件已存在: {output_file}")
        print("跳过新闻生成，使用现有文件")
        return True
    
cmd = f"""python3 {SCRIPTS_DIR}/generate_daily_news.py \
--date {date_str} \
--output-dir {output_dir}"""
    
    return run_command(cmd, "生成每日新闻（使用 Tavily API）")


def step2_generate_images(date_str, output_dir):
    """步骤 2: 生成配图"""
    input_file = output_dir / f"daily-briefing-{date_str}.md"
    
    if not input_file.exists():
        print(f"❌ 新闻文件不存在: {input_file}")
        return False
    
cmd = f"""python3 {SCRIPTS_DIR}/generate_news_image.py \
--input {input_file} \
--output-dir {output_dir} \
--layout both"""
    
    return run_command(cmd, "生成配图（纵版+横版）")


def step3_convert_to_xhs(date_str, output_dir):
    """步骤 3: 转换为小红书格式"""
    input_file = output_dir / f"daily-briefing-{date_str}.md"
    output_file = output_dir / f"xhs_daily_{date_str}.md"
    
    if not input_file.exists():
        print(f"❌ 新闻文件不存在: {input_file}")
        return False
    
    cmd = f"""python3 {SCRIPTS_DIR}/convert_to_xhs.py \
--input {input_file} \
--output {output_file}"""
    
    return run_command(cmd, "转换为小红书格式")


def step4_render_cards(date_str, output_dir):
    """步骤 4: 渲染小红书卡片"""
    input_file = output_dir / f"xhs_daily_{date_str}.md"
    cards_dir = output_dir / f"xhs_output_{date_str}"
    
    if not input_file.exists():
        print(f"❌ 小红书文件不存在: {input_file}")
        return False
    
    # 创建输出目录
    cards_dir.mkdir(exist_ok=True)
    
cmd = f"""python3 {SCRIPTS_DIR}/render_xhs_cards.py \
{input_file} \
--output-dir {cards_dir} \
--style xiaohongshu"""
    
    return run_command(cmd, "渲染小红书卡片")


def step5_publish(date_str, output_dir, dry_run=False):
    """步骤 5: 发布到小红书"""
    cards_dir = output_dir / f"xhs_output_{date_str}"
    
    if not cards_dir.exists():
        print(f"❌ 输出目录不存在: {cards_dir}")
        return False
    
    # 检查必要的文件
    cover = cards_dir / "cover.png"
    if not cover.exists():
        print(f"❌ 封面不存在: {cover}")
        return False
    
    # 获取图片
    images = sorted(cards_dir.glob("*.png"))
    if not images:
        print("❌ 没有找到图片文件")
        return False
    
    print(f"📸 找到 {len(images)} 张图片")
    
    # 使用 publish_to_xhs.py 脚本
    cmd = f"""python3 {SCRIPTS_DIR}/publish_to_xhs.py \
--date {date_str} \
--output-dir {output_dir}"""
    
    if dry_run:
        cmd += " --dry-run"
    
    return run_command(cmd, "发布到小红书", check=False)


def main():
    parser = argparse.ArgumentParser(description="小红书每日新闻完整工作流")
    parser.add_argument("--date", help="指定日期 (YYYY-MM-DD)，默认昨天")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="工作目录，默认使用 XHS_DAILY_NEWS_DIR 或 agent home 下的 xhs-daily-news",
    )
    parser.add_argument("--skip-publish", action="store_true", help="跳过发布步骤")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不实际发布")
    parser.add_argument("--steps", default="all", help="执行指定步骤 (1,2,3,4,5 或 all)")
    args = parser.parse_args()
    
    # 确定日期
    if args.date:
        date_str = args.date
    else:
        date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    output_dir = Path(args.output_dir).expanduser()
    
    print(f"🚀 小红书每日新闻工作流")
    print(f"📅 日期: {date_str}")
    print(f"📁 输出目录: {output_dir}")
    print(f"🔧 技能目录: {SKILL_DIR}")
    
    # 确保输出目录存在
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 执行步骤
    steps_to_run = args.steps.split(',') if args.steps != 'all' else ['1', '2', '3', '4', '5']
    
    results = {}
    
    if '1' in steps_to_run:
        results['generate_news'] = step1_generate_news(date_str, output_dir)
    
    if '2' in steps_to_run and results.get('generate_news', True):
        results['generate_images'] = step2_generate_images(date_str, output_dir)
    
    if '3' in steps_to_run and results.get('generate_news', True):
        results['convert_to_xhs'] = step3_convert_to_xhs(date_str, output_dir)
    
    if '4' in steps_to_run and results.get('convert_to_xhs', True):
        results['render_cards'] = step4_render_cards(date_str, output_dir)
    
    if '5' in steps_to_run and not args.skip_publish:
        results['publish'] = step5_publish(date_str, output_dir, args.dry_run)
    
    # 输出总结
    print(f"\n{'='*60}")
    print("📊 执行总结")
    print(f"{'='*60}")
    for step, success in results.items():
        status = "✅" if success else "❌"
        print(f"{status} {step}")
    
    all_success = all(results.values())
    if all_success:
        print(f"\n🎉 所有步骤执行成功!")
        print(f"📁 输出文件:")
        print(f"   - {output_dir}/daily-briefing-{date_str}.md")
        print(f"   - {output_dir}/daily-briefing-{date_str.replace('-', '')}_portrait.png")
        print(f"   - {output_dir}/daily-briefing-{date_str.replace('-', '')}_landscape.png")
        print(f"   - {output_dir}/xhs_daily_{date_str}.md")
        print(f"   - {output_dir}/xhs_output_{date_str}/")
        
        # 写入状态文件
        state_file = output_dir / f"state_{date_str}.json"
        import json
        state = {
            "date": date_str,
            "timestamp": datetime.now().isoformat(),
            "steps": {k: v for k, v in results.items()},
            "files": {
                "news": str(output_dir / f"daily-briefing-{date_str}.md"),
                "xhs": str(output_dir / f"xhs_daily_{date_str}.md"),
                "output_dir": str(output_dir / f"xhs_output_{date_str}")
            }
        }
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
    else:
        print(f"\n⚠️ 部分步骤失败，请检查日志")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
