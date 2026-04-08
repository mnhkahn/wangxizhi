"""
OCR API Client Module
OCR API调用模块 - 使用 layout-parsing API
"""

import os
import base64
import requests
import time
from typing import Dict, List, Optional, Any
from pathlib import Path

from .config import (
    API_URL,
    API_TOKEN,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
)


class OCRAPIClient:
    """Layout Parsing API 客户端"""

    def __init__(
        self,
        api_url: str = API_URL,
        token: str = API_TOKEN,
    ):
        self.api_url = api_url
        self.token = token

    def _encode_file(self, file_path: str) -> str:
        """
        将文件编码为base64字符串

        Args:
            file_path: 文件路径

        Returns:
            base64编码的字符串
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")

    def _get_file_type(self, file_path: str) -> int:
        """
        获取文件类型

        Args:
            file_path: 文件路径

        Returns:
            0 for PDF, 1 for image
        """
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            return 0
        return 1  # 默认视为图片

    def recognize(
        self,
        file_path: str,
        markdown_ignore_labels: Optional[List[str]] = None,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_layout_detection: bool = False,
        use_chart_recognition: bool = False,
        use_seal_recognition: bool = False,
        use_ocr_for_image_block: bool = True,
        merge_tables: bool = True,
        relevel_titles: bool = True,
    ) -> Dict[str, Any]:
        """
        调用Layout Parssing API进行文档解析

        Args:
            file_path: 图像或PDF文件路径
            markdown_ignore_labels: 忽略的标签列表
            use_doc_orientation_classify: 是否检测文档方向
            use_doc_unwarping: 是否去扭曲
            use_layout_detection: 是否检测布局
            use_chart_recognition: 是否识别图表
            use_seal_recognition: 是否识别印章
            use_ocr_for_image_block: 是否对图像块进行OCR
            merge_tables: 是否合并表格
            relevel_titles: 是否重新调整标题级别

        Returns:
            API响应字典
        """
        # 编码文件
        file_data = self._encode_file(file_path)
        file_type = self._get_file_type(file_path)

        # 构建请求头
        headers = {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json",
        }

        # 必需参数
        required_payload = {
            "file": file_data,
            "fileType": file_type,
        }

        # 可选参数
        optional_payload = {
            "markdownIgnoreLabels": markdown_ignore_labels
            or [
                "header",
                "header_image",
                "footer",
                "footer_image",
                "number",
                "footnote",
                "aside_text",
            ],
            "useDocOrientationClassify": use_doc_orientation_classify,
            "useDocUnwarping": use_doc_unwarping,
            "useLayoutDetection": use_layout_detection,
            "useChartRecognition": use_chart_recognition,
            "useSealRecognition": use_seal_recognition,
            "useOcrForImageBlock": use_ocr_for_image_block,
            "mergeTables": merge_tables,
            "relevelTitles": relevel_titles,
            "layoutShapeMode": "auto",
            "promptLabel": "spotting",
            "repetitionPenalty": 1,
            "temperature": 0,
            "topP": 1,
            "minPixels": 51586,
            "maxPixels": 2822400,
            "layoutNms": True,
            "restructurePages": True,
        }

        payload = {**required_payload, **optional_payload}

        # 发送请求（带重试）
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                result = response.json()

                # 检查错误码: errorCode 在外层，result 包含实际数据
                if result.get("errorCode") != 0:
                    raise RuntimeError(f"API error: {result.get('errorMsg', 'Unknown error')}")

                return result.get("result", {})

            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))

        raise RuntimeError(f"OCR API request failed after {MAX_RETRIES} retries: {last_error}")

    def recognize_raw(self, file_path: str) -> Dict[str, Any]:
        """直接调用API并返回原始响应（用于调试）"""
        file_data = self._encode_file(file_path)
        file_type = self._get_file_type(file_path)

        headers = {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json",
        }

        payload = {
            "file": file_data,
            "fileType": file_type,
        }

        response = requests.post(
            self.api_url,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "text": response.text[:2000],
        }

    def save_results(
        self,
        result: Dict[str, Any],
        output_dir: str = "output",
    ) -> List[str]:
        """
        保存解析结果

        Args:
            result: API响应结果
            output_dir: 输出目录

        Returns:
            保存的文件路径列表
        """
        os.makedirs(output_dir, exist_ok=True)
        saved_files = []

        layout_results = result.get("layoutParsingResults", [])
        for i, res in enumerate(layout_results):
            # 保存Markdown文件
            md_filename = os.path.join(output_dir, f"doc_{i}.md")
            with open(md_filename, "w", encoding="utf-8") as md_file:
                md_file.write(res.get("markdown", {}).get("text", ""))
            saved_files.append(md_filename)

            # 保存markdown中的图片
            for img_path, img_url in res.get("markdown", {}).get("images", {}).items():
                full_img_path = os.path.join(output_dir, img_path)
                os.makedirs(os.path.dirname(full_img_path), exist_ok=True)
                try:
                    img_bytes = requests.get(img_url).content
                    with open(full_img_path, "wb") as img_file:
                        img_file.write(img_bytes)
                    saved_files.append(full_img_path)
                except Exception as e:
                    print(f"Failed to download image {img_path}: {e}")

            # 保存outputImages中的图片
            for img_name, img_url in res.get("outputImages", {}).items():
                try:
                    img_response = requests.get(img_url)
                    if img_response.status_code == 200:
                        filename = os.path.join(output_dir, f"{img_name}_{i}.jpg")
                        with open(filename, "wb") as f:
                            f.write(img_response.content)
                        saved_files.append(filename)
                except Exception as e:
                    print(f"Failed to download output image {img_name}: {e}")

        return saved_files