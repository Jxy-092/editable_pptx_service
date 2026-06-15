from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class TextStyleResult:
    font_color_rgb: Optional[Tuple[int, int, int]] = None
    colored_segments: list = field(default_factory=list)
    is_bold: bool = False
    is_italic: bool = False
    is_underline: bool = False
    text_alignment: Optional[str] = None
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
