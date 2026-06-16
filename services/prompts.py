"""
AI Service Prompts - 集中管理所有 AI 服务的 prompt 模板

分区:
  1. 共享工具 & 常量    — 语言配置、格式化辅助、DRY 常量
  2. 大纲 Prompts       — 生成、解析、细化大纲
  3. 描述 Prompts       — 单页、流式、拆分、细化描述
  4. 图片生成 Prompts   — 文生图、图片编辑
  5. 图片处理 Prompts   — 背景提取、画质修复
  6. 内容提取 Prompts   — 文字属性、页面内容、排版分析、风格提取
  7. 旁白 Prompts        — TTS 播报视频旁白生成
"""
import json
import logging
import re
from typing import List, Dict, Optional, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.ai_service import ProjectContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 共享工具 & 常量
# ═══════════════════════════════════════════════════════════════════════════════


# --- 常量 ---

LANGUAGE_CONFIG = {
    'zh': {
        'name': '中文',
        'instruction': '请使用全中文输出。',
        'ppt_text': 'PPT文字请使用全中文。'
    },
    'ja': {
        'name': '日本語',
        'instruction': 'すべて日本語で出力してください。',
        'ppt_text': 'PPTのテキストは全て日本語で出力してください。'
    },
    'en': {
        'name': 'English',
        'instruction': 'Please output all in English.',
        'ppt_text': 'Use English for PPT text.'
    },
    'auto': {
        'name': '自动',
        'instruction': '',
        'ppt_text': ''
    }
}

DETAIL_LEVEL_SPECS = {
    'concise': '文字极致地压缩和精简，每条要点用一个核心词语或数据代替，例如效率↑80%',
    'default': '清晰明了，每条要点控制在15-20字以内，优先使用短语而非完整句子；落地到页面的文字建议在2-6句之内，避免冗长和复杂表述，为演示服务，而不是代替演讲人叙述。',
    'detailed': '忠于原文的基础上做到内容详实，逻辑清晰。',
}

DEFAULT_NARRATION_CONFIG = {
    'speaker_persona': 'knowledgeable and patient university professor',
    'target_audience': 'the general public with no technical background',
    'speech_tone': 'analytical, data-driven, and highly professional',
    'presentation_topic': 'the main ideas and key takeaways of this presentation',
    'min_words': 100,
    'max_words': 200,
}

_NARRATION_MIN_WORDS_LOWER_BOUND = 30
_NARRATION_MAX_WORDS_UPPER_BOUND = 300

_OUTLINE_JSON_FORMAT = """\
1. Simple format (for short PPTs without major sections):
[{"title": "title1", "points": ["point1", "point2"]}, {"title": "title2", "points": ["point1", "point2"]}]

2. Part-based format (for longer PPTs with major sections):
[
    {
    "part": "Part 1: Introduction",
    "pages": [
        {"title": "Welcome", "points": ["point1", "point2"]},
        {"title": "Overview", "points": ["point1", "point2"]}
    ]
    },
    {
    "part": "Part 2: Main Content",
    "pages": [
        {"title": "Topic 1", "points": ["point1", "point2"]},
        {"title": "Topic 2", "points": ["point1", "point2"]}
    ]
    }
]"""


# --- 辅助函数 ---

def _build_prompt(prompt_text: str, reference_files_content=None, *, tag: str = '') -> str:
    """Prepend reference files XML and log the final prompt."""
    files_xml = _format_reference_files_xml(reference_files_content)
    final = files_xml + prompt_text
    if tag:
        logger.debug(f"[{tag}] Final prompt:\n{final}")
    return final


def _get_original_input(project_context: 'ProjectContext') -> str:
    """Extract original user input from project context (shared across prompt builders)."""
    if project_context.creation_type == 'idea' and project_context.idea_prompt:
        return project_context.idea_prompt
    if project_context.creation_type == 'outline' and project_context.outline_text:
        return f"用户提供的大纲：\n{project_context.outline_text}"
    if project_context.creation_type == 'descriptions' and project_context.description_text:
        return f"用户提供的描述：\n{project_context.description_text}"
    return project_context.idea_prompt or ""


def _get_original_input_labeled(project_context: 'ProjectContext') -> str:
    """Build labeled original input section for refinement prompts."""
    text = "\n原始输入信息：\n"
    if project_context.creation_type == 'idea' and project_context.idea_prompt:
        text += f"- PPT构想：{project_context.idea_prompt}\n"
    elif project_context.creation_type == 'outline' and project_context.outline_text:
        text += f"- 用户提供的大纲文本：\n{project_context.outline_text}\n"
    elif project_context.creation_type == 'descriptions' and project_context.description_text:
        text += f"- 用户提供的页面描述文本：\n{project_context.description_text}\n"
    elif project_context.idea_prompt:
        text += f"- 用户输入：{project_context.idea_prompt}\n"
    return text


