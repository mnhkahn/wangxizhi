# OCR Module for Chinese Calligraphy

书法拆字识别模块 - 专为竖排书法作品设计

## 功能特性

- 支持 PaddleOCR PP-OCRv5 API
- 自动处理竖排文字布局（从右向左、从上往下）
- 单字边界框(bbox)计算
- 已知文字校验
- 调试图片输出

## 安装依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install opencv-python-headless numpy requests
```

## 使用方法

### 基本用法

```python
from ocr import recognize_calligraphy

# 识别书法图片
result = recognize_calligraphy("path/to/image.jpg")

print(f"识别文字: {result['recognized_text']}")
print(f"总字数: {result['total_chars']}")
print(f"列数: {result['column_count']}")
```

### 使用已知文字校验

```python
known_text = "大唐三藏聖教序..."
result = recognize_calligraphy("image.jpg", known_text=known_text)

# 比对识别结果
for char_info in result['char_results']:
    if char_info.get('expected_char'):
        print(f"识别: {char_info['char']}, 期望: {char_info['expected_char']}")
```

### 访问单字Bbox

```python
for char_info in result['char_results']:
    char = char_info['char']        # 单字
    bbox = char_info['bbox']        # [x1, y1, x2, y2]
    column = char_info['column']    # 列索引（从右向左，0开始）
    row = char_info['row']          # 行索引（从上往下，0开始）
```

### 调试模式

```python
result = recognize_calligraphy("image.jpg", debug=True)
# 会输出调试信息并保存调试图片到 ocr_output/ 目录
```

## 命令行使用

```bash
source venv/bin/activate
python -m ocr.recognizer image.jpg --debug
```

## 输出文件

识别结果保存在 `ocr_output/<image_name>/` 目录：

- `result.json` - 完整识别结果
- `chars.json` - 单字信息（简化版）
- `text.txt` - 纯文本
- `debug_*.jpg` - 调试图片（bbox可视化）

## 模块结构

```
ocr/
├── __init__.py      # 模块入口
├── config.py        # 配置（API地址、Token等）
├── preprocess.py    # 图像预处理
├── api_client.py    # OCR API调用
├── postprocess.py   # 后处理（竖排重排序、单字bbox）
├── recognizer.py    # 主识别器
├── test_ocr.py      # 测试脚本
└── example_usage.py # 使用示例
```

## 测试

```bash
source venv/bin/activate
python ocr/test_ocr.py
```

## 配置

编辑 `config.py` 修改：

- `API_URL` - OCR API地址
- `API_TOKEN` - API认证Token
- `KNOWN_TEXTS` - 已知文字内容（用于校验）

## 算法说明

竖排书法的列结构分析：

1. OCR检测返回多个文本区域（每区域可能是整列或部分）
2. 根据x坐标聚类检测项，识别列结构
3. 按x坐标从大到小排序（从右向左）
4. 每列内按y坐标排序（从上往下）
5. 将列的bbox均分给每个字（书法文字间隔均匀）

## 注意事项

- API会自动缩放大图（最大1500px）以提高识别速度
- Bbox坐标已映射回原始图像尺寸
- 首次使用需要配置正确的API Token
