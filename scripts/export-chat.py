#!/usr/bin/env python3
"""
Claude Code 对话导出工具 —— 把 .jsonl 对话文件转成精美的 HTML 网页。

用法：
    python3 scripts/export-chat.py --list                   # 列出所有对话（含开头语）
    python3 scripts/export-chat.py <序号>                   # 按序号导出（最快）
    python3 scripts/export-chat.py <序号> ~/Desktop/a.html  # 指定输出路径
    python3 scripts/export-chat.py <uuid或文件路径>         # 按文件名导出

示例：
    python3 scripts/export-chat.py --list
    python3 scripts/export-chat.py 0
    python3 scripts/export-chat.py 3 ~/Desktop/分享.html

输出：一个自包含的 HTML 文件，浏览器打开即可查看，支持暗色/亮色模式切换。
"""

import json
import os
import sys
import html as html_mod
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

TZ_LOCAL = datetime.now().astimezone().tzinfo


# ── 数据解析 ──────────────────────────────────────────────────

def parse_jsonl(filepath: str) -> list[dict]:
    """读取 JSONL 文件，过滤出有意义的对话事件"""
    events = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = obj.get('type', '')
            if t in ('user', 'assistant', 'ai-title'):
                events.append(obj)
    return events


def build_turns(events: list[dict]) -> list[dict]:
    """
    把扁平的 events 列表构建为对话轮次（turn）。
    一个 turn 包含一个用户消息和紧随其后的助手响应。
    tool_use / tool_result 成对处理。
    """
    turns = []
    current_user = None          # 当前用户消息
    pending_tools: dict[str, dict] = {}  # tool_use_id -> tool_use obj
    assistant_blocks: list[dict] = []     # 助手的所有 content blocks
    title: Optional[str] = None

    for ev in events:
        if ev.get('type') == 'ai-title':
            if ev.get('title'):
                title = ev['title']

        elif ev.get('type') == 'user':
            msg = ev.get('message', {})
            content = msg.get('content', [])
            if isinstance(content, str):
                content = [{'type': 'text', 'text': content}]

            text_parts = []
            tool_results: dict[str, dict] = {}
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
                elif block.get('type') == 'tool_result':
                    tid = block.get('tool_use_id', '')
                    tool_results[tid] = block

            user_text = '\n'.join(text_parts).strip()

            # 如果只有 tool_results 没有用户文本，合并到上一轮
            if not user_text and tool_results and turns:
                last = turns[-1]
                for tid, tr in tool_results.items():
                    if tid in (last.get('_pending_tool_ids') or set()):
                        last.setdefault('_tool_results', {})[tid] = tr
                continue

            # 新的用户消息 → 开启新 turn
            if current_user and assistant_blocks:
                turns.append(_make_turn(current_user, assistant_blocks, pending_tools))
            current_user = {
                'text': user_text,
                'timestamp': ev.get('timestamp', ''),
                '_tool_results': tool_results,
                '_pending_tool_ids': set(tool_results.keys()),
            }
            assistant_blocks = []
            pending_tools = {}

        elif ev.get('type') == 'assistant':
            msg = ev.get('message', {})
            content = msg.get('content', [])
            if isinstance(content, str):
                content = [{'type': 'text', 'text': content}]

            for block in content:
                if not isinstance(block, dict):
                    continue
                assistant_blocks.append({
                    **block,
                    '_model': msg.get('model', ''),
                    '_timestamp': ev.get('timestamp', ''),
                    '_usage': msg.get('usage'),
                })

    # 收尾最后一个 turn
    if current_user and assistant_blocks:
        turns.append(_make_turn(current_user, assistant_blocks, pending_tools))

    return turns, title


def _make_turn(user: dict, blocks: list[dict], pending_tools: dict) -> dict:
    """组装一个对话轮次"""
    # 把 pending_tools 和 blocks 中的 tool_use 关联起来
    tool_results = user.get('_tool_results', {})
    processed = []
    for blk in blocks:
        if blk.get('type') == 'tool_use':
            tid = blk.get('id', '')
            blk = {**blk, '_result': tool_results.get(tid)}
        processed.append(blk)

    return {
        'user_text': user.get('text', ''),
        'user_timestamp': user.get('timestamp', ''),
        'assistant_blocks': processed,
    }