def _get_previous_requirements_text(previous_requirements: Optional[List[str]]) -> str:
    """Format previous modification history."""
    if not previous_requirements:
        return ""
    prev_list = "\n".join([f"- {req}" for req in previous_requirements])
    return f"\n\n之前用户提出的修改要求：\n{prev_list}\n"


def _normalize_word_count(value: Any, default: int) -> int:
    """Normalize narration word-count inputs to a safe integer range."""
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(_NARRATION_MIN_WORDS_LOWER_BOUND, min(_NARRATION_MAX_WORDS_UPPER_BOUND, normalized))


def get_default_narration_generation_config(fallback_topic: str = '') -> Dict[str, Any]:
    """Return the default narration config, filling topic from project context when possible."""
    config = dict(DEFAULT_NARRATION_CONFIG)
    topic = (fallback_topic or '').strip()
    if topic:
        config['presentation_topic'] = topic
    return config


def normalize_narration_generation_config(
    config: Optional[Dict[str, Any]] = None,
    fallback_topic: str = '',
) -> Dict[str, Any]:
    """Normalize narration generation options from UI/API payloads."""
    normalized = get_default_narration_generation_config(fallback_topic=fallback_topic)
    if not isinstance(config, dict):
        return normalized

    for field in ('speaker_persona', 'target_audience', 'speech_tone', 'presentation_topic'):
        value = config.get(field)
        if isinstance(value, str) and value.strip():
            normalized[field] = value.strip()

    min_words = _normalize_word_count(config.get('min_words'), normalized['min_words'])
    max_words = _normalize_word_count(config.get('max_words'), normalized['max_words'])
    if max_words < min_words:
        max_words = min_words

    normalized['min_words'] = min_words
    normalized['max_words'] = max_words
    return normalized


def parse_narration_generation_result(result: str) -> Dict[int, str]:
    """Parse batched narration output split by the `=== SLIDE n ===` delimiter."""
    if not result or not result.strip():
        return {}

    sections = re.split(r'===\s*SLIDE\s+(\d+)\s*===', result)
    if len(sections) <= 1:
        return {}

    parsed: Dict[int, str] = {}
    iterator = iter(sections[1:])
    for idx_str, text in zip(iterator, iterator):
        try:
            parsed[int(idx_str)] = text.strip()
        except ValueError:
            continue
    return parsed


def _format_extra_field_instructions(extra_fields: list | None) -> str:
    """将额外字段列表格式化为 prompt 中的输出要求。"""
    if not extra_fields:
        return ''
    parts = [f'{f}：[关于{f}的建议]' for f in extra_fields]
    return '\n'.join([''] + parts)  # 前导换行


def _format_reference_files_xml(reference_files_content: Optional[List[Dict[str, str]]]) -> str:
    """Format reference files content as XML structure."""
    if not reference_files_content:
        return ""
    xml_parts = ["<uploaded_files>"]
    for file_info in reference_files_content:
        filename = file_info.get('filename', 'unknown')
        content = file_info.get('content', '')
        xml_parts.append(f'  <file name="{filename}">')
        xml_parts.append('    <content>')
        xml_parts.append(content)
        xml_parts.append('    </content>')
        xml_parts.append('  </file>')
    xml_parts.append('</uploaded_files>')
    xml_parts.append('')  # Empty line after XML
    return '\n'.join(xml_parts)


def _format_requirements(requirements: str, context: str = "outline") -> str:
    """格式化用户提供的生成要求，返回可直接拼接到 prompt 中的文本段。

    context: "outline" 或 "description"，用于生成对应的结构标记示例。
    """
    if requirements and requirements.strip():
        if context == "description":
            marker_example = (
                "For example, if the user asks to avoid certain symbols, "
                "do NOT use them in the page content, but still use structural markers "
                "like '页面文字：', '图片素材：', and '<!-- PAGE_END -->' as-is."
            )
        else:
            marker_example = (
                "For example, if the user asks to avoid '#' symbols, "
                "do NOT use '#' in the page content, but still use '## Title' as "
                "the structural heading delimiter between pages."
            )
        return (
            "<user_requirements>\n"
            f"{requirements.strip()}\n"
            "</user_requirements>\n"
            "Note: The requirements above apply to the generated content of each page and "
            "take precedence over other content-related instructions. The required output format "
            f"and structural markers must still be used as-is. {marker_example}\n\n"
        )
    return ""


