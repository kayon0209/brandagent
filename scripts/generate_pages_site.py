"""Build the public introduction from the same markup, CSS and tokens as Next."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'docs/site/brandagent'


def build_outputs():
    content = (ROOT / 'src/components/landing/content.html').read_text()
    content = content.replace('__ENTRY_HREF__', '#access').replace('__ENTRY_LABEL__', '查看体验方式').replace('__SURFACE_NOTE__', '本页为静态介绍与虚构样张，非在线写作应用；目前通过公开仓库了解本地部署与体验方式。')
    if re.search(r'__[A-Z_]+__', content):
        raise ValueError('Unresolved landing placeholder')
    token_source = (ROOT / 'src/styles/consumer-tokens.css').read_text()
    tokens = re.search(r':root\s*\{[^}]*\}', token_source).group(0)
    css = '/* Generated: consumer-tokens.css + landing.css. Do not edit. */\n' + tokens + '\n' + (ROOT / 'src/styles/landing.css').read_text()
    html = '''<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BrandAgent · 一个人的编辑部</title>
<meta name="description" content="从自己的素材到一份可修改、可追溯的母稿。公众号、小红书、知乎、视频号四个开本的编辑工作台；当前为本地候选介绍与虚构样张。">
<meta property="og:title" content="BrandAgent · 一个人的编辑部">
<meta property="og:description" content="稿纸、朱笔、来源与版本。AI 递建议，判断和签发留给你。静态介绍，非在线应用。">
<meta property="og:type" content="website"><meta property="og:url" content="https://brandagent.pages.dev/">
<link rel="canonical" href="https://brandagent.pages.dev/">
<link rel="icon" href="assets/mark.svg"><link rel="stylesheet" href="styles.css">
</head><body><div class="v42-landing">''' + content + '</div></body></html>\n'
    return {'index.html': html, 'styles.css': css}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    payload_path = ROOT / 'src/components/landing/content.json'
    payload = json.dumps({'html': (ROOT / 'src/components/landing/content.html').read_text()}, ensure_ascii=False, indent=2) + '\n'
    if args.check:
        if payload_path.read_text() != payload:
            raise SystemExit('Stale generated Next landing payload')
    else:
        payload_path.write_text(payload)
    for name, expected in build_outputs().items():
        path = SITE / name
        if args.check:
            if not path.exists() or path.read_text() != expected:
                raise SystemExit(f'Stale generated site: {name}; run python3 scripts/generate_pages_site.py')
        else:
            path.write_text(expected)
    print('Shared landing outputs verified' if args.check else 'Shared landing outputs generated')


if __name__ == '__main__':
    main()