def find_sessions(project_dir: Optional[str] = None) -> list[dict]:
    """扫描 ~/.claude/projects/ 下的所有对话文件"""
    base = Path.home() / '.claude' / 'projects'
    if project_dir:
        base = base / project_dir
    if not base.exists():
        print(f"目录不存在: {base}", file=sys.stderr)
        return []

    sessions = []
    for jsonl in sorted(base.rglob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = jsonl.stat()
        # 快速读取 title 和第一条用户消息
        title = ''
        first_question = ''
        turn_count = 0
        try:
            with open(jsonl, 'r') as f:
                for line in f:
                    obj = json.loads(line)
                    if obj.get('type') == 'ai-title' and obj.get('title'):
                        title = obj['title']
                    if obj.get('type') == 'user':
                        turn_count += 1
                        if not first_question:
                            content = obj.get('message', {}).get('content', [])
                            for c in content:
                                if isinstance(c, dict) and c.get('type') == 'text':
                                    t = c.get('text', '').strip()
                                    if t:
                                        first_question = t
                                        break
        except Exception:
            pass

        sessions.append({
            'path': str(jsonl),
            'name': jsonl.stem,
            'title': title,
            'first_question': first_question,
            'turns': turn_count,
            'size': stat.st_size,
            'mtime': datetime.fromtimestamp(stat.st_mtime, tz=TZ_LOCAL).strftime('%Y-%m-%d %H:%M'),
        })
    return sessions


# ── HTML 生成 ──────────────────────────────────────────────────

def _esc(text: str) -> str:
    """HTML 转义"""
    return html_mod.escape(text)


def _format_ts(ts: str) -> str:
    """格式化时间戳为可读格式"""
    if not ts:
        return ''
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        local_dt = dt.astimezone(TZ_LOCAL)
        return local_dt.strftime('%H:%M')
    except Exception:
        return ts


def _render_markdown(text: str) -> str:
    """简易 Markdown → HTML（处理常见格式，无需额外依赖）"""
    if not text:
        return ''

    lines = text.split('\n')
    result = []
    in_code_block = False
    code_lang = ''
    code_lines: list[str] = []
    in_table = False
    table_lines: list[str] = []
    in_list = False
    list_tag = ''

    def flush_code():
        nonlocal code_lines, code_lang, in_code_block
        lang = code_lang or 'plaintext'
        code = '\n'.join(code_lines)
        code = _esc(code)
        result.append(f'<pre><code class="language-{lang}">{code}</code></pre>')
        code_lines = []
        code_lang = ''

    def flush_table():
        nonlocal table_lines, in_table
        if not table_lines:
            return
        html_parts = ['<table>']
        for i, row in enumerate(table_lines):
            cells = [c.strip() for c in row.split('|') if c.strip() != '']
            # skip separator row
            if all(re.match(r'^[-:]+$', c) for c in cells):
                continue
            tag = 'th' if i == 0 else 'td'
            html_parts.append('<tr>')
            for cell in cells:
                html_parts.append(f'<{tag}>{_render_inline(_esc(cell))}</{tag}>')
            html_parts.append('</tr>')
        html_parts.append('</table>')
        result.append('\n'.join(html_parts))
        table_lines = []

    def flush_list():
        nonlocal in_list, list_tag
        in_list = False
        list_tag = ''

    i = 0
    while i < len(lines):
        line = lines[i]

        # 代码块开始/结束
        if line.strip().startswith('```'):
            if in_code_block:
                flush_code()
                in_code_block = False
            else:
                if in_table:
                    flush_table()
                if in_list:
                    flush_list()
                code_lang = line.strip()[3:].strip()
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # 表格
        if '|' in line and line.strip().startswith('|'):
            if not in_table:
                if in_list:
                    flush_list()
                in_table = True
                table_lines = []
            table_lines.append(line)
            i += 1
            # 如果下一行不是表格行，则当前表结束
            if i >= len(lines) or not ('|' in lines[i] and lines[i].strip().startswith('|')):
                flush_table()
                in_table = False
            continue

        if in_table:
            flush_table()
            in_table = False

        # 无序列表
        ul_match = re.match(r'^(\s*)[-*+]\s+(.*)', line)
        # 有序列表
        ol_match = re.match(r'^(\s*)\d+[.)]\s+(.*)', line)

        if ul_match:
            if not in_list or list_tag != 'ul':
                if in_list:
                    result.append(f'</{list_tag}>')
                result.append('<ul>')
                in_list = True
                list_tag = 'ul'
            indent, content = ul_match.groups()
            result.append(f'<li>{_render_inline(content)}</li>')
            i += 1
            continue
        elif ol_match:
            if not in_list or list_tag != 'ol':
                if in_list:
                    result.append(f'</{list_tag}>')
                result.append('<ol>')
                in_list = True
                list_tag = 'ol'
            indent, content = ol_match.groups()
            result.append(f'<li>{_render_inline(content)}</li>')
            i += 1
            continue
        else:
            if in_list:
                result.append(f'</{list_tag}>')
                in_list = False
                list_tag = ''

        # 标题
        heading_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if heading_match:
            level = len(heading_match.group(1))
            content = heading_match.group(2)
            result.append(f'<h{level}>{_render_inline(content)}</h{level}>')
            i += 1
            continue

        # 引用
        if line.startswith('>'):
            quote_lines = []
            while i < len(lines) and lines[i].startswith('>'):
                quote_lines.append(lines[i][1:].strip())
                i += 1
            result.append(f'<blockquote><p>{_render_inline(" ".join(quote_lines))}</p></blockquote>')
            continue

        # 分隔线
        if re.match(r'^[-*_]{3,}$', line.strip()):
            result.append('<hr>')
            i += 1
            continue

        # 普通段落
        if line.strip():
            result.append(f'<p>{_render_inline(line)}</p>')
        else:
            result.append('')
        i += 1

    # 清理未闭合的块
    if in_code_block:
        flush_code()
    if in_table:
        flush_table()
    if in_list:
        result.append(f'</{list_tag}>')

    return '\n'.join(result)


def _render_inline(text: str) -> str:
    """行内 Markdown 渲染：粗体、斜体、行内代码、链接、删除线"""
    text = _esc(text)

    # 行内代码（先处理，避免和其他规则冲突）
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # 粗体+斜体
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    # 粗体
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 斜体
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # 删除线
    text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
    # 链接
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)

    return text


