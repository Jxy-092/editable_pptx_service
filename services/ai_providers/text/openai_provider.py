"""
OpenAI SDK implementation for text generation
"""
import base64
import mimetypes
import logging
from typing import Generator
from openai import OpenAI
from .base import TextProvider, strip_think_tags
from config import get_config

logger = logging.getLogger(__name__)


class OpenAITextProvider(TextProvider):
    """Text generation using OpenAI SDK (compatible with Gemini via proxy)"""

    def __init__(self, api_key: str, api_base: str = None, model: str = "gemini-3-flash-preview"):
        """
        Initialize OpenAI text provider
        
        Args:
            api_key: API key
            api_base: API base URL (e.g., https://aihubmix.com/v1)
            model: Model name to use
        """
        self.client = OpenAI(
            api_key=api_key,
            base_url=api_base,
            default_query={"api-version": "2025-04-01-preview"},
            timeout=get_config().OPENAI_TIMEOUT,  # set timeout from config
            max_retries=get_config().OPENAI_MAX_RETRIES  # set max retries from config
        )
        self.model = model

    def generate_text(self, prompt: str, thinking_budget: int = 0) -> str:
        """
        Generate text using OpenAI SDK
        
        Args:
            prompt: The input prompt
            thinking_budget: Not used in OpenAI format, kept for interface compatibility (0 = default)
            
        Returns:
            Generated text
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return strip_think_tags(response.choices[0].message.content)

    def generate_text_stream(self, prompt: str, thinking_budget: int = 0) -> Generator[str, None, None]:
        """Stream text using OpenAI SDK with stream=True."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content


    def generate_with_image(self, prompt: str, image_path: str, thinking_budget: int = 0) -> str:
        """使用 OpenAI Responses API 分析图片并返回文本结果。"""
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = "image/png"

        with open(image_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")

        request_url = self._build_responses_request_url()
        start_time = time.perf_counter()

        logger.info(
            "Calling OpenAI Responses image understanding API: url=%s, params=%s",
            request_url,
            json.dumps(log_request_params, ensure_ascii=False),
        )
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime_type};base64,{encoded}",
                        },
                    ],
                }
            ],
        )
        log_request_params = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,<omitted>",
                        },
                    ],
                }
            ],
            "extra_query": OPENAI_RESPONSES_EXTRA_QUERY,
        }
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "OpenAI Responses image understanding API completed: url=%s, elapsed_ms=%.2f",
            request_url,
            elapsed_ms,
        )
        return strip_think_tags(response.output_text or "")
