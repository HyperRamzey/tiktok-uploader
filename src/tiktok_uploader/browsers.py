"""Gets the browser's given the user's input"""
from selenium.webdriver.chrome.options import Options as ChromeOptions

import undetected_chromedriver as uc

from tiktok_uploader import config
from tiktok_uploader.proxy_auth_extension.proxy_auth_extension import (
    generate_proxy_auth_extension,
)


def get_browser(name: str = "chrome", options: ChromeOptions = None, **kwargs) -> uc.Chrome:
    """
    Gets a browser based on the name with the ability to pass in additional arguments
    """
    if _clean_name(name) != "chrome":
        raise UnsupportedBrowserException(
            f"Unsupported browser: {name}. Only Chrome is supported."
        )

    browser_options = options or get_default_options(name=name, **kwargs)

    driver = uc.Chrome(options=browser_options, use_subprocess=True, **kwargs)

    driver.implicitly_wait(config["implicit_wait"])

    return driver


def get_default_options(name: str, **kwargs) -> ChromeOptions:
    """
    Gets the default options for each browser to help remain undetected
    """
    name = _clean_name(name)

    if name == "chrome":
        return chrome_defaults(**kwargs)

    raise UnsupportedBrowserException()


def chrome_defaults(headless: bool = False, proxy: dict = None, **kwargs) -> ChromeOptions:
    """
    Creates Chrome with Options
    """

    options = ChromeOptions()

    ## regular
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--profile-directory=Default")

    ## experimental
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    ## add english language to avoid languages translation error
    options.add_argument("--lang=en")

    # headless
    if headless:
        options.add_argument("--headless=new")
    if proxy:
        if "user" in proxy.keys() and "pass" in proxy.keys():
            # This can fail if you are executing the function more than once in the same time
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
            options.add_argument(f'--proxy-server={proxy["host"]}:{proxy["port"]}')

    return options


# Misc
class UnsupportedBrowserException(Exception):
    """
    Browser is not supported by the library

    Supported browsers are:
        - Chrome
    """

    def __init__(self, message=None):
        super().__init__(message or self.__doc__)


def _clean_name(name: str) -> str:
    """
    Cleans the name of the browser to make it easier to use
    """
    return name.strip().lower()
