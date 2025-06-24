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
    # Enhanced anti-detection measures
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option(
        "excludeSwitches", ["enable-automation", "enable-logging"]
    )
    options.add_experimental_option("useAutomationExtension", False)
    
    # Stealth mode optimizations
    options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "webrtc.ip_handling_policy": "disable_non_proxied_udp",
        "webrtc.multiple_routes_enabled": False,
        "webrtc.nonproxied_udp_enabled": False,
    })

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
    
    # Additional stability options
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-features=TranslateUI")
    options.add_argument("--disable-ipc-flooding-protection")
    options.add_argument("--disable-client-side-phishing-detection")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-hang-monitor")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-prompt-on-repost")
    options.add_argument("--disable-sync")
    options.add_argument("--log-level=3")  # Reduce Chrome logging
    options.add_argument("--silent")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-background-mode")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-java")
    options.add_argument("--aggressive-cache-discard")
    options.add_argument("--disable-plugins-discovery")
    options.add_argument("--disable-prerender-local-predictor")
    options.add_argument("--disable-threaded-animation")
    options.add_argument("--disable-threaded-scrolling")
    options.add_argument("--disable-in-process-stack-traces")
    options.add_argument("--disable-histogram-customizer")
    options.add_argument("--disable-gl-extensions")
    options.add_argument("--disable-composited-antialiasing")
    options.add_argument("--disable-canvas-aa")
    options.add_argument("--disable-3d-apis")
    options.add_argument("--disable-accelerated-2d-canvas")
    options.add_argument("--disable-accelerated-jpeg-decoding")
    options.add_argument("--disable-accelerated-mjpeg-decode")
    options.add_argument("--disable-app-list-dismiss-on-blur")
    options.add_argument("--disable-accelerated-video-decode")
    
    # Set page load strategy
    options.set_capability('pageLoadStrategy', 'eager')  # Don't wait for all resources
    
    # Randomize window size for fingerprinting
    if headless:
        options.add_argument("--headless")
        # Randomize viewport size slightly to avoid detection
        width = random.randint(1900, 1940)
        height = random.randint(1060, 1100)
        options.add_argument(f"--window-size={width},{height}")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-first-run")
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
