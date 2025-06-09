from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from tiktok_uploader import config
from tiktok_uploader.proxy_auth_extension.proxy_auth_extension import (
    generate_proxy_auth_extension,
)
import os
import logging
from tiktok_uploader.utils import green
import random
import time

logger = logging.getLogger(__name__)


def get_browser(
    name: str = "chrome",
    options: ChromeOptions = None,
    browser_data_dir: str = None,
    **kwargs,
) -> webdriver.Chrome:
    if _clean_name(name) != "chrome":
        raise UnsupportedBrowserException(
            f"Unsupported browser: {name}. Only Chrome is supported."
        )

    browser_options = options or get_default_options(name=name, **kwargs)

    if browser_data_dir:
        if os.path.exists(browser_data_dir):
            try:
                import shutil

                shutil.rmtree(browser_data_dir)
                logger.debug(
                    green(
                        f"Cleared existing browser data directory: {browser_data_dir}"
                    )
                )
            except Exception as e:
                logger.error(f"Failed to clear browser data directory: {e}")

        os.makedirs(browser_data_dir, exist_ok=True)
        browser_options.add_argument(f"--user-data-dir={browser_data_dir}")
        logger.debug(green(f"Created fresh browser data directory: {browser_data_dir}"))

    service = Service()
    driver = webdriver.Chrome(service=service, options=browser_options)

    try:
        driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
        driver.execute_cdp_cmd("Network.clearBrowserCache", {})
        driver.execute_cdp_cmd(
            "Storage.clearDataForOrigin",
            {
                "origin": "*",
                "storageTypes": "all",
            },
        )

        script = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument", {"source": script}
        )
    except Exception as e:
        logger.error(f"Could not execute CDP commands, browser might have crashed: {e}")

    driver.set_page_load_timeout(20)
    driver.implicitly_wait(config["implicit_wait"])

    return driver


def get_default_options(name: str, **kwargs) -> ChromeOptions:
    name = _clean_name(name)

    if name == "chrome":
        return chrome_defaults(**kwargs)

    raise UnsupportedBrowserException()


def chrome_defaults(
    headless: bool = True, proxy: dict = None, **kwargs
) -> ChromeOptions:
    options = ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-notifications")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--disable-infobars")
    options.add_argument("--ignore-gpu-blocklist")

    random_port = random.randint(30000, 40000)
    options.add_argument(f"--remote-debugging-port={random_port}")
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
    options.add_argument(f"user-agent={user_agent}")

    options.add_experimental_option(
        "excludeSwitches", ["enable-automation", "enable-logging"]
    )
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option(
        "prefs",
        {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.images": 1,
            "profile.default_content_setting_values.cookies": 1,
            "profile.managed_default_content_settings.javascript": 1,
        },
    )

    options.add_argument("--lang=en")
    options.add_argument("--disable-blink-features")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    options.add_argument("--disable-site-isolation-trials")
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-features=UserAgentClientHint")

    if proxy:
        if "user" in proxy.keys() and "pass" in proxy.keys():
            extension_file = "temp_proxy_auth_extension.zip"
            generate_proxy_auth_extension(
                proxy["host"],
                proxy["port"],
                proxy["user"],
                proxy["pass"],
                extension_file,
            )
            options.add_extension(extension_file)
        else:
            options.add_argument(f"--proxy-server={proxy['host']}:{proxy['port']}")

    return options


class UnsupportedBrowserException(Exception):
    def __init__(self, message=None):
        super().__init__(message or self.__doc__)


def _clean_name(name: str) -> str:
    return name.strip().lower()