def _format_size(size_bytes: int) -> str:
    """文件大小格式化"""
    for unit in ['B', 'KB', 'MB']:
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} GB"


def generate_html(turns: list[dict], title: Optional[str] = None, source_file: str = '') -> str:
    """生成完整的 HTML 页面"""

    # 格式化时间范围
    time_start = ''
    time_end = ''
    if turns:
        time_start = turns[0].get('user_timestamp', '')
        time_end = turns[-1].get('user_timestamp', '')

    title_display = title or 'Claude Code 对话'
    date_display = _format_ts(time_start) if time_start else ''

    # 生成消息 HTML
    messages_html = []
    for ti, turn in enumerate(turns):
        user_text = turn.get('user_text', '')
        user_ts = turn.get('user_timestamp', '')
        blocks = turn.get('assistant_blocks', [])

        if user_text:
            messages_html.append(f'''
            <div class="msg msg-user">
                <div class="msg-avatar" title="你">👤</div>
                <div class="msg-body">
                    <div class="msg-content">{_render_markdown(user_text)}</div>
                    <div class="msg-time">{_format_ts(user_ts)}</div>
                </div>
            </div>''')

        if blocks:
            messages_html.append('<div class="msg msg-assistant">')
            messages_html.append('<div class="msg-avatar" title="Claude">🧠</div>')
            messages_html.append('<div class="msg-body">')

            # 按类型分组：thinking + text/tool_use 交替
            for bi, blk in enumerate(blocks):
                btype = blk.get('type', '')
                model = blk.get('_model', '')

                if btype == 'thinking':
                    thinking_text = blk.get('thinking', '')
                    if thinking_text:
                        # 截取预览（前 100 字符）
                        preview = thinking_text[:120].replace('\n', ' ').strip()
                        messages_html.append(f'''
                        <details class="thinking-block">
                            <summary><span class="thinking-icon">💭</span> 思考过程<span class="thinking-preview">：{_esc(preview)}…</span></summary>
                            <div class="thinking-content">{_render_markdown(thinking_text)}</div>
                        </details>''')

                elif btype == 'tool_use':
                    tool_name = blk.get('name', '?')
                    tool_input = blk.get('input', {})
                    tool_desc = tool_input.get('description', '')
                    result = blk.get('_result', {})
                    result_content = ''
                    if result:
                        result_content = result.get('content', '')
                        if isinstance(result_content, list):
                            result_content = '\n'.join(
                                r.get('text', '') if isinstance(r, dict) else str(r)
                                for r in result_content
                            )

                    # 工具调用的输入展示
                    input_display = ''
                    if tool_name == 'Bash':
                        input_display = tool_input.get('command', '')
                    elif tool_name in ('WebSearch', 'WebFetch'):
                        input_display = tool_input.get('query', '') or tool_input.get('url', '')
                    else:
                        input_display = json.dumps(tool_input, ensure_ascii=False, indent=2)

                    messages_html.append(f'''
                        <details class="tool-block">
                            <summary><span class="tool-icon">🔧</span> <code>{_esc(tool_name)}</code>{" — " + _esc(tool_desc) if tool_desc else ""}</summary>
                            <div class="tool-input"><strong>输入：</strong><pre><code>{_esc(str(input_display)[:3000])}</code></pre></div>
                            {f'<div class="tool-output"><strong>结果：</strong><pre><code>{_esc(str(result_content)[:5000])}</code></pre></div>' if result_content else ''}
                        </details>''')

                elif btype == 'text':
                    text = blk.get('text', '')
                    if text:
                        messages_html.append(f'<div class="msg-content">{_render_markdown(text)}</div>')

            # 时间戳和模型
            last_ts = blocks[-1].get('_timestamp', '') if blocks else ''
            model_name = blocks[0].get('_model', '') if blocks else ''
            messages_html.append(f'<div class="msg-time">{_format_ts(last_ts)}{" · " + _esc(model_name) if model_name else ""}</div>')
            messages_html.append('</div></div>')

    # 完整的 HTML 页面
    html = f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title_display)} — Claude Code 对话导出</title>
