# AGENTS.md

本文档为 AI 代理和开发者提供项目架构概述，帮助快速理解代码库结构。

## 项目概述

本项目是一个王羲之书法作品展示网站，包含两个主要部分：

1. **静态网站**：展示王羲之书法碑帖作品（兰亭序、十七帖、丧乱帖等）
2. **OCR 模块** (`ocr/`)：识别竖排书法作品中的文字及其边界框坐标

### 核心架构

```
项目根目录/
├── index.html              # 网站首页
├── {书法作品名称}/          # 各作品文件夹
│   ├── index.html          # 作品详情页
│   └── fatie-XXX.jpg       # 书法图片
├── ocr/                    # OCR 识别模块
│   ├── recognizer.py       # 主识别器（入口）
│   ├── api_client.py       # Layout Parsing API 客户端
│   ├── preprocess.py       # 图像预处理
│   ├── postprocess.py      # 后处理（竖排重排序、单字分割）
│   └── config.py           # 配置管理
└── {字帖目录}/.debug/      # OCR 输出结果（每张图一个子目录）
└── {字帖目录}/words/       # 拆解后的文字（每张图一个 txt）
```

## 构建与命令

### 静态网站

```bash
# 启动本地服务器
python3 -m http.server 8000
# 或
npx serve .
```

### OCR 模块

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install opencv-python-headless numpy requests python-dotenv

# 运行识别
python -m ocr.recognizer ./怀仁集王羲之圣教序/fatie-000.jpg --debug

# 运行测试
python ocr/test_ocr.py
```

### Python API 使用

```python
from ocr import recognize_calligraphy

# 识别书法图片
result = recognize_calligraphy("path/to/image.jpg", debug=True)

# 访问结果
print(result['recognized_text'])  # 识别的文字
print(result['total_chars'])       # 总字数
print(result['column_count'])      # 列数

# 访问单字信息
for char_info in result['char_results']:
    print(f"字: {char_info['char']}, bbox: {char_info['bbox']}")
```

## 代码风格

### Python 模块

- **类型注解**：使用 `typing` 模块的类型提示
- **文档字符串**：使用中文文档字符串，说明参数和返回值
- **命名规范**：遵循 PEP 8，函数使用 `snake_case`，类使用 `PascalCase`
- **模块组织**：每个模块有明确的单一职责

### 关键约定

- OCR 模块使用像素投影法进行单字分割（`recognizer.py:202-291`）
- 竖排文字从右向左、从上往下排序（`postprocess.py`）
- 边界框格式：`[x1, y1, x2, y2]`（左上角和右下角坐标）
- 列索引从右向左编号（最右列为第 0 列）

## 测试

### 测试文件

- `ocr/test_ocr.py`：OCR 功能测试脚本

### 测试执行

```bash
source venv/bin/activate
python ocr/test_ocr.py
```

### 测试内容

- 基本 OCR 功能
- OCR 结果详情
- 单字识别结果
- 列结构分析
- 输出文件检查

## 安全

### API 凭证管理

- **API Token**：通过环境变量 `OCR_API_TOKEN` 配置
- **API URL**：通过环境变量 `OCR_API_URL` 配置
- **配置文件**：`.env` 文件存储敏感配置，不应提交到版本控制

### 数据保护

- OCR API 使用 HTTPS 加密传输
- 图像通过 Base64 编码传输
- 本地输出文件存储在 `ocr_output/` 目录

## 配置

### 环境变量

在项目根目录创建 `.env` 文件：

```
OCR_API_URL=https://api.example.com/ocr
OCR_API_TOKEN=your_token_here
```

### 配置参数

编辑 `ocr/config.py` 修改：

- `VERTICAL_LAYOUT`：竖排布局参数（最小列宽、列高等）
- `CHAR_BBOX`：单字边界框参数（最小字高、重叠阈值等）
- `OUTPUT_DIR`：输出目录路径
- `SAVE_DEBUG_IMAGES`：是否保存调试图片

### 竖排布局配置

```python
VERTICAL_LAYOUT = {
    "direction": "right_to_left",      # 列排列方向
    "column_direction": "top_to_bottom", # 列内文字方向
    "min_column_width": 30,            # 最小列宽（像素）
    "min_column_height": 100,          # 最小列高（像素）
}
```

## OCR 算法说明

### 处理流程

1. **图像加载**：读取图像并获取基本信息
2. **API 调用**：调用 Layout Parsing API 进行文字检测
3. **结果解析**：提取识别文字和坐标信息
4. **竖排排序**：按从右向左、从上往下排序
5. **单字分割**：使用像素投影法分割单字边界框
6. **结果输出**：保存 JSON、文本和调试图片

### 单字分割算法

使用像素投影法（`recognizer.py:202-291`）：

1. 计算列区域每行的像素亮度投影
2. 找到亮度为 0 的分割点（空白行）
3. 根据分割点生成单字边界框
4. 自动从图像四角估算背景亮度阈值

### 输出文件

识别结果保存在字帖目录下：

- `{字帖目录}/.debug/<image_stem>/result.json`：完整识别结果
- `{字帖目录}/.debug/<image_stem>/chars.json`：单字信息（简化版，可编辑）
- `{字帖目录}/words/<image_stem>.txt`：拆解后的文字

## 开发注意事项

### 添加新书法作品

1. 创建文件夹（以作品名命名）
2. 添加 `index.html` 和书法图片 `fatie-XXX.jpg`
3. 在主 `index.html` 中添加链接

### OCR 模块扩展

- **新增 API 客户端**：继承或修改 `api_client.py`
- **自定义预处理**：扩展 `preprocess.py` 中的 `ImagePreprocessor`
- **调整分割算法**：修改 `recognizer.py` 中的 `_split_column_by_pixels`

### Sub-Agent 调度规则

**并行执行**（满足所有条件时）：
- 3 个以上相互独立的任务
- 任务间无共享状态
- 文件边界清晰无重叠

**串行执行**（满足任一条件时）：
- 任务有依赖关系（B 需要 A 的输出）
- 共享文件或状态（有合并冲突风险）
- 范围不明确需要先探索
