from os.path import abspath, exists
from typing import List, Optional, Dict, Any
import time
import threading
import os

from tqdm import tqdm

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from tiktok_uploader.browsers import get_browser
from tiktok_uploader.auth import AuthBackend
from tiktok_uploader import config, logger
from tiktok_uploader.utils import (
    bold,
    cyan,
    green,
    red,
    clean_description,
    truncate_string,
)
from tiktok_uploader.proxy_auth_extension import proxy_is_working


def upload_video(
    filename: str,
    description: str = "",
    cookies: str = "",
    sessionid: str = None,
    proxy: Optional[Dict] = None,
    **kwargs,
) -> bool:
    auth = AuthBackend(
        cookies=cookies,
        sessionid=sessionid,
    )

    return upload_videos(
        videos=[{"path": filename, "description": description}],
        auth=auth,
        proxy=proxy,
        **kwargs,
    )


def upload_videos(
    videos: List[Dict[str, Any]],
    auth: AuthBackend,
    proxy: Optional[Dict] = None,
    browser: str = "chrome",
    headless: bool = False,
    num_retries: int = 1,
    browser_data_dir: Optional[str] = None,
    **kwargs,
) -> List[Dict[str, Any]]:
    
    driver = get_browser(
        name=browser,
        headless=headless,
        proxy=proxy,
        browser_data_dir=browser_data_dir,
        **kwargs,
    )

    if proxy:
        if not proxy_is_working(driver, proxy.get("host")):
            logger.error(red("Proxy is not working. Exiting."))
            driver.quit()
            raise Exception("Proxy is not working")
        logger.debug(green("Proxy is working"))

    driver = auth.authenticate_agent(driver)

    failed_videos = []
    for video in tqdm(videos, desc="Uploading videos"):
        try:
            path = abspath(video.get("path"))
            description = video.get("description", "")

            if not exists(path):
                logger.warning(red(f"File not found: {path}"))
                failed_videos.append(video)
                continue

            complete_upload_form(
                driver,
                path,
                description,
                num_retries=num_retries,
                **kwargs,
            )

        except Exception as e:
            logger.error(red(f"Failed to upload {video.get('path')}: {e}"))
            failed_videos.append(video)
    
    if config.get("quit_on_end", True):
        driver.quit()

    return failed_videos


def complete_upload_form(
    driver,
    path: str,
    description: str,
    num_retries: int,
    **kwargs,
):
    try:
        _go_to_upload(driver)
        _set_video(driver, path, **kwargs)
        _set_description(driver, description)
        _set_interactivity(driver, **kwargs)
        _post_video(driver)
    except Exception as e:
        logger.error(red(f"Upload of {path} failed: {e}"))
        if num_retries > 0:
            logger.warning(yellow(f"Retrying... ({num_retries} attempts left)"))
            complete_upload_form(driver, path, description, num_retries - 1, **kwargs)
        else:
            raise FailedToUpload(f"Failed to upload {path} after multiple retries.")


def _go_to_upload(driver):
    driver.get(config["paths"]["upload"])
    time.sleep(1)
    _remove_cookies_window(driver)
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
    )

def _set_video(driver, path: str, **kwargs):
    upload_input = driver.find_element(By.XPATH, "//input[@type='file']")
    upload_input.send_keys(path)

    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located(
            (By.XPATH, config["selectors"]["upload"]["post"])
        )
    )

def _set_description(driver, description: str):
    if not description:
        return
    
    description = clean_description(description)
    description = truncate_string(description, config.get("max_description_length", 150))
    
    desc_field = driver.find_element(By.XPATH, config["selectors"]["upload"]["description"])
    desc_field.click()
    time.sleep(0.5)
    desc_field.clear()
    time.sleep(0.5)
    desc_field.send_keys(description)

def _set_interactivity(driver, **kwargs):
    comment = kwargs.get("comment", True)
    stitch = kwargs.get("stitch", True)
    duet = kwargs.get("duet", True)

    for setting, enabled in [("comment", comment), ("stitch", stitch), ("duet", duet)]:
        try:
            checkbox = driver.find_element(By.XPATH, config["selectors"]["upload"][setting])
            if checkbox.is_selected() != enabled:
                checkbox.click()
        except NoSuchElementException:
            logger.warning(yellow(f"Could not find checkbox for '{setting}'"))

def _post_video(driver):
    post_button = driver.find_element(By.XPATH, config["selectors"]["upload"]["post"])
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable(post_button))
    post_button.click()
    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located(
            (By.XPATH, config["selectors"]["upload"]["post_confirmation"])
        )
    )

def _remove_cookies_window(driver):
    try:
        button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, config["selectors"]["upload"]["cookies_banner"]["button"]))
        )
        button.click()
    except TimeoutException:
        pass # No cookie banner

def _convert_videos_dict(videos_list):
    if not videos_list:
        return []

    valid_path_keys = config.get("valid_path_names", ["path", "filename", "video"])
    valid_desc_keys = config.get("valid_descriptions", ["description", "desc"])
    
    processed_videos = []
    for video_data in videos_list:
        video_data = {k.lower(): v for k, v in video_data.items()}
        
        path, description = None, ""
        
        for key in valid_path_keys:
            if key in video_data:
                path = video_data[key]
                break
        
        for key in valid_desc_keys:
            if key in video_data:
                description = video_data[key]
                break
        
        if not path:
            raise ValueError(f"Video path not found in {video_data}")

        processed_videos.append({"path": path, "description": description})

    return processed_videos


class FailedToUpload(Exception):
    pass