def get_default_output_language() -> str:
    """获取环境变量中配置的默认输出语言"""
    from config import Config
    return getattr(Config, 'OUTPUT_LANGUAGE', 'zh')


def get_language_instruction(language: str = None) -> str:
    """获取语言限制指令文本"""
    lang = language if language else get_default_output_language()
    config = LANGUAGE_CONFIG.get(lang, LANGUAGE_CONFIG['zh'])
    return config['instruction']


def get_ppt_language_instruction(language: str = None) -> str:
    """获取PPT文字语言限制指令"""
    lang = language if language else get_default_output_language()
    config = LANGUAGE_CONFIG.get(lang, LANGUAGE_CONFIG['zh'])
    return config['ppt_text']

def get_image_edit_prompt(edit_instruction: str, original_description: str = None) -> str:
    """生成图片编辑 prompt"""
    if original_description:
        if "其他页面素材" in original_description:
            original_description = original_description.split("其他页面素材")[0].strip()

        prompt = (f"""\
该PPT页面的原始页面描述为：
{original_description}

现在，根据以下指令修改这张PPT页面：{edit_instruction}

要求维持原有的文字内容和设计风格，只按照指令进行修改。提供的参考图中既有新素材，也有用户手动框选出的区域，请你根据原图和参考图的关系智能判断用户意图。
""")
    else:
        prompt = f"根据以下指令修改这张PPT页面：{edit_instruction}\n保持原有的内容结构和设计风格，只按照指令进行修改。提供的参考图中既有新素材，也有用户手动框选出的区域，请你根据原图和参考图的关系智能判断用户意图。"

    logger.debug(f"[get_image_edit_prompt] Final prompt:\n{prompt}")
    return prompt


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 图片处理 Prompts — 背景提取、画质修复
# ═══════════════════════════════════════════════════════════════════════════════


def get_clean_background_prompt(removal_regions: Optional[List[Dict[str, Any]]] = None) -> str:
    """生成纯背景图的 prompt（去除文字和插画）"""
    regions_info = ""
    if removal_regions:
        regions_json = json.dumps(removal_regions, ensure_ascii=False, indent=2)
        regions_info = f"""
以下是当前图片里需要重点移除的前景元素 bbox 列表，坐标都已经按当前图片宽高做了 0-1 归一化：

```json
{regions_json}
```

坐标说明：
- `bbox.x0`, `bbox.y0`：元素左上角坐标，范围 0-1
- `bbox.x1`, `bbox.y1`：元素右下角坐标，范围 0-1
- `bbox.width`, `bbox.height`：元素宽高占整张图的比例
- `element_type`：该区域的大致元素类型，如 `text` / `image` / `chart` / `table` / `figure`

请优先移除这些 bbox 内，以及与这些 bbox 紧贴或轻微重叠的所有前景内容，避免遗漏。
"""

    prompt = f"""\
你是一位专业的图片文字&图片擦除专家。你的任务是从原始图片中移除文字和配图，输出一张无任何文字和图表内容、干净纯净的底板图。
<requirements>
- 彻底移除页面中的所有文字、插画、图表。必须确保所有文字都被完全去除。
- 保持原背景设计的完整性（包括渐变、纹理、图案、线条、色块等）。保留原图的文本框和色块。
- 对于被前景元素遮挡的背景区域，要智能填补，使背景保持无缝和完整，就像被移除的元素从来没有出现过。
- 输出图片的尺寸、风格、配色必须和原图完全一致。
- 请勿新增任何元素。
</requirements>

{regions_info}

注意，**任意位置的, 所有的**文字和图表都应该被彻底移除，**输出不应该包含任何文字和图表。**
"""
    logger.debug(f"[get_clean_background_prompt] Final prompt:\n{prompt}")
    return prompt


