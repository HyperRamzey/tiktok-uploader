"""
Utilities for TikTok Uploader
"""

import os
import time
import random
from typing import List, Optional
from colorama import Fore, Style, init

init(autoreset=True)


def bold(to_bold: str) -> str:
    return Style.BRIGHT + to_bold


def green(to_green: str) -> str:
    return Fore.GREEN + to_green


def red(to_red: str) -> str:
    return Fore.RED + to_red


def cyan(to_cyan: str) -> str:
    return Fore.CYAN + to_cyan


def blue(to_blue: str) -> str:
    return Fore.BLUE + to_blue


def yellow(to_yellow: str) -> str:
    return Fore.YELLOW + to_yellow


def underline(to_underline: str) -> str:
    # Underline is not a standard colorama style, so we'll use a bright effect instead
    # or just return the string as is if no visual distinction is needed.
    # For now, let's just make it bright as a substitute.
    return Style.BRIGHT + to_underline


def safe_filename(filename: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename[:255]


def validate_video_file(filepath: str, supported_types: List[str]) -> bool:
    if not os.path.exists(filepath):
        return False
    extension = filepath.split(".")[-1].lower()
    return extension in [ext.lower() for ext in supported_types]


def random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0) -> None:
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    def decorator(func):
        def wrapper(*args, **kwargs):
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


def truncate_string(text: str, max_length: int = 100) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def clean_description(description: str) -> str:
    if not description:
        return ""
    cleaned = "".join(
        char for char in description if ord(char) >= 32 or char in "\n\r\t"
    )
    return cleaned.strip()