<style>
/* ── Reset & Base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
    --bg: #fafafa;
    --surface: #ffffff;
    --border: #e5e5e5;
    --text: #1a1a1a;
    --text-secondary: #6b7280;
    --text-tertiary: #9ca3af;
    --user-bg: #eef2ff;
    --user-border: #c7d2fe;
    --assistant-bg: #ffffff;
    --assistant-border: #e5e7eb;
    --thinking-bg: #f5f3ff;
    --thinking-border: #ddd6fe;
    --tool-bg: #f0fdf4;
    --tool-border: #bbf7d0;
    --code-bg: #f1f5f9;
    --pre-bg: #1e293b;
    --pre-text: #e2e8f0;
    --accent: #6366f1;
    --accent-hover: #4f46e5;
    --shadow: 0 1px 3px rgba(0,0,0,0.06);
    --shadow-lg: 0 4px 12px rgba(0,0,0,0.08);
    --radius: 12px;
    --radius-sm: 6px;
}}

[data-theme="dark"] {{
    --bg: #0f172a;
    --surface: #1e293b;
    --border: #334155;
    --text: #e2e8f0;
    --text-secondary: #94a3b8;
    --text-tertiary: #64748b;
    --user-bg: #1e1b4b;
    --user-border: #3730a3;
    --assistant-bg: #1e293b;
    --assistant-border: #334155;
    --thinking-bg: #1e1b4b;
    --thinking-border: #3730a3;
    --tool-bg: #052e16;
    --tool-border: #166534;
    --code-bg: #1e293b;
    --pre-bg: #0f172a;
    --pre-text: #e2e8f0;
    --shadow: 0 1px 3px rgba(0,0,0,0.3);
    --shadow-lg: 0 4px 12px rgba(0,0,0,0.4);
}}

body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans SC", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.7;
    min-height: 100vh;
}}

/* ── Header ── */
header {{
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    box-shadow: var(--shadow);
    backdrop-filter: blur(12px);
}}
.header-left h1 {{
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--text);
}}
.header-left .meta {{
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-top: 2px;
}}
.header-right {{
    display: flex;
    align-items: center;
    gap: 12px;
}}

