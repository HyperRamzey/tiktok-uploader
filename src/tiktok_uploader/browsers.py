from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from tiktok_uploader import config
import logging
import webbrowser
from typing import Optional
import atexit
from webdriver_manager.chrome import ChromeDriverManager
from tiktok_uploader.proxy_auth_extension import get_proxy_auth_extension
import shutil
import sys

logger = logging.getLogger(__name__)


def get_browser(
    name: str = "chrome",
    headless: bool = False,
    proxy: Optional[dict] = None,
    options: Optional[ChromeOptions] = None,
    browser_data_dir: Optional[str] = None,
    **kwargs,
) -> webdriver.Chrome:
    if name.lower() != "chrome":
        raise ValueError("Only Chrome is supported")

    options = options or ChromeOptions()
    chrome_defaults(options, headless=headless, browser_data_dir=browser_data_dir)

    if proxy:
        logger.debug("Using proxy: %s", proxy)
        proxy_extension = get_proxy_auth_extension(proxy)
        options.add_extension(proxy_extension)

    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(
            service=service,
            options=options
        )
    except Exception as e:
        logger.error("Failed to initialize Chrome browser: %s", e)
        raise

    atexit.register(driver.quit)
    return driver


def chrome_defaults(
    options: ChromeOptions,
    headless: bool = False,
    browser_data_dir: Optional[str] = None,
) -> None:
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-translate")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")

    if headless:
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")

    if browser_data_dir:
        options.add_argument(f"--user-data-dir={browser_data_dir}")

    options.add_argument(f"--lang={config.get('lang', 'en-US')}")
    options.add_argument(f"--user-agent={config['disguising']['user-agent']}")


def get_driver_path(name: str) -> str:
    """
    Downloads and returns the path to the specified web driver
    """
    if name.lower() == 'chrome':
        path = ChromeDriverManager().install()
    else:
        raise NotImplementedError(f"Driver for {name} is not supported")
    
    return path
