# 书法拆字识别方案架构设计

## 背景与目标
- 识别竖排书法作品中的每个汉字及其BBOX坐标
- 测试图片：`/怀仁集王羲之圣教序/fatie-000.jpg`
- 使用 PaddleOCR PP-OCRv5 模型

## 核心挑战
1. 竖排文字：从右向左、从上往下排列
2. 单字分割：PP-OCRv5 倾向于整行检测，需要拆到单字

## 总体架构

```
Input Image
    ↓
[Image Preprocessor] - 图像增强、去噪、二值化（可选）
    ↓
[PP-OCRv5 API] - 文字检测+识别
    ↓
[Post Processor] - 竖排文字重排序 + 单字分割
    ↓
Output: [{text, bbox}, ...]
```

## 模块设计

### 1. Image Preprocessor（可选增强）
- 调整对比度
- 去噪处理
- 统一尺寸

### 2. PP-OCRv5 API 调用
- 调用社区 API
- 优化参数：降低 textDetLimitSideLen、textDetThresh 等以提高单字检测率
- 返回原始 OCR 结果

### 3. Post Processor（关键模块）
- **竖排排序**：根据 bbox 坐标对检测结果进行从右到左、从上到下的排序
- **单字分割策略**：
  - 策略 A：整行文字按字长均分（已知每行字数）
  - 策略 B：基于投影分析的字符分割
  - 策略 C：调整后再次调用 OCR 进行单字识别

### 4. Output Formatter
- 返回标准格式：{text: "字", bbox: [x1, y1, x2, y2]}

## 实现方案

采用两阶段识别：
1. 第一阶段：检测文字块（整行/整列）
2. 第二阶段：对每块内部进行单字分割

单字分割算法：
```python
# 对于竖排文字列，根据字数均分高度
num_chars = len(recognized_text)
char_height = (y2 - y1) / num_chars
for i, char in enumerate(text):
    bbox = [x1, y1 + i*char_height, x2, y1 + (i+1)*char_height]
```

## 文件结构
```
ocr/
  ├── __init__.py
  ├── config.py          # 配置参数
  ├── preprocessor.py    # 图像预处理
  ├── paddle_ocr.py      # PP-OCRv5 API 调用
  ├── post_processor.py  # 竖排排序 + 单字分割
  └── main.py            # 主入口
```