/* ── Theme Toggle ── */
.theme-btn {{
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 6px 14px;
    cursor: pointer;
    font-size: 0.85rem;
    color: var(--text-secondary);
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 6px;
}}
.theme-btn:hover {{
    background: var(--border);
    color: var(--text);
}}

/* ── Main Chat Area ── */
main {{
    max-width: 800px;
    margin: 0 auto;
    padding: 24px 16px 64px;
}}

/* ── Messages ── */
.msg {{
    display: flex;
    gap: 12px;
    margin-bottom: 24px;
    animation: fadeIn 0.3s ease;
}}
@keyframes fadeIn {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}

.msg-avatar {{
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.1rem;
    flex-shrink: 0;
    background: var(--code-bg);
    border: 1px solid var(--border);
}}

.msg-body {{
    flex: 1;
    min-width: 0;
}}

.msg-content {{
    padding: 14px 18px;
    border-radius: var(--radius);
    border: 1px solid var(--assistant-border);
    background: var(--assistant-bg);
    box-shadow: var(--shadow);
    font-size: 0.95rem;
}}

.msg-user .msg-content {{
    background: var(--user-bg);
    border-color: var(--user-border);
    box-shadow: var(--shadow-lg);
}}

.msg-content p {{ margin-bottom: 0.6em; }}
.msg-content p:last-child {{ margin-bottom: 0; }}
.msg-content ul, .msg-content ol {{ padding-left: 1.5em; margin: 0.4em 0; }}
.msg-content li {{ margin-bottom: 0.2em; }}
.msg-content h1, .msg-content h2, .msg-content h3,
.msg-content h4, .msg-content h5, .msg-content h6 {{
    font-weight: 600;
    margin: 1em 0 0.4em;
    line-height: 1.3;
}}
.msg-content h1 {{ font-size: 1.4rem; }}
.msg-content h2 {{ font-size: 1.2rem; border-bottom: 1px solid var(--border); padding-bottom: 0.3em; }}
.msg-content h3 {{ font-size: 1.05rem; }}
.msg-content h4 {{ font-size: 0.95rem; }}
.msg-content blockquote {{
    border-left: 3px solid var(--accent);
    padding: 0.3em 0.8em;
    margin: 0.5em 0;
    background: var(--code-bg);
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    color: var(--text-secondary);
}}
.msg-content a {{
    color: var(--accent);
    text-decoration: none;
}}
.msg-content a:hover {{ text-decoration: underline; }}
.msg-content hr {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 1em 0;
}}
.msg-content img {{ max-width: 100%; border-radius: var(--radius-sm); }}
.msg-content table {{
    width: 100%;
    border-collapse: collapse;
    margin: 0.5em 0;
    font-size: 0.9rem;
}}
.msg-content table th,
.msg-content table td {{
    border: 1px solid var(--border);
    padding: 8px 12px;
    text-align: left;
}}
.msg-content table th {{
    background: var(--code-bg);
    font-weight: 600;
}}

/* 行内代码 */
.msg-content :not(pre) > code {{
    background: var(--code-bg);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.88em;
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", Menlo, Consolas, monospace;
    border: 1px solid var(--border);
}}

/* 代码块 */
.msg-content pre {{
    background: var(--pre-bg);
    color: var(--pre-text);
    padding: 16px;
    border-radius: var(--radius-sm);
    overflow-x: auto;
    margin: 0.6em 0;
    font-size: 0.85rem;
    line-height: 1.5;
}}
.msg-content pre code {{
    background: none;
    padding: 0;
    border: none;
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", Menlo, Consolas, monospace;
    color: inherit;
}}

.msg-time {{
    font-size: 0.75rem;
    color: var(--text-tertiary);
    margin-top: 6px;
    padding-left: 4px;
}}

