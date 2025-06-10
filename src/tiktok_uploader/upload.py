from os.path import abspath, exists
from typing import List, Optional
import time
import threading
import os

from tqdm import tqdm

from selenium.webdriver.common.by import By

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
    NoSuchElementException,
)

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
from tiktok_uploader.proxy_auth_extension.proxy_auth_extension import proxy_is_working


def upload_video(
    filename=None,
    description="",
    cookies="",
    username="",
    password="",
    sessionid=None,
    cookies_list=None,
    cookies_str=None,
    proxy=None,
    browser_data_dir: str = None,
    **kwargs,
):
    auth = AuthBackend(
        username=username,
        password=password,
        cookies=cookies,
        cookies_list=cookies_list,
        cookies_str=cookies_str,
        sessionid=sessionid,
    )

    return upload_videos(
        videos=[
            {
                "path": filename,
                "description": description,
            }
        ],
        auth=auth,
        proxy=proxy,
        browser_data_dir=browser_data_dir,
        **kwargs,
    )


def upload_videos(
    videos: list = None,
    auth: AuthBackend = None,
    proxy: dict = None,
    browser="chrome",
    browser_agent=None,
    on_complete=None,
    headless=False,
    num_retries: int = 1,
    skip_split_window=False,
    browser_data_dir: str = None,
    **kwargs,
):
    videos = _convert_videos_dict(videos)

    if videos and len(videos) > 1:
        logger.debug("Uploading %d videos", len(videos))

    if not browser_agent:
        logger.debug(
            "Create a %s browser instance %s",
            browser,
            "in headless mode" if headless else "",
        )
        browser_options = kwargs.get("options", None)
        driver = get_browser(
            name=browser,
            headless=headless,
            proxy=proxy,
            options=browser_options,
            browser_data_dir=browser_data_dir,
            **kwargs,
        )
    else:
        logger.debug("Using user-defined browser agent")
        driver = browser_agent
    if proxy:
        if proxy_is_working(driver, proxy["host"]):
            logger.debug(green("Proxy is working"))
        else:
            logger.error("Proxy is not working")
            driver.quit()
            raise Exception("Proxy is not working")
    driver = auth.authenticate_agent(driver)

    failed = []
    for video in tqdm(videos, desc="Overall Upload Progress"):
        try:
            path = abspath(video.get("path"))
            description = video.get("description", "")

            logger.debug(
                "Posting %s%s",
                bold(video.get("path")),
                (
                    f"\n{' ' * 15}with description: {bold(description)}"
                    if description
                    else ""
                ),
            )

            if not _check_valid_path(path):
                logger.warning(f"{path} is invalid, skipping")
                failed.append(video)
                continue

            complete_upload_form(
                driver,
                path,
                description,
                skip_split_window,
                num_retries=num_retries,
                headless=headless,
                **kwargs,
            )
        except Exception as exception:
            logger.error("Failed to upload %s", path)
            logger.error(exception)
            failed.append(video)

        if on_complete is callable:
            on_complete(video)

    if config["quit_on_end"]:
        driver.quit()

    return failed


def complete_upload_form(
    driver,
    path: str,
    description: str,
    skip_split_window: bool,
    num_retries: int = 1,
    headless=False,
    **kwargs,
) -> None:
    try:
        total_steps = 6 if not skip_split_window else 5
        with tqdm(
            total=total_steps, desc=green(f"Uploading {os.path.basename(path)}")
        ) as pbar:
            pbar.set_description("Step 1: Navigating to upload page")
            _go_to_upload(driver)
            _remove_cookies_window(driver)
            pbar.update(1)

            pbar.set_description("Step 2: Starting video upload")
            upload_complete_event = threading.Event()
            upload_success = [False]
            upload_error = [None]

            def upload_video_thread():
                try:
                    logger.debug("Uploading video file...")
                    _set_video(driver, path, **kwargs)
                    upload_success[0] = True
                    logger.debug("Video upload completed successfully")
                except Exception as e:
                    upload_error[0] = e
                    logger.error(f"Video upload failed: {e}")
                finally:
                    upload_complete_event.set()

            upload_thread = threading.Thread(target=upload_video_thread)
            upload_thread.start()

            upload_timeout = config.get("uploading_wait", 90)
            logger.debug(
                f" Waiting for upload to complete (timeout: {upload_timeout}s)..."
            )
            if not upload_complete_event.wait(timeout=upload_timeout):
                logger.error("Upload timeout exceeded")
                raise Exception(
                    f"Video upload timed out after {upload_timeout} seconds"
                )

            if upload_error[0]:
                raise upload_error[0]

            if not upload_success[0]:
                logger.error("Upload failed for unknown reason")
                raise Exception("Video upload failed")

            pbar.update(1)

            pbar.set_description("Step 3: Setting video description")
            _set_description(driver, description)
            pbar.update(1)

            pbar.set_description("Step 4: Configuring video settings")
            _set_interactivity(driver, **kwargs)
            pbar.update(1)

            if not skip_split_window:
                pbar.set_description("Step 5: Handling split window")
                _remove_split_window(driver)
                pbar.update(1)

            pbar.set_description("Step 6: Publishing video")
            _post_video(driver)
            pbar.update(1)
            pbar.set_description(green("Video published successfully!"))

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        if num_retries > 0:
            logger.debug(f"Retrying upload ({num_retries} attempts remaining)...")
            complete_upload_form(
                driver,
                path,
                description,
                skip_split_window,
                num_retries=num_retries - 1,
                headless=headless,
                **kwargs,
            )
        else:
            raise FailedToUpload(f"Upload failed after all retries: {e}")


