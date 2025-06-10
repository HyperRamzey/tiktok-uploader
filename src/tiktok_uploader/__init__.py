from os.path import abspath, join, dirname
import logging
import sys

import toml

__version__ = "1.0.0"
__author__ = "TikTok Uploader Contributors"
__description__ = "Automated video uploading to TikTok using Selenium"
try:
    src_dir = abspath(dirname(__file__))
    config_path = join(src_dir, "config.toml")
    config = toml.load(config_path)
except Exception as e:
    print(f"❌ Failed to load configuration: {e}")
    sys.exit(1)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    "%(asctime)s [%(levelname)8s] %(name)s: %(message)s", datefmt="[%H:%M:%S]"
)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(stream_handler)

logger.propagate = False
from tiktok_uploader.upload import upload_video, upload_videos
from tiktok_uploader.auth import AuthBackend


def set_log_level(level):
    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)


__all__ = [
    "upload_video",
    "upload_videos",
    "AuthBackend",
    "config",
    "logger",
    "__version__",
    "set_log_level",
]