/* ── Thinking Blocks ── */
.thinking-block {{
    margin: 8px 0;
    border: 1px solid var(--thinking-border);
    border-radius: var(--radius-sm);
    background: var(--thinking-bg);
    overflow: hidden;
}}
.thinking-block summary {{
    padding: 10px 14px;
    cursor: pointer;
    font-size: 0.85rem;
    color: var(--text-secondary);
    user-select: none;
    display: flex;
    align-items: center;
    gap: 6px;
}}
.thinking-block summary:hover {{ background: rgba(0,0,0,0.03); }}
[data-theme="dark"] .thinking-block summary:hover {{ background: rgba(255,255,255,0.03); }}
.thinking-icon {{ font-size: 0.9rem; }}
.thinking-preview {{
    opacity: 0.6;
    font-style: italic;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    min-width: 0;
}}
.thinking-content {{
    padding: 12px 14px;
    border-top: 1px solid var(--thinking-border);
    font-size: 0.85rem;
    color: var(--text-secondary);
    white-space: pre-wrap;
    max-height: 400px;
    overflow-y: auto;
}}

/* ── Tool Blocks ── */
.tool-block {{
    margin: 8px 0;
    border: 1px solid var(--tool-border);
    border-radius: var(--radius-sm);
    background: var(--tool-bg);
    overflow: hidden;
}}
.tool-block summary {{
    padding: 10px 14px;
    cursor: pointer;
    font-size: 0.85rem;
    color: var(--text-secondary);
    user-select: none;
    display: flex;
    align-items: center;
    gap: 6px;
}}
.tool-block summary:hover {{ background: rgba(0,0,0,0.03); }}
[data-theme="dark"] .tool-block summary:hover {{ background: rgba(255,255,255,0.03); }}
.tool-icon {{ font-size: 0.9rem; }}
.tool-block summary code {{
    background: var(--code-bg);
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 0.82rem;
    border: 1px solid var(--border);
}}
.tool-input, .tool-output {{
    padding: 10px 14px;
    border-top: 1px solid var(--tool-border);
    font-size: 0.82rem;
}}
.tool-input strong, .tool-output strong {{
    display: block;
    margin-bottom: 6px;
    color: var(--text-secondary);
}}
.tool-input pre, .tool-output pre {{
    background: var(--pre-bg);
    color: var(--pre-text);
    padding: 12px;
    border-radius: 4px;
    overflow-x: auto;
    max-height: 300px;
    font-size: 0.78rem;
    line-height: 1.5;
    margin: 0;
}}
.tool-input pre code, .tool-output pre code {{
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", Menlo, Consolas, monospace;
}}

/* ── Footer ── */
footer {{
    text-align: center;
    padding: 32px 16px;
    color: var(--text-tertiary);
    font-size: 0.8rem;
}}