def _go_to_upload(driver) -> None:
    logger.debug(green("Navigating to upload page"))

    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            driver.get("https://www.tiktok.com/upload")
            time.sleep(2)
            return
        except Exception as e:
            retry_count += 1
            if retry_count == max_retries:
                raise e
            time.sleep(2)


def _change_to_upload_iframe(driver) -> None:
    iframe = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "iframe"))
    )
    driver.switch_to.frame(iframe)


def _set_description(driver, description: str) -> None:
    logger.debug(green("Setting video description"))

    try:
        description = clean_description(description)
        description_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='video-desc']"))
        )
        _clear(description_element)
        description_element.send_keys(description)
    except Exception as e:
        logger.error(f"Failed to set description: {e}")
        raise e


def _clear(element) -> None:
    element.send_keys(Keys.CONTROL + "a")
    element.send_keys(Keys.DELETE)


def _set_video(driver, video: str, **kwargs) -> None:
    logger.debug(green("Setting video file"))

    try:
        video_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-e2e='upload-video']")
            )
        )
        video_input.send_keys(video)
    except Exception as e:
        logger.error(f"Failed to set video: {e}")
        raise e


def _remove_cookies_window(driver) -> None:
    try:
        cookie_button = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-e2e='cookie-banner-accept']")
            )
        )
        cookie_button.click()
    except TimeoutException:
        pass


def _remove_split_window(driver) -> None:
    try:
        split_button = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-e2e='split-screen-button']")
            )
        )
        split_button.click()
    except TimeoutException:
        pass


def _set_interactivity(
    driver, comment=True, stitch=True, duet=True, *args, **kwargs
) -> None:
    logger.debug(green("Setting video interactivity options"))

    def find_and_click_element(selectors, setting_name):
        for selector in selectors:
            try:
                element = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                element.click()
                logger.debug(f"Successfully toggled {setting_name}")
                return True
            except (TimeoutException, ElementClickInterceptedException):
                continue
        return False

    settings = {
        "comments": (
            comment,
            ["[data-e2e='comment-switch']", "[data-e2e='comment-toggle']"],
        ),
        "stitch": (
            stitch,
            ["[data-e2e='stitch-switch']", "[data-e2e='stitch-toggle']"],
        ),
        "duet": (
            duet,
            ["[data-e2e='duet-switch']", "[data-e2e='duet-toggle']"],
        ),
    }

    for setting_name, (enabled, selectors) in settings.items():
        if not enabled:
            if not find_and_click_element(selectors, setting_name):
                logger.warning(f"Could not toggle {setting_name}")


def _post_video(driver) -> None:
    logger.debug(green("Publishing video"))

    try:
        post_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-e2e='post-button']")
            )
        )
        post_button.click()
    except Exception as e:
        logger.error(f"Failed to post video: {e}")
        raise e


def _check_valid_path(path: str) -> bool:
    return exists(path)


def _convert_videos_dict(videos_list_of_dictionaries) -> List:
    def intersection(lst1, lst2):
        return list(set(lst1) & set(lst2))

    required_keys = ["path", "description"]
    for video in videos_list_of_dictionaries:
        if not intersection(list(video.keys()), required_keys) == required_keys:
            raise ValueError(
                f"Video dictionary must contain {required_keys} keys, got {list(video.keys())}"
            )
    return videos_list_of_dictionaries


def __get_driver_timezone(driver):
    return driver.execute_script(
        "return Intl.DateTimeFormat().resolvedOptions().timeZone"
    )


def _refresh_with_alert(driver) -> None:
    driver.refresh()
    try:
        alert = driver.switch_to.alert
        alert.accept()
    except:
        pass


class FailedToUpload(Exception):
    def __init__(self, message=None):
        super().__init__(message)
