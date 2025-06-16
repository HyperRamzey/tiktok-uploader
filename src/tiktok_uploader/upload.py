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
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

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
    manage_screenshots,
)
from tiktok_uploader.proxy_auth_extension import proxy_is_working

logger = logging.getLogger(__name__)
POST_FINISH_TIMEOUT = 60


def upload_video(filename, description, cookies, browser_data_dir=None, headless=True):
    try:
        pbar = tqdm(total=100, desc="Uploading video", leave=False)
        pbar.update(10)
        driver = get_browser(headless=headless, user_data_dir=browser_data_dir)
        pbar.update(10)
        driver.get("https://www.tiktok.com")
        for cookie in get_cookies(cookies):
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                logger.error(f"Error adding cookie: {e}")
        pbar.update(10)
        driver.get(config["paths"]["upload"])
        pbar.update(10)
        try:
            file_input = _locate_file_input(driver, timeout=60)
            file_input.send_keys(os.path.abspath(filename))
            pbar.update(20)

            logger.info("Waiting for video upload and processing to complete...")
            try:
                processing_selectors = [
                    "//div[contains(text(), 'Uploading') or contains(text(), 'Processing') or contains(text(), 'upload in progress')]",
                    "//span[contains(text(), 'Uploading') or contains(text(), 'Processing')]",
                    "//div[contains(text(), 'processing')]",
                    "//div[contains(@class, 'progress')]", 
                    "//div[contains(@class, 'upload-progress')]",
                    "//div[contains(@role, 'progressbar')]",
                ]

                processing_found = False
                for selector in processing_selectors:
                    try:
                        processing_element = driver.find_element(By.XPATH, selector)
                        if processing_element.is_displayed():
                            processing_found = True
                            logger.info(
                                f"Processing indicator found with selector: {selector}"
                            )
                            try:
                                WebDriverWait(driver, 90).until(  # Increased timeout from 60 to 90 seconds
                                    EC.invisibility_of_element_located(
                                        (By.XPATH, selector)
                                    )
                                )
                                logger.info("Processing completed")
                            except TimeoutException:
                                logger.warning(
                                    "Processing indicator did not disappear within timeout"
                                )
                            break
                    except NoSuchElementException:
                        continue

                if not processing_found:
                    logger.info(
                        "No processing indicator found, waiting a bit anyway..."
                    )
                    time.sleep(30)  # Increased from 10 to 20 seconds

                form_selectors = [
                    "//div[contains(@class, 'form') or contains(@class, 'editor')]",
                    "//div[@role='form']",
                    "//div[.//div[@aria-label='Caption' or @aria-label='Description']]",
                    "//textarea",
                ]

                for selector in form_selectors:
                    try:
                        WebDriverWait(driver, 30).until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                        logger.info(f"Form area detected with selector: {selector}")
                        break
                    except TimeoutException:
                        continue

                time.sleep(5)

            except Exception as e:
                logger.warning(f"Error while waiting for upload completion: {e}")
                time.sleep(10)
        except TimeoutException:
            logger.error("Timeout waiting for file input")
            pbar.close()
            return "Timeout waiting for file input"
        try:
            xpaths = [
                "//div[contains(@data-tux-text-input-wrapper,'true')]",
                "//div[data-tux-text-input-wrapper='true']",
                "//div[contains(@data-e2e,'caption')]//div[@contenteditable='true']",
                "//div[@contenteditable='true' and @aria-label='Caption']",
                "//div[@role='textbox' and @contenteditable='true']",
                "//div[contains(@class,'editor-container')]//div[@contenteditable='true']",
                "//div[@contenteditable='true']",
            ]

            description_input = None
            end_time = time.time() + 60
            while time.time() < end_time and description_input is None:
                try:
                    candidates = []
                    try:
                        desc_selector = config["selectors"]["upload"]["description"]
                        if desc_selector:
                            candidates = driver.find_elements(
                                By.CSS_SELECTOR, desc_selector
                            )
                            logger.info(
                                f"Found {len(candidates)} elements with config selector: {desc_selector}"
                            )
                    except Exception as e:
                        logger.warning(f"Error using config selector: {e}")

                    if not candidates:
                        candidates = driver.find_elements(
                            By.CSS_SELECTOR,
                            "div.public-DraftEditor-content[contenteditable='true']",
                        )

                    if not candidates:
                        for xpath in xpaths:
                            try:
                                xpath_candidates = driver.find_elements(By.XPATH, xpath)
                                if xpath_candidates:
                                    candidates.extend(xpath_candidates)
                            except Exception:
                                pass

                    if not candidates:
                        candidates += driver.find_elements(
                            By.CSS_SELECTOR,
                            "div[contenteditable='true'][role='combobox']",
                        )
                        candidates += driver.find_elements(
                            By.CSS_SELECTOR,
                            "div[contenteditable='true'][role='textbox']",
                        )
                        candidates += driver.find_elements(
                            By.CSS_SELECTOR, "div[contenteditable='true']"
                        )

                    for el in candidates:
                        try:
                            if el.is_displayed() and el.is_enabled():
                                description_input = el
                                logger.info(
                                    f"Found description input field: {el.get_attribute('outerHTML')[:100]}..."
                                )
                                break
                        except StaleElementReferenceException:
                            continue

                except StaleElementReferenceException:
                    description_input = None

                if description_input is None:
                    time.sleep(2)
                    try:
                        screenshot_path = (
                            f"description_field_search_{int(time.time())}.png"
                        )
                        driver.save_screenshot(manage_screenshots(screenshot_path))
                        logger.info(f"Debug screenshot saved to {screenshot_path}")
                    except Exception as ss_err:
                        logger.warning(f"Could not save debug screenshot: {ss_err}")

            if description_input is None:
                raise TimeoutException(
                    "Could not locate description textbox within 180 seconds"
                )

            for attempt in range(2):
                if attempt == 1 and (
                    description_input is None or not description_input.is_enabled()
                ):
                    try:
                        description_input = driver.find_element(
                            By.CSS_SELECTOR,
                            "div.public-DraftEditor-content[contenteditable='true']",
                        )
                    except Exception:
                        description_input = None
                try:
                    if description_input is None:
                        raise StaleElementReferenceException(
                            "Description input lost after re-render"
                        )

                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});",
                        description_input,
                    )
                    driver.execute_script("arguments[0].focus();", description_input)
                    time.sleep(0.3)
                    description_input.send_keys(Keys.CONTROL, "a")
                    time.sleep(0.2)
                    description_input.send_keys(Keys.DELETE)
                    time.sleep(0.3)
                    description_input.send_keys(description)
                    break
                except StaleElementReferenceException:
                    description_input = None
                    if attempt == 0:
                        continue
                    else:
                        raise
            pbar.update(10)

            logger.info(
                "Using preset TikTok settings - skipping all interactivity modifications"
            )

            for scroll_pos in [400, 600, 800]:
                driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                time.sleep(0.5)

            try:
                post_button_selectors = [
                    "button[data-e2e='post_video_button']",
                    "button[data-e2e='publish-button']",
                    "button[type='submit']",
                    "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'post')]",
                    "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'publish')]",
                ]

                scroll_found = False
                for scroll_pos in [600, 1000, 1500, 2000, 2500, 3000, 3500]:
                    driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                    time.sleep(0.7)

                    for selector in post_button_selectors:
                        try:
                            if selector.startswith("//"):
                                post_buttons = driver.find_elements(By.XPATH, selector)
                            else:
                                post_buttons = driver.find_elements(
                                    By.CSS_SELECTOR, selector
                                )

                            for btn in post_buttons:
                                if btn.is_displayed() and btn.is_enabled():
                                    logger.info(
                                        f"Post button found at scroll position {scroll_pos} with selector: {selector}"
                                    )
                                    post_button = btn
                                    scroll_found = True
                                    break

                            if scroll_found:
                                break
                        except Exception:
                            pass

                    if scroll_found:
                        break

                if not scroll_found:
                    logger.info("Trying bottom scroll to find post button...")
                    driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight);"
                    )
                    time.sleep(1.5)
                    for scroll_pos in [3000, 2500, 2000, 1500, 1000, 500]:
                        driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                        time.sleep(0.5)
                        for selector in post_button_selectors:
                            try:
                                if selector.startswith("//"):
                                    post_buttons = driver.find_elements(
                                        By.XPATH, selector
                                    )
                                else:
                                    post_buttons = driver.find_elements(
                                        By.CSS_SELECTOR, selector
                                    )

                                for btn in post_buttons:
                                    if btn.is_displayed() and btn.is_enabled():
                                        logger.info(
                                            f"Post button found during reverse scroll at {scroll_pos}px with selector: {selector}"
                                        )
                                        post_button = btn
                                        scroll_found = True
                                        break

                                if scroll_found:
                                    break
                            except Exception:
                                pass

                        if scroll_found:
                            break

                if scroll_found and "post_button" in locals():
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", post_button
                    )
                    time.sleep(1)
                else:
                    for selector in post_button_selectors:
                        try:
                            if selector.startswith("//"):
                                post_button = WebDriverWait(driver, 10).until(
                                    EC.element_to_be_clickable((By.XPATH, selector))
                                )
                            else:
                                post_button = WebDriverWait(driver, 10).until(
                                    EC.element_to_be_clickable(
                                        (By.CSS_SELECTOR, selector)
                                    )
                                )
                            logger.info(
                                f"Post button found with WebDriverWait using selector: {selector}"
                            )
                            break
                        except Exception:
                            continue

                try:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", post_button
                    )
                    time.sleep(1.5)

                    # Check if post button is actually enabled (not grayed out)
                    is_enabled = driver.execute_script(
                        "return !arguments[0].disabled && !arguments[0].classList.contains('disabled') && window.getComputedStyle(arguments[0]).opacity > 0.5", 
                        post_button
                    )
                    
                    if not is_enabled:
                        logger.info("Post button appears disabled. Waiting additional time...")
                        time.sleep(15)  # Wait additional time for processing to complete
                        
                    # Check again if post button is enabled
                    is_enabled = driver.execute_script(
                        "return !arguments[0].disabled && !arguments[0].classList.contains('disabled') && window.getComputedStyle(arguments[0]).opacity > 0.5", 
                        post_button
                    )
                    
                    if not is_enabled:
                        logger.info("Post button still appears disabled. Waiting longer...")
                        time.sleep(15)  # Wait more time
                    
                    driver.execute_script("arguments[0].click();", post_button)
                    logger.info(
                        cyan(
                            f"Post button clicked – waiting up to {POST_FINISH_TIMEOUT}s for TikTok to finish processing …"
                        )
                    )
                    pbar.update(20)
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", post_button)
                        logger.info("Clicked post button with JavaScript click")
                    except Exception as e:
                        logger.error(f"Failed to click post button: {e}")
                        raise
            except TimeoutException:
                logger.error("Timeout waiting for post button")
                pbar.close()
                return "Timeout waiting for post button"
        except TimeoutException:
            logger.error("Timeout waiting for description input")
            pbar.close()
            return "Timeout waiting for description input"

        try:
            wait_start = time.time()
            success_detected = False

            try:
                success_selectors = [
                    "div[data-e2e='upload-success']",
                    "div[data-e2e='upload-complete']",
                    "div[data-e2e='upload-succeed']",
                    "div.success-container",
                    "div.upload-success",
                    "//div[contains(text(), 'upload') and (contains(text(), 'success') or contains(text(), 'complete'))]",
                    "//h2[contains(text(), 'upload') and (contains(text(), 'success') or contains(text(), 'complete'))]",
                    "//div[contains(text(), 'successfully')]",
                    "//div[contains(text(), 'Your video is being uploaded')]",
                ]

                for selector in success_selectors:
                    try:
                        if selector.startswith("//"):
                            WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.XPATH, selector))
                            )
                        else:
                            WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, selector)
                                )
                            )
                        logger.info(
                            green(
                                f"Upload success banner detected with selector: {selector}"
                            )
                        )
                        success_detected = True
                        break
                    except TimeoutException:
                        continue
            except TimeoutException:
                pass

            if not success_detected:
                current_url = driver.current_url
                if (
                    "/content" in current_url
                    or "/creator-center" in current_url
                    or "/tiktok-studio" in current_url
                ):
                    logger.info(green("Upload likely successful based on URL redirect"))
                    success_detected = True
                elif "tiktokstudio" not in current_url and "upload" not in current_url:
                    logger.info(
                        green(
                            "Upload likely successful based on navigation away from upload page"
                        )
                    )
                    success_detected = True
                else:
                    try:
                        profile_links = driver.find_elements(
                            By.XPATH,
                            "//a[contains(@href, '/profile/') or contains(@href, '/user/')]",
                        )
                        if profile_links:
                            logger.info(
                                green(
                                    "Upload likely successful - profile links detected"
                                )
                            )
                            success_detected = True
                    except Exception:
                        pass

                    try:
                        buttons = driver.find_elements(By.TAG_NAME, "button")
                        for button in buttons:
                            button_text = button.text.lower()
                            if (
                                "continue" in button_text
                                or "new" in button_text
                                or "done" in button_text
                                or "view" in button_text
                                or "close" in button_text
                            ) and button.is_displayed():
                                logger.info(
                                    green(
                                        f"Upload likely successful - found button with text: {button_text}"
                                    )
                                )
                                success_detected = True
                                break
                    except Exception:
                        pass

            if success_detected:
                logger.info(green("Upload confirmed successful!"))
                try:
                    screenshot_path = f"upload_success_{int(time.time())}.png"
                    driver.save_screenshot(manage_screenshots(screenshot_path))
                    logger.info(f"Success screenshot saved to {screenshot_path}")
                except Exception:
                    pass
            else:
                elapsed = time.time() - wait_start
                remaining_wait = max(1, POST_FINISH_TIMEOUT - elapsed)
                logger.info(
                    yellow(
                        f"No explicit success indicator found - waiting {int(remaining_wait)} more seconds to ensure upload completes"
                    )
                )
                time.sleep(remaining_wait)
                logger.info(yellow("Wait completed, upload assumed successful"))

            pbar.update(10)

        except TimeoutException:
            elapsed = int(time.time() - wait_start)
            logger.warning(
                yellow(
                    f"No explicit success banner after {elapsed}s – proceeding to next account."
                )
            )

        time.sleep(3)

        pbar.close()
        return None

    except Exception as e:
        logger.error(f"Error during upload: {e}")
        if "pbar" in locals():
            pbar.close()
        return str(e)
    finally:
        if "driver" in locals():
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
                if headless and driver:
                    try:
                        screenshot_path = f"error_screenshot_{int(time.time())}.png"
                        driver.save_screenshot(manage_screenshots(screenshot_path))
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
        logger.info(
            "Using preset TikTok settings - skipping all interactivity modifications"
        )

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
        upload_input = _locate_file_input(driver, timeout=60)
        upload_input.send_keys(path)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.XPATH, config["selectors"]["upload"]["processing"])
            )
        )
        WebDriverWait(driver, 120).until(
            EC.presence_of_element_located(
                (By.XPATH, config["selectors"]["upload"]["post"])
            )
        )
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
    description = truncate_string(
        description, config.get("max_description_length", 150)
    )

    try:
        desc_field = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.XPATH, config["selectors"]["upload"]["description"])
            )
        )
        WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, config["selectors"]["upload"]["description"])
            )
        )
        desc_field.click()
        time.sleep(2)
        desc_field.send_keys(Keys.CONTROL, "a")
        time.sleep(0.2)
        desc_field.send_keys(Keys.DELETE)
        time.sleep(0.5)
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