def get_quality_enhancement_prompt(inpainted_regions: list = None) -> str:
    """生成画质提升的 prompt（用于百度图像修复后的画质修复）"""
    regions_info = ""
    if inpainted_regions and len(inpainted_regions) > 0:
        regions_json = json.dumps(inpainted_regions, ensure_ascii=False, indent=2)
        regions_info = f"""
以下是被抹除工具处理过的具体区域（共 {len(inpainted_regions)} 个矩形区域），请重点修复这些位置：

```json
{regions_json}
```

坐标说明（所有数值都是相对于图片宽高的百分比，范围0-100%）：
- left: 区域左边缘距离图片左边缘的百分比
- top: 区域上边缘距离图片上边缘的百分比
- right: 区域右边缘距离图片左边缘的百分比
- bottom: 区域下边缘距离图片上边缘的百分比
- width_percent: 区域宽度占图片宽度的百分比
- height_percent: 区域高度占图片高度的百分比

例如：left=10 表示区域从图片左侧10%的位置开始。
"""

    prompt = f"""\
你是一位专业的图像修复专家。这张ppt页面图片刚刚经过了文字/对象抹除操作，抹除工具在指定区域留下了一些修复痕迹，包括：
- 色块不均匀、颜色不连贯
- 模糊的斑块或涂抹痕迹
- 与周围背景不协调的区域，比如不和谐的渐变色块
- 可能的纹理断裂或图案不连续
{regions_info}
你的任务是修复这些抹除痕迹，让图片看起来像从未有过对象抹除操作一样自然。

要求：
- **重点修复上述标注的区域**：这些区域刚刚经过抹除处理，需要让它们与周围背景完美融合
- 保持纹理、颜色、图案的连续性
- 提升整体画质，消除模糊、噪点、伪影
- 保持图片的原始构图、布局、色调风格
- 禁止添加任何文字、图表、插画、图案、边框等元素
- 除了上述区域，其他区域不要做任何修改，保持和原图像素级别地一致。
- 输出图片的尺寸必须与原图一致

请输出修复后的高清ppt页面背景图片，不要遗漏修复任何一个被涂抹的区域。
"""
    return prompt


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 内容提取 Prompts — 文字属性、页面内容、排版分析、风格提取
# ═══════════════════════════════════════════════════════════════════════════════


def get_text_attribute_extraction_prompt(content_hint: str = "") -> str:
    """生成文字属性提取的 prompt（提取文字内容、颜色、公式等信息）"""
    prompt = """你的任务是精确识别这张图片中的文字内容和样式，返回JSON格式的结果。

{content_hint}

## 核心任务
请仔细观察图片，精确识别：
1. **文字内容** - 输出你实际看到的文字符号。
2. **颜色** - 每个字/词的实际颜色
3. **空格** - 精确识别文本中空格的位置和数量
4. **公式** - 如果是数学公式，输出 LaTeX 格式

## 注意事项
- **空格识别**：必须精确还原空格数量，多个连续空格要完整保留，不要合并或省略
- **颜色分割**：一行文字可能有多种颜色，按颜色分割成片段，一般来说只有两种颜色。
- **公式识别**：如果片段是数学公式，设置 is_latex=true 并用 LaTeX 格式输出
- **相邻合并**：相同颜色的相邻普通文字应合并为一个片段

## 输出格式
- colored_segments: 文字片段数组，每个片段包含：
  - text: 文字内容（公式时为 LaTeX 格式，如 "x^2"、"\\sum_{{i=1}}^n"）
  - color: 颜色，十六进制格式 "#RRGGBB"
  - is_latex: 布尔值，true 表示这是一个 LaTeX 公式片段（可选，默认 false）

只返回JSON对象，不要包含任何其他文字。
示例输出：
```json
{{
    "colored_segments": [
        {{"text": "·  创新合成", "color": "#000000"}},
        {{"text": "1827个任务环境", "color": "#26397A"}},
        {{"text": "与", "color": "#000000"}},
        {{"text": "8.5万提示词", "color": "#26397A"}},
        {{"text": "突破数据瓶颈", "color": "#000000"}},
        {{"text": "x^2 + y^2 = z^2", "color": "#FF0000", "is_latex": true}}
    ]
}}
```
""".format(content_hint=content_hint)

    return prompt


def get_batch_text_attribute_extraction_prompt(text_elements_json: str) -> str:
    """生成批量文字属性提取的 prompt（给模型全图 + 所有文本元素的 bbox）"""
    prompt = f"""你是一位专业的 PPT/文档排版分析专家。请分析这张图片中所有标注的文字区域的样式属性。

我已经从图片中提取了以下文字元素及其位置信息：

```json
{text_elements_json}
```

请仔细观察图片，对比每个文字区域在图片中的实际视觉效果，为每个元素分析以下属性：

1. **font_color**: 字体颜色的十六进制值，格式为 "#RRGGBB"
   - 请仔细观察文字的实际颜色，不要只返回黑色
   - 常见颜色如：白色 "#FFFFFF"、蓝色 "#0066CC"、红色 "#FF0000" 等

2. **is_bold**: 是否为粗体 (true/false)
   - 观察笔画粗细，标题通常是粗体

3. **is_italic**: 是否为斜体 (true/false)

4. **is_underline**: 是否有下划线 (true/false)

5. **text_alignment**: 文字对齐方式
   - "left": 左对齐
   - "center": 居中对齐
   - "right": 右对齐
   - "justify": 两端对齐
   - 如果无法判断，根据文字在其区域内的位置推测

请返回一个 JSON 数组，数组中每个对象对应输入的一个元素（按相同顺序），包含以下字段：
- element_id: 与输入相同的元素ID
- text_content: 文字内容
- font_color: 颜色十六进制值
- is_bold: 布尔值
- is_italic: 布尔值
- is_underline: 布尔值
- text_alignment: 对齐方式字符串

只返回 JSON 数组，不要包含其他文字：
```json
[
    {{
        "element_id": "xxx",
        "text_content": "文字内容",
        "font_color": "#RRGGBB",
        "is_bold": true/false,
        "is_italic": true/false,
        "is_underline": true/false,
        "text_alignment": "对齐方式"
    }},
    ...
]
```
"""

    return prompt


