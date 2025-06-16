import os
import time
import random
import json
import logging
import glob
import os.path
from typing import List, Optional, Callable, Any, Dict
from functools import lru_cache, wraps

logger = logging.getLogger(__name__)


def bold(to_bold: str) -> str:
    return f"\033[1m{to_bold}\033[0m"


def green(to_green: str) -> str:
    return f"\033[32m{to_green}\033[0m"


def red(to_red: str) -> str:
    return f"\033[31m{to_red}\033[0m"


def cyan(to_cyan: str) -> str:
    return f"\033[36m{to_cyan}\033[0m"


def blue(to_blue: str) -> str:
    return to_blue


def yellow(to_yellow: str) -> str:
    return f"\033[33m{to_yellow}\033[0m"


def underline(to_underline: str) -> str:
    return to_underline


def manage_screenshots(new_screenshot_path: str, max_screenshots: int = 5) -> str:
    """
    Saves a new screenshot and maintains only the most recent screenshots up to max_screenshots.
    
    Args:
        new_screenshot_path: Path where the new screenshot should be saved
        max_screenshots: Maximum number of screenshots to keep
        
    Returns:
        The path of the saved screenshot
    """
    # Get all existing screenshot files
    screenshot_patterns = [
        "description_field_search_*.png", 
        "upload_success_*.png", 
        "error_screenshot_*.png"
    ]
    
    all_screenshots = []
    for pattern in screenshot_patterns:
        all_screenshots.extend(glob.glob(pattern))
    
    # Sort by modification time (most recent last)
    all_screenshots.sort(key=lambda f: os.path.getmtime(f))
    
    # If we have too many screenshots, remove the oldest ones
    if len(all_screenshots) >= max_screenshots:
        # Calculate how many to remove
        to_remove = len(all_screenshots) - max_screenshots + 1  # +1 for the new one
        
        # Remove oldest screenshots
        for i in range(to_remove):
            if i < len(all_screenshots):
                try:
                    os.remove(all_screenshots[i])
                    logger.debug(f"Removed old screenshot: {all_screenshots[i]}")
                except Exception as e:
                    logger.warning(f"Could not remove old screenshot {all_screenshots[i]}: {e}")
    
    return new_screenshot_path


def safe_filename(filename: str) -> str:
    return "".join(c for c in filename if c.isalnum() or c in "._- ")


def validate_video_file(filepath: str, supported_types: List[str]) -> bool:
    return any(filepath.lower().endswith(f".{ext}") for ext in supported_types)


def random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0) -> None:
    time.sleep(random.uniform(min_seconds, max_seconds))


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


def truncate_string(text: str, max_length: int = 100) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def clean_description(description: str) -> str:
    if not description:
        return ""
    cleaned = " ".join(description.split())
    return cleaned


def get_cookies(cookie_file: str) -> List[Dict]:
    cookies = []
    try:
        with open(cookie_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                fields = line.split("\t")
                if len(fields) >= 7:
                    cookie = {
                        "name": fields[5],
                        "value": fields[6],
                        "domain": fields[0],
                        "path": fields[2],
                        "secure": fields[3] == "TRUE",
                        "httpOnly": fields[4] == "TRUE",
                    }
                    cookies.append(cookie)
    except Exception as e:
        logger.error(f"Error reading cookie file: {e}")
    return cookies