def _post_video(driver):
    try:
        post_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, config["selectors"]["upload"]["post"])
            )
        )
        post_button.click()
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.XPATH, config["selectors"]["upload"]["processing"])
            )
        )
        WebDriverWait(driver, 180).until(
            EC.presence_of_element_located(
                (By.XPATH, config["selectors"]["upload"]["post_confirmation"])
            )
        )
        time.sleep(15)
        success = False
        try:
            success_element = driver.find_element(
                By.XPATH, config["selectors"]["upload"]["complete"]
            )
            if success_element.is_displayed():
                success = True
        except NoSuchElementException:
            pass
        if not success:
            try:
                profile_element = driver.find_element(
                    By.XPATH, "//div[contains(@class, 'profile')]"
                )
                if profile_element.is_displayed():
                    success = True
            except NoSuchElementException:
                pass
        if not success:
            current_url = driver.current_url
            if "/content" in current_url:
                success = True

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
            EC.element_to_be_clickable(
                (By.XPATH, config["selectors"]["upload"]["cookies_banner"]["button"])
            )
        )
        button.click()
    except TimeoutException:
        pass


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


def _locate_file_input(driver, timeout: int = 30):
    """Return a visible <input type='file'> element."""
    try:
        file_input = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
        )
        driver.execute_script("arguments[0].style.display = 'block';", file_input)
        driver.execute_script("arguments[0].style.visibility = 'visible';", file_input)
        driver.execute_script("arguments[0].style.height = '1px';", file_input)
        driver.execute_script("arguments[0].style.width = '1px';", file_input)
        driver.execute_script("arguments[0].style.opacity = 1;", file_input)
        return file_input
    except TimeoutException:
        raise TimeoutException(
            "Could not locate <input type='file'> within given timeout"
        )
