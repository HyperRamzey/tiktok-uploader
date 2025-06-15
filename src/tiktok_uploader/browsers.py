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
import platform
import random

logger = logging.getLogger(__name__)

CHROME_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
]


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
        driver = webdriver.Chrome(service=service, options=options)
        
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {
            "userAgent": get_user_agent_for_platform(),
            "platform": get_platform_name()
        })
        })
        
    except Exception as e:
        logger.error("Failed to initialize Chrome browser: %s", e)
        raise

    atexit.register(driver.quit)
    return driver


def get_user_agent_for_platform():
    custom_ua = config.get('disguising', {}).get('user-agent')
    if custom_ua:
        return custom_ua
        
    platform_name = get_platform_name().lower()
    matching_agents = [ua for ua in CHROME_USER_AGENTS if 
                      (platform_name == 'win' and 'Windows' in ua) or
                      (platform_name == 'mac' and 'Mac' in ua) or
                      (platform_name == 'linux' and 'Linux' in ua)]
    
    if matching_agents:
        return random.choice(matching_agents)
    else:
        return random.choice(CHROME_USER_AGENTS)


def get_platform_name():
    system = platform.system().lower()
    if system == 'darwin':
        return 'Mac'
    elif system == 'windows':
        return 'Win'
    else:
        return 'Linux'


def chrome_defaults(
    options: ChromeOptions,
    headless: bool = False,
    browser_data_dir: Optional[str] = None,
) -> None:
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option(
        "excludeSwitches", ["enable-automation", "enable-logging"]
    )
    options.add_experimental_option("useAutomationExtension", False)

    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-translate")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-web-security")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    options.add_argument("--use-fake-ui-for-media-stream")
    
    if headless:
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")

    if browser_data_dir:
        options.add_argument(f"--user-data-dir={browser_data_dir}")

    options.add_argument(f"--lang={config.get('lang', 'en-US')}")

    ua = get_user_agent_for_platform()
    options.add_argument(f"--user-agent={ua}")


def get_driver_path(name: str) -> str:
    if name.lower() == "chrome":
        path = ChromeDriverManager().install()
    else:
        raise NotImplementedError(f"Driver for {name} is not supported")

    return path
