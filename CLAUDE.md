# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a static website showcasing Chinese calligraphy (书法碑帖) by Wang Xizhi (王羲之), the famous Eastern Jin calligrapher known as the "Sage of Calligraphy" (书圣).

## Architecture

- **Static HTML site** using Bootstrap 3.1.1 from CDN
- **Structure**:
  - `index.html` - Homepage listing all calligraphy works
  - `{法帖名称}/` - Each calligraphy work has its own folder
    - `index.html` - Detail page showing calligraphy images (faties)
    - `.data.json` - Metadata: name, dynasty, category, text content, author info
    - `fatie-XXX.jpg` - Calligraphy image files

## Development

This is a static site—no build process required. Simply serve the files with any HTTP server:

```bash
python3 -m http.server 8000
# or
npx serve .
```

## Content Management

Each calligraphy folder contains a `.data.json` file with structured metadata including:
- `name` - Calligraphy title
- `dynasty` - Historical period
- `category` - Type (草书/行书/etc.)
- `text` - Full description, interpretation, and analysis
- `author` - Attribution

The homepage (`index.html`) links to each work manually. New works require:
1. Creating a folder with the work's name
2. Adding `index.html` and `.data.json`
3. Adding `fatie-XXX.jpg` images
4. Adding a link in the main `index.html`

## Key Works

The site features major Wang Xizhi works including:
- 兰亭序 (Orchid Pavilion Preface)
- 丧乱帖 (Sangluan Scroll)
- 十七帖 (Seventeen Posts)
- 快雪时晴帖 (Kuai Xue Shi Qing Scroll)
- And others


## Sub-Agent 调度规则

**并行执行**（满足所有条件时）：
- 3个以上相互独立的任务
- 任务间无共享状态
- 文件边界清晰无重叠

**串行执行**（满足任一条件时）：
- 任务有依赖关系（B 需要 A 的输出）
- 共享文件或状态（有合并冲突风险）
- 范围不明确需要先探索
