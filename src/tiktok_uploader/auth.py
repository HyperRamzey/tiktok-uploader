"""Handles authentication for TikTokUploader"""

from http import cookiejar
from time import time, sleep
from typing import List, Optional, Dict, Any
import json
import os
from functools import lru_cache

from selenium.webdriver.common.by import By

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from tiktok_uploader import config, logger
from tiktok_uploader.browsers import get_browser
from tiktok_uploader.utils import green, red


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
        self.username = username
        self.password = password
        self.cookies = []

        if cookies_list:
            self.cookies = cookies_list
        elif cookies:
            self.cookies = self.get_cookies(path=cookies)
        elif cookies_str:
            self.cookies = self.get_cookies(cookies_str=cookies_str)
        elif sessionid:
            self.cookies = [{"name": "sessionid", "value": sessionid}]

        if not self.cookies and not (username and password):
            raise InsufficientAuth(
                "No authentication method provided. Use cookies, sessionid, or username/password."
            )

    def authenticate_agent(self, driver):
        if self.cookies:
            logger.debug(green("Using cookies for authentication"))
            driver.get(config["paths"]["upload"])
            for cookie in self.cookies:
                try:
                    driver.add_cookie(cookie)
                except Exception as e:
                    logger.warning(f"Failed to add cookie: {e}")
            driver.refresh()
            return driver

        if self.username and self.password:
            logger.debug(green("Using username/password for authentication"))
            return login(driver, self.username, self.password)

        raise InsufficientAuth("No valid authentication method provided")

    @lru_cache(maxsize=100)
    def get_cookies(self, path: str = None, cookies_str: str = None) -> list:
        if path:
            try:
                cookies = []
                with open(path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            fields = line.split("\t")
                            if len(fields) >= 7:
                                cookie = {
                                    "domain": fields[0],
                                    "flag": fields[1] == "TRUE",
                                    "path": fields[2],
                                    "secure": fields[3] == "TRUE",
                                    "expiration": int(fields[4]),
                                    "name": fields[5],
                                    "value": fields[6],
                                }
                                cookies.append(cookie)
                if cookies:
                    return cookies
                with open(path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load cookies from {path}: {e}")
                return []
        elif cookies_str:
            try:
                return json.loads(cookies_str)
            except Exception as e:
                logger.error(f"Failed to parse cookies string: {e}")
                return []
        return []


def login(driver, username: str, password: str):
    logger.debug(green(f"Logging in as {username}"))
    driver.get(config["paths"]["login"])
    sleep(2)

    try:
        username_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, config["selectors"]["login"]["username_field"])
            )
        )
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, config["selectors"]["login"]["password_field"])
            )
        )

        username_field.send_keys(username)
        password_field.send_keys(password)

        login_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, config["selectors"]["login"]["login_button"])
            )
        )
        login_button.click()

        WebDriverWait(driver, 10).until(EC.url_changes(config["paths"]["login"]))

    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise e


def get_username_and_password(login_info: tuple or dict) -> tuple:
    if isinstance(login_info, tuple):
        return login_info
    elif isinstance(login_info, dict):
        return login_info.get("username"), login_info.get("password")
    return None, None


def save_cookies(path, cookies: list):
    try:
        with open(path, "w") as f:
            json.dump(cookies, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save cookies to {path}: {e}")


class InsufficientAuth(Exception):
    def __init__(self, message=None):
        super().__init__(message)
