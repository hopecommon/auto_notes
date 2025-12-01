"""
Auto Notes 通用工具模块
======================
集中管理可复用的工具函数，避免代码散落多处。

包含：
- 环境变量加载（.env 文件）
- 文件名处理
- 文本清洗
- 日志配置
- 其他通用工具
"""

import os
import re
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any

# ================= 模块目录 =================
MODULE_DIR = Path(__file__).resolve().parent


# ================= 环境变量加载 =================
_env_loaded = False


def load_dotenv(env_path: Optional[Path] = None, override: bool = False) -> Dict[str, str]:
    """
    加载 .env 文件中的环境变量（不依赖 python-dotenv）
    
    Args:
        env_path: .env 文件路径，默认为模块目录下的 .env
        override: 是否覆盖已存在的环境变量，默认 False
        
    Returns:
        加载的环境变量字典
    """
    global _env_loaded
    
    if env_path is None:
        env_path = MODULE_DIR / ".env"
    
    loaded_vars = {}
    
    if not env_path.exists():
        return loaded_vars
    
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith("#"):
                    continue
                # 解析 KEY=VALUE
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # 移除引号
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    # 根据 override 决定是否覆盖
                    if key:
                        if override or key not in os.environ:
                            os.environ[key] = value
                            loaded_vars[key] = value
        _env_loaded = True
    except Exception as e:
        print(f"Warning: 加载 .env 文件失败: {e}", file=sys.stderr)
    
    return loaded_vars


def ensure_env_loaded():
    """确保环境变量已加载（幂等操作）"""
    global _env_loaded
    if not _env_loaded:
        load_dotenv()


# ================= 配置读取 =================
def get_config(key: str, default: Any = None, cast_type: type = str) -> Any:
    """
    获取配置值，优先从环境变量读取
    
    Args:
        key: 配置键名
        default: 默认值
        cast_type: 类型转换（str, int, float, bool）
        
    Returns:
        配置值
    """
    ensure_env_loaded()
    value = os.getenv(key)
    
    if value is None:
        return default
    
    if cast_type == bool:
        return value.lower() in ('true', '1', 'yes', 'on')
    
    try:
        return cast_type(value)
    except (ValueError, TypeError):
        return default


# ================= 文件名处理 =================
def sanitize_filename(name: str, replacement: str = "") -> str:
    """
    清理文件名，移除非法字符
    
    Args:
        name: 原始文件名
        replacement: 替换非法字符的字符串，默认为空
        
    Returns:
        清理后的文件名
    """
    # Windows 非法字符: \ / * ? : " < > |
    return re.sub(r'[\\/*?:"<>|]', replacement, name)


def parse_course_metadata(course_name: str, lesson_title: str) -> str:
    """
    解析课程元数据，生成格式化的文件名
    
    Args:
        course_name: 课程名称
        lesson_title: 课时标题（可能包含日期时间）
        
    Returns:
        格式化的文件名（不含扩展名）
    """
    import time
    
    # 提取课程名（去除括号内容）
    course = course_name.split('(')[0].strip() if '(' in course_name else course_name.strip()
    
    # 尝试提取日期时间
    date_pattern = r'(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})'
    match = re.search(date_pattern, lesson_title)
    
    if match:
        year, month, day, hour, minute = match.groups()
        formatted_name = f"{course}-{month}{day}-{hour}{minute}"
    else:
        formatted_name = f"{course}-{int(time.time())}"
    
    return sanitize_filename(formatted_name)


# ================= 文本清洗 =================
def clean_model_output(text: str) -> str:
    """
    清洗 AI 模型输出，移除 BOM、空白和客套前缀
    
    Args:
        text: 原始模型输出
        
    Returns:
        清洗后的文本
    """
    if not text:
        return ""
    
    # 移除 BOM
    cleaned = text.replace("\ufeff", "")
    cleaned = cleaned.lstrip()
    
    # 尝试移除客套前缀
    cleaned = strip_preface_before_marker(cleaned)
    
    # 额外去除清洗后可能残留的开头分隔线（---）
    # 允许 BOM (\ufeff) 与 ZWSP (\u200b) 在分隔线两侧
    cleaned = re.sub(r'(?m)\A(?:[\s\ufeff\u200b]*-{3,}[\s\ufeff\u200b]*\r?\n)+', '', cleaned)
    
    return cleaned


def strip_preface_before_marker(text: str, max_preface_chars: int = 500, max_preface_lines: int = 10) -> str:
    """
    如果在开头检测到短小客套语且后面紧跟 Markdown 分隔线（---），
    仅在安全条件下移除前缀，避免误删正文。
    
    Args:
        text: 原始文本
        max_preface_chars: 最大前缀字符数（默认 500）
        max_preface_lines: 最大前缀行数（默认 10）
        
    Returns:
        处理后的文本
    """
    # 更健壮地匹配分隔线，允许 Unicode 隐藏空白（如 BOM/ZWSP）在两侧
    marker_match = re.search(r'(?m)^[\s\ufeff\u200b]*-{3,}[\s\ufeff\u200b]*$', text)
    if not marker_match:
        return text

    if marker_match.start() > max_preface_chars:
        return text

    preface = text[:marker_match.start()].strip()
    if not preface:
        # 如果没有前缀（直接以 --- 开头），去掉分隔线并返回后续内容
        return text[marker_match.end():].lstrip("\r\n")

    # 仅移除满足条件的客套前缀
    # 条件1：字符数限制
    if len(preface) > max_preface_chars:
        return text

    # 条件2：行数限制（放宽到 max_preface_lines 行）
    if preface.count("\n") > max_preface_lines:
        return text

    # 条件3：不包含结构性 Markdown（章节标题、代码块等）
    # 注意：这里的 --- 检测要排除单独成行的情况（那可能是分隔线本身）
    if re.search(r'#{1,6}\s.+|```', preface):
        return text

    return text[marker_match.end():].lstrip("\r\n")


# ================= 日志配置 =================
def setup_logging(
    level: int = logging.INFO,
    format_str: str = '%(asctime)s - %(levelname)s - %(message)s',
    encoding: str = 'utf-8'
) -> None:
    """
    配置全局日志
    
    Args:
        level: 日志级别
        format_str: 日志格式
        encoding: 输出编码
    """
    # 配置标准输出编码
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding=encoding)
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding=encoding)
    
    logging.basicConfig(level=level, format=format_str)


# ================= HTTP Headers =================
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://courses.sjtu.edu.cn/",
    "Origin": "https://courses.sjtu.edu.cn"
}


def get_ffmpeg_headers(headers: Optional[Dict[str, str]] = None) -> str:
    """
    生成 ffmpeg 所需的 headers 字符串
    
    Args:
        headers: HTTP 头字典，默认使用 DEFAULT_HEADERS
        
    Returns:
        ffmpeg headers 格式字符串
    """
    if headers is None:
        headers = DEFAULT_HEADERS
    return "".join([f"{k}: {v}\r\n" for k, v in headers.items()])


# ================= 路径工具 =================
def ensure_dir(path: Path) -> Path:
    """
    确保目录存在，不存在则创建
    
    Args:
        path: 目录路径
        
    Returns:
        目录路径
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_module_dir() -> Path:
    """获取模块所在目录"""
    return MODULE_DIR


# ================= 初始化 =================
# 模块加载时自动加载 .env
load_dotenv()
