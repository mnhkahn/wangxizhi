# 王羲之法帖

这是一个围绕王羲之法帖整理与拆字处理的项目，当前包含 3 个可直接使用的部分：

- 静态网站：浏览各个法帖页面与图片
- OCR 命令行模块：对单张书法图片做识别与拆字
- 桌面编辑器：对 OCR 结果进行查看、修订、保存与导出

## 项目结构

```text
.
├── index.html                 # 静态网站首页
├── 王羲之-*/                   # 各法帖目录，内含 index.html 和 fatie-*.jpg
├── ocr/                       # OCR 模块
├── app/                       # PyQt 桌面编辑器
├── run_app.py                 # 桌面编辑器启动入口
└── requirements-app.txt       # 编辑器 + OCR 依赖
```

当前法帖目录命名采用 `作者-字体-作品` 的形式，例如：

- `王羲之-行书-圣教序`
- `王羲之-行书-兰亭序`
- `王羲之-草书-丧乱帖`

## 快速开始

### 1. 安装依赖

在项目根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-app.txt
```

如果你只想使用 OCR，也至少需要这些依赖：

```bash
pip install opencv-python-headless numpy requests python-dotenv
```

### 2. 配置 OCR 环境变量

OCR 会从项目根目录的 `.env` 读取配置。新建 `.env`：

```dotenv
OCR_API_URL=https://your-layout-parsing-api
OCR_API_TOKEN=your_token_here
```

也可以临时在终端中设置：

```bash
export OCR_API_URL="https://your-layout-parsing-api"
export OCR_API_TOKEN="your_token_here"
```

## 使用方式

### 静态网站

项目站点是纯静态页面，不需要 `npm install`。

启动方式：

```bash
python3 -m http.server 8000
```

打开：

```text
http://127.0.0.1:8000/
```

如需直接访问某个法帖目录，可打开例如：

```text
http://127.0.0.1:8000/王羲之-行书-圣教序/
http://127.0.0.1:8000/王羲之-行书-兰亭序/
```

说明：首页中的部分链接仍沿用旧目录命名，若点击后无法进入，请直接使用真实目录名访问。

### OCR 命令行

#### 识别单张图片

```bash
source .venv/bin/activate
python3 -m ocr.recognizer "./王羲之-行书-圣教序/fatie-000.jpg" --debug
```

参数说明：

- `image_path`：必填，目标图片路径
- `--debug` / `-d`：输出调试日志
- `--output` / `-o`：当前命令行参数已保留，但识别结果实际仍保存到图片所在字帖目录下

#### 验证拆字效果

单张图片验证：

```bash
source .venv/bin/activate
python3 ocr/validate_split.py "./王羲之-行书-圣教序/fatie-000.jpg" --debug
```

目录批量验证：

```bash
source .venv/bin/activate
python3 ocr/validate_split.py "./王羲之-行书-圣教序" --batch --debug
```

说明：当前 `--batch` 仅会处理目录内前 5 张图片，用于快速验证，不是全量批处理。

### 桌面编辑器

启动：

```bash
source .venv/bin/activate
python3 run_app.py
```

桌面编辑器适合对识别结果进行人工校正，主流程如下：

1. 在左侧字帖树中选择一个字帖目录或某张图片
2. 点击“识别”
   - 选中字帖目录时：批量识别该目录下所有 `fatie-*.jpg`
   - 选中单张图片时：仅识别当前图片
3. 在画布与字符列表中检查识别结果，按需调整框与字符信息
4. 点击“保存编辑”，将修改写回对应的 `chars.json`，并同步生成 `words/<image_stem>.txt`
5. 点击“导出”，汇总导出全量字形数据（后台线程执行，状态栏显示进度，不阻塞 UI）
6. （可选）点击“上传”，把导出产物 `*/words/*.webp` 批量上传到 Cloudinary（后台线程执行，状态栏显示进度）

工具栏增强：

- 右侧新增“搜字”输入框：输入单字回车后，会在所有 `chars.json` 中查找，命中后自动跳转到对应图片，并自动选中该字对应的框/列表项

常用操作：

- `Cmd+S` / `Ctrl+S`：保存编辑
- `Cmd+Z` / `Ctrl+Z`：撤销
- `Shift+Cmd+Z` / `Ctrl+Shift+Z`：重做
- `Delete`：删除当前项
- `Ctrl + 鼠标滚轮`：缩放画布

## 输出结果

### OCR 缓存文件

识别结果会写入图片所在字帖目录，而不是统一写到 `ocr_output/`：

```text
<字帖目录>/.debug/<图片名>/result.json
<字帖目录>/.debug/<图片名>/chars.json
```

例如：

```text
王羲之-行书-圣教序/.debug/fatie-000/result.json
王羲之-行书-圣教序/.debug/fatie-000/chars.json
```

### 编辑器保存结果

桌面编辑器保存时会同时写入：

```text
<字帖目录>/.debug/<图片名>/chars.json
<字帖目录>/words/<图片名>.txt
```

### 导出结果

桌面编辑器执行“导出”后会生成：

```text
ocr_output/glyphs.sqlite
<字帖目录>/words/<字符ID>.webp
```

其中：

- `glyphs.sqlite`：汇总所有已识别字形元数据
- `words/<字符ID>.webp`：按字符边界框裁剪出的单字图片（若文件名重复会直接覆盖）

## 调试命令

### 查看 glyphs.sqlite 记录数

```bash
sqlite3 ocr_output/glyphs.sqlite 'SELECT COUNT(*) FROM glyphs;'
```

### 查看 glyphs.sqlite 前5条记录

```bash
sqlite3 ocr_output/glyphs.sqlite 'SELECT * FROM glyphs LIMIT 5;'
```

## 推荐操作手段

### 场景一：只浏览网站

```bash
python3 -m http.server 8000
```

### 场景二：只跑 OCR 识别

```bash
source .venv/bin/activate
python3 -m ocr.recognizer "./王羲之-行书-圣教序/fatie-000.jpg" --debug
```

### 场景三：批量识别并人工校对

1. 配好 `.env`
2. 启动 `python3 run_app.py`
3. 在左侧选择字帖目录
4. 点击“识别”批量生成缓存
5. 逐张检查并点击“保存编辑”
6. 最后执行“导出”汇总数据

## 当前已知说明

- 首页部分链接名与实际目录名不一致，浏览时优先以真实目录为准
- `ocr/validate_split.py` 默认示例路径仍是旧目录名，实际使用时请手动传入现有图片路径
- `ocr.recognizer` 的 `--output` 参数当前不会改变最终缓存落盘位置
- OCR 调试图片目前未默认输出，核心结果以 `result.json`、`chars.json` 和 `words/*.txt` 为准