/* ── Print Styles ── */
@media print {{
    header {{ position: static; box-shadow: none; }}
    .theme-btn {{ display: none; }}
    .msg {{ break-inside: avoid; }}
    body {{ background: white; color: black; }}
    .msg-content {{ box-shadow: none; border: 1px solid #ddd; }}
    .msg-user .msg-content {{ background: #f5f5f5; }}
    .thinking-block, .tool-block {{ break-inside: avoid; border: 1px solid #ddd; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; }}
}}

/* ── Responsive ── */
@media (max-width: 640px) {{
    main {{ padding: 16px 10px 48px; }}
    .msg-content {{ padding: 12px 14px; font-size: 0.9rem; }}
    .msg-avatar {{ width: 30px; height: 30px; font-size: 0.9rem; }}
    .msg {{ gap: 8px; }}
    header {{ padding: 12px 14px; }}
    header h1 {{ font-size: 0.95rem; }}
}}
</style>
</head>
<body>
<header>
    <div class="header-left">
        <h1>{_esc(title_display)}</h1>
        <div class="meta">{date_display} · {len(turns)} 轮对话 · Claude Code</div>
    </div>
    <div class="header-right">
        <button class="theme-btn" onclick="toggleTheme()" title="切换暗色/亮色模式">
            <span id="theme-icon">🌙</span> <span id="theme-label">暗色</span>
        </button>
    </div>
</header>
<main>
    {''.join(messages_html)}
</main>
<footer>
    <p>由 Claude Code 对话导出工具生成 · {_esc(source_file)}</p>
    <p>{datetime.now(TZ_LOCAL).strftime('%Y-%m-%d %H:%M')} 导出</p>
</footer>
<script>
const STORAGE_KEY = 'claude-chat-export-theme';
function setTheme(theme) {{
    document.documentElement.setAttribute('data-theme', theme);
    const icon = document.getElementById('theme-icon');
    const label = document.getElementById('theme-label');
    if (theme === 'dark') {{
        icon.textContent = '☀️';
        label.textContent = '亮色';
    }} else {{
        icon.textContent = '🌙';
        label.textContent = '暗色';
    }}
    try {{ localStorage.setItem(STORAGE_KEY, theme); }} catch(e) {{}}
}}
function toggleTheme() {{
    const current = document.documentElement.getAttribute('data-theme');
    setTheme(current === 'dark' ? 'light' : 'dark');
}}
// 初始化主题（尊重系统偏好）
(function() {{
    try {{
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {{ setTheme(saved); return; }}
    }} catch(e) {{}}
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) {{
        setTheme('dark');
    }}
}})();
</script>
</body>
</html>'''

    return html


# ── CLI ───────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == '--list':
        project_dir = sys.argv[2] if len(sys.argv) > 2 else None
        sessions = find_sessions(project_dir)
        if not sessions:
            print("未找到对话文件。")
            sys.exit(0)
        print(f"{'#':<4} {'时间':<18} {'轮数':>4} 第一条消息")
        print("-" * 80)
        for i, s in enumerate(sessions):
            question = s.get('first_question', '') or '(非对话内容)'
            # 截断过长的消息
            if len(question) > 55:
                question = question[:52] + '...'
            print(f"{i:<4} {s['mtime']:<18} {s.get('turns', 0):>4}  {question}")
        print(f"\n共 {len(sessions)} 个对话文件。")
        print(f"导出方式：")
        print(f"  python3 scripts/export-chat.py <序号>            # 按序号导出")
        print(f"  python3 scripts/export-chat.py <uuid或文件路径>  # 按文件名导出")
        sys.exit(0)

    input_file = sys.argv[1]

    # 支持按序号导出（先列一次表）
    if input_file.isdigit():
        sessions = find_sessions()
        idx = int(input_file)
        if 0 <= idx < len(sessions):
            input_file = sessions[idx]['path']
            print(f"📌 已选择 #{idx}: {sessions[idx].get('first_question', '(无标题)')[:60]}")
        else:
            print(f"错误：序号 {idx} 超出范围（共 {len(sessions)} 个对话）", file=sys.stderr)
            sys.exit(1)

    if not os.path.exists(input_file):
        # 尝试在 ~/.claude/projects/ 下查找
        base = Path.home() / '.claude' / 'projects'
        attempted = base / input_file
        if attempted.exists():
            input_file = str(attempted)
        else:
            # 尝试按文件名匹配
            for jsonl in base.rglob('*.jsonl'):
                if jsonl.stem == input_file or jsonl.name == input_file:
                    input_file = str(jsonl)
                    break
            else:
                print(f"错误：文件不存在 - {input_file}", file=sys.stderr)
                print("提示：使用 --list 查看可用的对话文件。", file=sys.stderr)
                sys.exit(1)

    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    if not output_file:
        stem = Path(input_file).stem
        output_file = f'{stem}.html'

    print(f"📖 读取: {input_file}")
    events = parse_jsonl(input_file)
    turns, title = build_turns(events)

    if not turns:
        print("⚠️ 未找到有效的对话内容。", file=sys.stderr)
        sys.exit(1)

    print(f"💬 解析到 {len(turns)} 轮对话" + (f'，标题: {title}' if title else ''))
    print(f"🖨️  生成 HTML…")

    html = generate_html(turns, title, Path(input_file).name)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    file_size = os.path.getsize(output_file)
    print(f"✅ 已导出: {output_file} ({_format_size(file_size)})")
    print(f"🌐 在浏览器中打开查看，或直接分享这个 HTML 文件。")


if __name__ == '__main__':
    main()
