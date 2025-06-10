"""
Utilities for TikTok Uploader
"""

import os
import time
import random
from typing import List, Optional, Callable, Any
from functools import lru_cache, wraps


def bold(to_bold: str) -> str:
    return to_bold


def green(to_green: str) -> str:
    return to_green


def red(to_red: str) -> str:
    return to_red


def cyan(to_cyan: str) -> str:
    return to_cyan


def blue(to_blue: str) -> str:
    return to_blue


def yellow(to_yellow: str) -> str:
    return to_yellow


def underline(to_underline: str) -> str:
    return to_underline


@lru_cache(maxsize=1000)
def safe_filename(filename: str) -> str:
    return "".join(c for c in filename if c.isalnum() or c in "._- ")


@lru_cache(maxsize=1000)
def validate_video_file(filepath: str, supported_types: List[str]) -> bool:
    return any(filepath.lower().endswith(f".{ext}") for ext in supported_types)


def random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0) -> None:
    time.sleep(random.uniform(min_seconds, max_seconds))


@lru_cache(maxsize=100)
def format_duration(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
                    time.sleep(delay * (attempt + 1))
            return None
        return wrapper
    return decorator


@lru_cache(maxsize=1000)
def truncate_string(text: str, max_length: int = 100) -> str:
    return text[:max_length] + "..." if len(text) > max_length else text


@lru_cache(maxsize=1000)
def clean_description(description: str) -> str:
    return description.strip()