def get_ppt_page_content_extraction_prompt(markdown_text: str, language: str = None) -> str:
    """从 fileparser 解析出的 markdown 文本中提取页面内容（title, points, description）"""
    prompt = f"""\
You are a helpful assistant that extracts structured PPT page content from parsed document text.

The following markdown text was extracted from a single PPT slide:

<slide_content>
{markdown_text}
</slide_content>

Your task is to extract the following structured information from this slide:

1. **title**: The main title/heading of the slide
2. **points**: A list of key bullet points or content items on the slide
3. **description**: A complete page description suitable for regenerating this slide, following this format:

页面标题：[title]

页面文字：
- [point 1]
- [point 2]
...

其他页面素材（如果有图表、表格、公式等描述，保留原文中的markdown图片完整形式）

Rules:
- Extract the title faithfully from the first heading in the markdown. Do NOT invent or rephrase it
- Points must be extracted verbatim from the slide content, in their original order
- In the description, 页面标题 and 页面文字 must be copied verbatim from the original text (punctuation may be normalized, but wording must be identical)
- The description should capture ALL content on the slide including text, data, and visual element descriptions
- If there are tables, charts, or formulas, describe them in the description under "其他页面素材"
- Preserve the original language of the content

Return a JSON object with exactly these three fields: "title", "points" (array of strings), "description" (string).
Return only the JSON, no other text.
{get_language_instruction(language)}
"""
    logger.debug(f"[get_ppt_page_content_extraction_prompt] Final prompt:\n{prompt}")
    return prompt


def get_layout_caption_prompt() -> str:
    """描述 PPT 页面的排版布局（给 caption model 用）"""
    prompt = """\
You are a professional PPT layout analyst. Describe the visual layout and composition of this PPT slide image in detail.

Focus on:
1. **Overall layout**: How elements are arranged (e.g., title at top, content in two columns, image on the right)
2. **Text placement**: Where text blocks are positioned, their relative sizes, alignment
3. **Visual elements**: Position and size of images, charts, icons, decorative elements
4. **Spacing and proportions**: How space is distributed between elements

Output a concise layout description in Chinese that can be used to recreate a similar layout. Format:

排版布局：
- 整体结构：[描述]
- 标题位置：[描述]
- 内容区域：[描述]
- 视觉元素：[描述]

Only describe the layout and spatial arrangement. Do not describe colors, text content, or style.
"""
    logger.debug(f"[get_layout_caption_prompt] Final prompt:\n{prompt}")
    return prompt


def get_style_extraction_prompt() -> str:
    """从图片中提取风格描述（通用，可复用于所有创建模式）"""
    prompt = """\
You are a professional PPT design analyst. Analyze this image and extract a detailed style description that can be used to generate PPT slides with a similar visual style.

Focus on:
1. **Color palette**: Primary colors, secondary colors, accent colors, background colors
2. **Typography style**: Font style impression (serif/sans-serif, weight, size hierarchy)
3. **Design elements**: Decorative patterns, shapes, icons style, borders, shadows
4. **Overall mood**: Professional, playful, minimalist, corporate, creative, etc.
5. **Layout tendencies**: How content is typically arranged, spacing preferences

Output a concise style description in Chinese that can be directly used as a style prompt for PPT generation. Write it as a single paragraph, not a list. Example:

"采用深蓝色渐变背景，搭配白色和金色文字。整体风格简约商务，使用无衬线字体，标题加粗突出。页面装饰以几何线条和半透明色块为主，配色统一协调。内容区域留白充足，视觉层次分明。"

Only output the style description text, no other content.
"""
    logger.debug(f"[get_style_extraction_prompt] Final prompt:\n{prompt}")
    return prompt
