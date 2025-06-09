"""Handles authentication for TikTokUploader"""

from http import cookiejar
from time import time, sleep

from selenium.webdriver.common.by import By

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from tiktok_uploader import config, logger
from tiktok_uploader.browsers import get_browser
from tiktok_uploader.utils import green


class AuthBackend:
    username: str
    password: str
    cookies: list

    def __init__(
        self,
        username: str = "",
        password: str = "",
        cookies_list: list = None,
        cookies=None,
        cookies_str=None,
        sessionid: str = None,
    ):
        if (username and not password) or (password and not username):
            logger.error("Both username and password must be provided for login.")
            raise InsufficientAuth("Both username and password must be provided.")

        self.cookies = []
        if cookies:
            self.cookies += self.get_cookies(path=cookies)
        if cookies_str:
            self.cookies += self.get_cookies(cookies_str=cookies_str)
        if cookies_list:
            self.cookies += cookies_list
        if sessionid:
            self.cookies += [{"name": "sessionid", "value": sessionid}]

        if not (self.cookies or (username and password)):
            logger.error("No valid authentication method provided.")
            raise InsufficientAuth("No valid authentication method provided.")

        self.username = username
        self.password = password

        if self.cookies:
            logger.debug(green("Authenticating browser with cookies"))
        elif username and password:
            logger.debug(green("Authenticating browser with username and password"))
        elif sessionid:
            logger.debug(green("Authenticating browser with sessionid"))
        elif cookies_list:
            logger.debug(green("Authenticating browser with cookies_list"))

    def authenticate_agent(self, driver):
        if not self.cookies and self.username and self.password:
            self.cookies = login(driver, username=self.username, password=self.password)

        logger.debug(green("Authenticating browser with cookies"))

        driver.get(config["paths"]["main"])

        WebDriverWait(driver, config["explicit_wait"]).until(
            EC.title_contains("TikTok")
        )

        for cookie in self.cookies:
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                logger.error(f"Failed to add cookie {cookie}: {e}")

        return driver

    def get_cookies(self, path: str = None, cookies_str: str = None) -> list:
        cookies = []
        try:
            if path:
                with open(path, "r", encoding="utf-8") as file:
                    lines = file.read().splitlines()
            elif cookies_str:
                lines = cookies_str.splitlines()
            else:
                return cookies
            for line in lines:
                if not line or line.startswith("#"):
                    continue
                split = line.split("\t")
                if len(split) < 7:
                    continue
                try:
                    expiry = int(split[4])
                except ValueError:
                    expiry = None
                cookie = {
                    "name": split[5],
                    "value": split[6],
                    "domain": split[0],
                    "path": split[2],
                }
                if expiry:
                    cookie["expiry"] = expiry
                cookies.append(cookie)
        except Exception as e:
            logger.error(f"Failed to parse cookies: {e}")
        return cookies


def login_accounts(driver=None, accounts=[(None, None)], *args, **kwargs) -> list:
    driver = driver or get_browser(headless=False, *args, **kwargs)

    cookies = {}
    for account in accounts:
        username, password = get_username_and_password(account)

        cookies[username] = login(driver, username, password)

    return cookies


def login(driver, username: str, password: str):
    assert username and password, "Username and password are required"
    if not config["paths"]["main"] in driver.current_url:
        driver.get(config["paths"]["main"])
    if driver.get_cookie(config["selectors"]["login"]["cookie_of_interest"]):
        driver.delete_all_cookies()
    driver.get(config["paths"]["login"])
    username_field = WebDriverWait(driver, config["explicit_wait"]).until(
        EC.presence_of_element_located(
            (By.XPATH, config["selectors"]["login"]["username_field"])
        )
    )
    username_field.clear()
    username_field.send_keys(username)

    password_field = driver.find_element(
        By.XPATH, config["selectors"]["login"]["password_field"]
    )
    password_field.clear()
    password_field.send_keys(password)

    submit = driver.find_element(By.XPATH, config["selectors"]["login"]["login_button"])
    submit.click()

    print(f"Complete the captcha for {username}")

    start_time = time()
    while not driver.get_cookie(config["selectors"]["login"]["cookie_of_interest"]):
        sleep(0.5)
        if time() - start_time > config["explicit_wait"]:
            raise InsufficientAuth()

    WebDriverWait(driver, config["explicit_wait"]).until(
        EC.url_changes(config["paths"]["login"])
    )

    return driver.get_cookies()


def get_username_and_password(login_info: tuple or dict):
    if not isinstance(login_info, dict):
        return login_info[0], login_info[1]
    if "email" in login_info:
        return login_info["email"], login_info["password"]
    elif "username" in login_info:
        return login_info["username"], login_info["password"]

    raise InsufficientAuth()


def save_cookies(path, cookies: list):
    cookie_jar = cookiejar.MozillaCookieJar(path)
    cookie_jar.load()

    for cookie in cookies:
        cookie_jar.set_cookie(cookie)

    cookie_jar.save()


class InsufficientAuth(Exception):
    def __init__(self, message=None):
        super().__init__(message or self.__doc__)
