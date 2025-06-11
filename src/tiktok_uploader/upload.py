from os.path import abspath, exists
from typing import List, Optional, Dict, Any
import time
import threading
import os
import re
import logging

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
    yellow,
    clean_description,
    truncate_string,
    get_cookies,
)
from tiktok_uploader.proxy_auth_extension import proxy_is_working

logger = logging.getLogger(__name__)

def upload_video(filename, description, cookies, browser_data_dir=None, headless=True):
    """
    Upload a video to TikTok using Selenium
    """
    try:
        # Initialize progress bar
        pbar = tqdm(total=100, desc="Uploading video", leave=False)
        pbar.update(10)  # Initial progress

        # Setup browser
        driver = get_browser(headless=headless, user_data_dir=browser_data_dir)
        pbar.update(10)  # Browser setup complete

        # Load cookies
        driver.get("https://www.tiktok.com")
        for cookie in get_cookies(cookies):
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                logger.error(f"Error adding cookie: {e}")
        pbar.update(10)  # Cookies loaded

        # Navigate to upload page
        driver.get("https://www.tiktok.com/upload")
        pbar.update(10)  # Reached upload page

        # Wait for file input and upload video
        try:
            file_input = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
            )
            file_input.send_keys(os.path.abspath(filename))
            pbar.update(20)  # File selected
        except TimeoutException:
            logger.error("Timeout waiting for file input")
            pbar.close()
            return False

        # Wait for description input and enter description
        try:
            description_input = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[contenteditable='true']"))
            )
            description_input.send_keys(description)
            pbar.update(10)  # Description entered
        except TimeoutException:
            logger.error("Timeout waiting for description input")
            pbar.close()
            return False

        # Click post button
        try:
            post_button = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
            )
            post_button.click()
            pbar.update(20)  # Post button clicked
        except TimeoutException:
            logger.error("Timeout waiting for post button")
            pbar.close()
            return False

        # Wait for upload to complete
        try:
            WebDriverWait(driver, 300).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-e2e='upload-success']"))
            )
            pbar.update(10)  # Upload complete
        except TimeoutException:
            logger.error("Timeout waiting for upload completion")
            pbar.close()
            return False

        pbar.close()
        return True

    except Exception as e:
        logger.error(f"Error during upload: {e}")
        if 'pbar' in locals():
            pbar.close()
        return False
    finally:
        if 'driver' in locals():
            driver.quit()


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
    
    driver = None
    try:
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
                # If we're in headless mode and encounter an error, try to take a screenshot
                if headless and driver:
                    try:
                        screenshot_path = f"error_screenshot_{int(time.time())}.png"
                        driver.save_screenshot(screenshot_path)
                        logger.info(f"Error screenshot saved to {screenshot_path}")
                    except:
                        pass

        return failed_videos

    except Exception as e:
        logger.error(red(f"Critical error during upload process: {e}"))
        raise
    finally:
        if driver and config.get("quit_on_end", True):
            try:
                driver.quit()
            except:
                pass


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
    try:
        # Wait for upload input to be present
        upload_input = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
        )
        
        # Send file path
        upload_input.send_keys(path)
        
        # Wait for processing to start
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, config["selectors"]["upload"]["processing"]))
        )
        
        # Wait for processing to complete and post button to appear
        WebDriverWait(driver, 120).until(
            EC.presence_of_element_located((By.XPATH, config["selectors"]["upload"]["post"]))
        )
        
        # Additional wait to ensure video is fully processed
        time.sleep(5)
        
    except TimeoutException as e:
        logger.error(f"Timeout while uploading video: {e}")
        raise
    except Exception as e:
        logger.error(f"Error during video upload: {e}")
        raise

def _set_description(driver, description: str):
    if not description:
        return
    
    description = clean_description(description)
    description = truncate_string(description, config.get("max_description_length", 150))
    
    try:
        # Wait for description field to be present and clickable
        desc_field = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, config["selectors"]["upload"]["description"]))
        )
        WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, config["selectors"]["upload"]["description"]))
        )
        
        # Click and wait for field to be ready
        desc_field.click()
        time.sleep(2)
        
        # Select all and delete any pre-filled text
        desc_field.send_keys(Keys.CONTROL, 'a')
        time.sleep(0.2)
        desc_field.send_keys(Keys.DELETE)
        time.sleep(0.5)
        
        # Send description text character by character
        for char in description:
            desc_field.send_keys(char)
            time.sleep(0.05)
        time.sleep(2)
        
    except TimeoutException:
        logger.error("Timeout waiting for description field to be ready")
        raise
    except Exception as e:
        logger.error(f"Error setting description: {e}")
        raise

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
    try:
        # Wait for post button to be present and clickable
        post_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, config["selectors"]["upload"]["post"]))
        )
        
        # Click post button
        post_button.click()
        
        # Wait for processing to start
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, config["selectors"]["upload"]["processing"]))
        )
        
        # Wait for upload confirmation
        WebDriverWait(driver, 180).until(
            EC.presence_of_element_located((By.XPATH, config["selectors"]["upload"]["post_confirmation"]))
        )
        
        # Additional wait to ensure upload is complete
        time.sleep(15)  # Increased wait time
        
        # Verify upload was successful by checking multiple indicators
        success = False
        
        # Check for completion element
        try:
            success_element = driver.find_element(By.XPATH, config["selectors"]["upload"]["complete"])
            if success_element.is_displayed():
                success = True
        except NoSuchElementException:
            pass
            
        # Check if we're redirected to the profile page
        if not success:
            try:
                profile_element = driver.find_element(By.XPATH, "//div[contains(@class, 'profile')]")
                if profile_element.is_displayed():
                    success = True
            except NoSuchElementException:
                pass
                
        # Check for success message
        if not success:
            try:
                success_message = driver.find_element(By.XPATH, "//div[contains(text(), 'successfully') or contains(text(), 'posted')]")
                if success_message.is_displayed():
                    success = True
            except NoSuchElementException:
                pass
                
        if not success:
            raise Exception("Could not verify upload completion")
            
    except TimeoutException as e:
        logger.error(f"Timeout while posting video: {e}")
        raise
    except Exception as e:
        logger.error(f"Error during video posting: {e}")
        raise

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
