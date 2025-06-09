from os.path import abspath, exists
from typing import List, Optional
import time
import threading

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
    for video in videos:
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
                print(f"{path} is invalid, skipping")
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
    logger.info(green(f"🚀 Starting upload process for: {path}"))

    try:
        logger.info("Step 1: Navigating to upload page...")
        _go_to_upload(driver)
        _remove_cookies_window(driver)
        logger.info("Successfully navigated to upload page")

        logger.info("Step 2: Starting video upload...")
        upload_complete_event = threading.Event()
        upload_success = [False]
        upload_error = [None]

        def upload_video():
            try:
                logger.info("🔄 Uploading video file...")
                _set_video(driver, path, **kwargs)
                upload_success[0] = True
                logger.info("Video upload completed successfully")
            except Exception as e:
                upload_error[0] = e
                logger.error(f"❌ Video upload failed: {e}")
            finally:
                upload_complete_event.set()

        upload_thread = threading.Thread(target=upload_video)
        upload_thread.start()

        upload_timeout = config.get("uploading_wait", 90)
        logger.info(f" Waiting for upload to complete (timeout: {upload_timeout}s)...")
        if not upload_complete_event.wait(timeout=upload_timeout):
            logger.error("❌ Upload timeout exceeded")
            raise Exception(f"Video upload timed out after {upload_timeout} seconds")

        if upload_error[0]:
            raise upload_error[0]

        if not upload_success[0]:
            logger.error("❌ Upload failed for unknown reason")
            raise Exception("Video upload failed")

        logger.info("✅ Upload completed successfully")

        logger.info("Step 3: Setting video description...")
        _set_description(driver, description)
        logger.info("Description set successfully")

        logger.info("Step 4: Configuring video settings...")
        _set_interactivity(driver, **kwargs)
        logger.info("Interactivity settings configured")

        if not skip_split_window:
            logger.info("Step 5: Handling split window...")
            _remove_split_window(driver)
            logger.info("Split window handled")

        logger.info("Step 6: Publishing video...")
        _post_video(driver)
        logger.info("✅ Video published successfully!")

    except Exception as e:
        logger.error(f"❌ Upload failed: {e}")
        if num_retries > 0:
            logger.info(f"🔄 Retrying upload ({num_retries} attempts remaining)...")
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
    for attempt in range(max_retries):
        try:
            if driver.current_url != config["paths"]["upload"]:
                driver.get(config["paths"]["upload"])
            else:
                _refresh_with_alert(driver)

            # Wait for the most reliable indicator that the page is ready for upload.
            # The file input is the best candidate.
            upload_input_selector = (By.XPATH, "//input[@type='file']")
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located(upload_input_selector)
            )

            driver.switch_to.default_content()
            logger.debug(green("Successfully navigated to upload page and it is ready."))
            return

        except Exception as e:
            logger.warning(f"Upload navigation attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise Exception(
                    f"Failed to navigate to upload page after {max_retries} attempts"
                )
            time.sleep(1)


def _change_to_upload_iframe(driver) -> None:
    iframe_selector = EC.presence_of_element_located(
        (By.XPATH, config["selectors"]["upload"]["iframe"])
    )
    iframe = WebDriverWait(driver, config["explicit_wait"]).until(iframe_selector)
    driver.switch_to.frame(iframe)


def _set_description(driver, description: str) -> None:
    if description is None:
        return

    logger.debug(green("Setting description"))

    description = clean_description(description)
    description = truncate_string(description, config["max_description_length"])

    if not description:
        logger.debug("Empty description, skipping")
        return

    saved_description = description

    description_selectors = [
        "//div[@contenteditable='true']",
        "//textarea[contains(@placeholder, 'description')]",
        "//div[contains(@class, 'description')]//div[@contenteditable='true']",
        "//div[contains(@class, 'editor')]//div[@contenteditable='true']",
        "//div[@role='textbox']",
    ]

    desc_element = None
    for selector in description_selectors:
        try:
            desc_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, selector))
            )
            if desc_element.is_displayed():
                break
        except:
            continue

    if not desc_element:
        logger.error("Could not find description field")
        return

    try:
        desc_element.click()
        WebDriverWait(driver, 5).until(lambda d: desc_element.text != "" or True)

        desc_element.send_keys(Keys.CONTROL + "a")
        desc_element.send_keys(Keys.DELETE)
        time.sleep(0.1)

        words = description.split(" ")
        for word in words:
            if word.startswith("#"):
                desc_element.send_keys(word)
                desc_element.send_keys(" " + Keys.BACKSPACE)
                try:
                    WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located(
                            (By.XPATH, config["selectors"]["upload"]["mention_box"])
                        )
                    )
                    time.sleep(0.1)
                    desc_element.send_keys(Keys.ENTER)
                except:
                    desc_element.send_keys(" ")
            elif word.startswith("@"):
                logger.debug(green(f"Adding mention: {word}"))
                desc_element.send_keys(word)
                desc_element.send_keys(" ")
                time.sleep(0.1)
                desc_element.send_keys(Keys.BACKSPACE)

                try:
                    WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located(
                            (
                                By.XPATH,
                                config["selectors"]["upload"]["mention_box_user_id"],
                            )
                        )
                    )

                    user_elements = driver.find_elements(
                        By.XPATH, config["selectors"]["upload"]["mention_box_user_id"]
                    )
                    for i, user_element in enumerate(user_elements):
                        if user_element and user_element.is_enabled:
                            username = user_element.text.split(" ")[0]
                            if username.lower() == word[1:].lower():
                                for j in range(i):
                                    desc_element.send_keys(Keys.DOWN)
                                desc_element.send_keys(Keys.ENTER)
                                break
                    else:
                        desc_element.send_keys(" ")
                except:
                    desc_element.send_keys(" ")
            else:
                desc_element.send_keys(word + " ")

        logger.debug(green("Description set successfully"))

    except Exception as e:
        logger.error(f"Failed to set description: {e}")
        try:
            _clear(desc_element)
            desc_element.send_keys(saved_description)
        except:
            logger.error("Failed to set fallback description")


def _clear(element) -> None:
    element.send_keys(2 * len(element.text) * Keys.BACKSPACE)


def _set_video(driver, video: str, **kwargs) -> None:
    logger.debug(green("Setting video"))

    try:
        upload_selectors = [
            config["selectors"]["upload"]["upload"],
            "//input[@type='file']",
            "//input[contains(@accept, 'video')]",
            "//input[contains(@accept, 'video/mp4')]",
            "//input[contains(@accept, '.mp4')]",
            "//div[contains(@class, 'upload')]//input[@type='file']",
            "//div[contains(@class, 'file')]//input[@type='file']",
            "//div[contains(@class, 'uploader')]//input[@type='file']",
            "//div[contains(@class, 'upload-container')]//input[@type='file']",
            "//div[contains(@class, 'file-input')]//input[@type='file']",
            "//input[contains(@class, 'file-input')]",
            "//input[contains(@class, 'upload-input')]",
            "//input[contains(@name, 'file')]",
            "//input[contains(@id, 'file')]",
            "//input[contains(@id, 'upload')]",
            "//*[@type='file']",
        ]

        upload_input = None

        time.sleep(1)

        for i, selector in enumerate(upload_selectors):
            try:
                logger.debug(
                    f"Trying upload selector {i + 1}/{len(upload_selectors)}: {selector}"
                )
                elements = driver.find_elements(By.XPATH, selector)

                for element in elements:
                    try:
                        if element.get_attribute("type") == "file":
                            accept_attr = element.get_attribute("accept") or ""
                            if (
                                not accept_attr
                                or "video" in accept_attr
                                or "*" in accept_attr
                                or ".mp4" in accept_attr
                            ):
                                upload_input = element
                                logger.debug(
                                    f"Found upload input with selector: {selector}"
                                )
                                break
                    except Exception as e:
                        logger.debug(f"Error checking element: {e}")
                        continue

                if upload_input:
                    break

            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
                continue

        if not upload_input:
            try:
                logger.debug("Trying JavaScript approach to find file input")
                upload_input = driver.execute_script("""
                    var inputs = document.querySelectorAll('input[type="file"]');
                    for (var i = 0; i < inputs.length; i++) {
                        var input = inputs[i];
                        var accept = input.getAttribute('accept') || '';
                        if (!accept || accept.includes('video') || accept.includes('*') || accept.includes('.mp4')) {
                            return input;
                        }
                    }
                    return null;
                """)
                if upload_input:
                    logger.debug("Found upload input via JavaScript")
            except Exception as e:
                logger.debug(f"JavaScript approach failed: {e}")

        if not upload_input:
            try:
                logger.debug("Final attempt: looking for any file input")
                all_inputs = driver.find_elements(By.TAG_NAME, "input")
                for inp in all_inputs:
                    if inp.get_attribute("type") == "file":
                        upload_input = inp
                        logger.debug("Found fallback file input")
                        break
            except Exception as e:
                logger.debug(f"Final attempt failed: {e}")

        if not upload_input:
            raise Exception("Could not find upload input after trying all methods")

        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", upload_input
            )
            time.sleep(0.2)

            if not upload_input.is_displayed():
                driver.execute_script(
                    "arguments[0].style.display = 'block';", upload_input
                )
                driver.execute_script(
                    "arguments[0].style.visibility = 'visible';", upload_input
                )
                driver.execute_script("arguments[0].style.opacity = '1';", upload_input)

        except Exception as e:
            logger.warning(f"Could not make upload input visible: {e}")

        logger.debug(f"Sending file path to upload input: {video}")
        upload_input.send_keys(video)

        time.sleep(1)

        processing_selectors = [
            config["selectors"]["upload"]["processing"],
            "//div[contains(@class, 'processing')]",
            "//div[contains(@class, 'uploading')]",
            "//div[contains(text(), 'Processing')]",
            "//div[contains(text(), 'Uploading')]",
            "//div[contains(@class, 'progress')]",
            "//div[contains(@class, 'upload-progress')]",
            "//div[contains(@class, 'file-upload')]",
            "//div[contains(text(), 'Upload')]",
            "//*[contains(text(), 'Processing')]",
            "//*[contains(text(), 'Uploading')]",
        ]

        processing_found = False
        for selector in processing_selectors:
            try:
                logger.debug(f"Waiting for processing indicator: {selector}")
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )
                processing_found = True
                logger.debug(f"Found processing indicator: {selector}")
                break
            except:
                continue

        if not processing_found:
            logger.warning("No processing indicator found, but continuing...")

        complete_selectors = [
            config["selectors"]["upload"]["complete"],
            "//div[contains(@class, 'complete')]",
            "//div[contains(@class, 'success')]",
            "//div[contains(@class, 'uploaded')]",
            "//div[contains(@class, 'finished')]",
            "//div[contains(text(), 'Complete')]",
            "//div[contains(text(), 'Success')]",
            "//div[contains(text(), 'Uploaded')]",
            "//div[contains(text(), 'Finished')]",
            "//*[contains(text(), 'Complete')]",
            "//*[contains(text(), 'Success')]",
        ]

        complete_found = False
        for selector in complete_selectors:
            try:
                logger.debug(f"Waiting for completion indicator: {selector}")
                WebDriverWait(driver, 30).until(  # Increased timeout to 2 minutes
                    EC.presence_of_element_located((By.XPATH, selector))
                )
                complete_found = True
                logger.debug(f"Found completion indicator: {selector}")
                break
            except:
                continue

        if not complete_found:
            logger.warning("No completion indicator found, but video may have uploaded")

        logger.debug(green("Video upload process completed"))

    except Exception as e:
        logger.error(f"Failed to upload video: {str(e)}")
        try:
            logger.debug(f"Failed to upload video: {str(e)}")
        except:
            pass
        raise FailedToUpload(f"Failed to upload video: {str(e)}")


def _remove_cookies_window(driver) -> None:
    logger.debug(green(f"Removing cookies window"))
    try:
        time.sleep(0.5)

        cookie_handled = False

        try:
            cookies_banner = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located(
                    (
                        By.TAG_NAME,
                        config["selectors"]["upload"]["cookies_banner"]["banner"],
                    )
                )
            )

            shadow_root = cookies_banner.shadow_root
            if shadow_root:
                item = WebDriverWait(driver, 2).until(
                    EC.visibility_of(
                        shadow_root.find_element(
                            By.CSS_SELECTOR,
                            config["selectors"]["upload"]["cookies_banner"]["button"],
                        )
                    )
                )

                accept_button = WebDriverWait(driver, 2).until(
                    EC.element_to_be_clickable(
                        item.find_elements(By.TAG_NAME, "button")[0]
                    )
                )
                accept_button.click()
                logger.debug(green("Cookies accepted via shadow root"))
                cookie_handled = True
            else:
                logger.debug("Shadow root not found for cookies banner")
        except Exception as e:
            logger.debug(f"Shadow root approach failed: {e}")

        if not cookie_handled:
            cookie_button_selectors = [
                "//button[contains(text(), 'Accept')]",
                "//button[contains(text(), 'accept')]",
                "//button[contains(text(), 'ACCEPT')]",
                "//button[contains(text(), 'Allow')]",
                "//button[contains(text(), 'OK')]",
                "//button[contains(text(), 'Got it')]",
                "//button[contains(@class, 'accept')]",
                "//button[contains(@class, 'cookie')]",
                "//div[contains(@class, 'cookie')]//button",
                "//div[contains(@class, 'banner')]//button",
                "//div[contains(@class, 'consent')]//button",
                "//*[@role='button' and contains(text(), 'Accept')]",
                "//*[@role='button' and contains(text(), 'OK')]",
            ]

            for selector in cookie_button_selectors:
                try:
                    button = WebDriverWait(driver, 1).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    if button.is_displayed():
                        button.click()
                        logger.debug(
                            green(f"Cookies accepted via selector: {selector}")
                        )
                        cookie_handled = True
                        break
                except:
                    continue

        if not cookie_handled:
            try:
                driver.execute_script("""
                    var buttons = document.querySelectorAll('button, [role="button"]');
                    for (var i = 0; i < buttons.length; i++) {
                        var btn = buttons[i];
                        var text = btn.textContent.toLowerCase();
                        if (text.includes('accept') || text.includes('allow') || text.includes('ok') || text.includes('got it')) {
                            btn.click();
                            break;
                        }
                    }
                """)
                logger.debug(green("Cookies handled via JavaScript"))
                cookie_handled = True
            except Exception as e:
                logger.debug(f"JavaScript approach failed: {e}")

        if not cookie_handled:
            try:
                close_selectors = [
                    "//button[contains(@class, 'close')]",
                    "//button[contains(text(), 'Close')]",
                    "//button[contains(text(), '×')]",
                    "//div[contains(@class, 'close')]",
                    "//*[@role='button' and contains(@aria-label, 'close')]",
                ]

                for selector in close_selectors:
                    try:
                        close_btn = driver.find_element(By.XPATH, selector)
                        if close_btn.is_displayed():
                            close_btn.click()
                            logger.debug(green(f"Modal closed via: {selector}"))
                            cookie_handled = True
                            break
                    except:
                        continue
            except Exception as e:
                logger.debug(f"Close button approach failed: {e}")

        if not cookie_handled:
            logger.debug("No cookie banner found or already handled")

    except Exception as e:
        logger.debug(f"Error while handling cookies (non-critical): {e}")


def _remove_split_window(driver) -> None:
    logger.debug(green(f"Removing split window"))
    try:
        selectors = [
            config["selectors"]["upload"]["split_window"],
            "//div[contains(@class, 'split-screen')]",
            "//div[contains(@class, 'splitScreen')]",
            "//div[contains(@class, 'split-screen-container')]",
            "//div[contains(@class, 'splitScreenContainer')]",
            "//div[contains(@class, 'split-screen-wrapper')]",
            "//div[contains(@class, 'splitScreenWrapper')]",
        ]

        for selector in selectors:
            try:
                element = WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )
                if element.is_displayed():
                    try:
                        element.click()
                    except:
                        try:
                            driver.execute_script("arguments[0].click();", element)
                        except:
                            ActionChains(driver).move_to_element(
                                element
                            ).click().perform()
                    logger.debug(green("Split window removed successfully"))
                    return
            except:
                continue

        logger.debug(red(f"Split window not found or operation timed out"))
    except Exception as e:
        logger.debug(red(f"Error handling split window: {str(e)}"))


def _set_interactivity(
    driver, comment=True, stitch=True, duet=True, *args, **kwargs
) -> None:
    try:
        logger.debug(green("Setting interactivity settings"))

        time.sleep(0.1)

        show_more_selectors = [
            "//div[contains(text(), 'Show more')]",
            "//button[contains(text(), 'Show more')]",
            "//div[contains(@class, 'show-more')]",
            "//button[contains(@class, 'show-more')]",
            "//div[contains(@class, 'more-options')]",
            "//button[contains(@class, 'more-options')]",
        ]

        show_more_clicked = False
        for selector in show_more_selectors:
            try:
                element = WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )
                if element.is_displayed():
                    try:
                        element.click()
                        show_more_clicked = True
                        logger.debug(green("Successfully clicked 'Show more' button"))
                        time.sleep(0.2)
                        break
                    except:
                        try:
                            driver.execute_script("arguments[0].click();", element)
                            show_more_clicked = True
                            logger.debug(
                                green(
                                    "Successfully clicked 'Show more' button using JavaScript"
                                )
                            )
                            time.sleep(0.2)
                            break
                        except:
                            ActionChains(driver).move_to_element(
                                element
                            ).click().perform()
                            show_more_clicked = True
                            logger.debug(
                                green(
                                    "Successfully clicked 'Show more' button using ActionChains"
                                )
                            )
                            time.sleep(0.2)
                            break
            except:
                continue

        if not show_more_clicked:
            logger.warning(
                "Could not find 'Show more' button, trying to find settings directly"
            )

        comment_selectors = [
            config["selectors"]["upload"]["comment"],
            "//div[contains(text(), 'Comment')]/following-sibling::div//input",
            "//div[contains(@class, 'comment')]//input[@type='checkbox']",
            "//div[contains(@class, 'comment')]//div[contains(@class, 'checkbox')]",
            "//div[contains(@class, 'comment')]//div[contains(@class, 'switch')]",
            "//div[contains(text(), 'Comments')]//following::input[@type='checkbox']",
            "//div[contains(text(), 'Comments')]//following::div[contains(@class, 'switch')]",
        ]

        stitch_selectors = [
            config["selectors"]["upload"]["stitch"],
            "//div[contains(text(), 'Stitch')]/following-sibling::div//input",
            "//div[contains(@class, 'stitch')]//input[@type='checkbox']",
            "//div[contains(@class, 'stitch')]//div[contains(@class, 'checkbox')]",
            "//div[contains(@class, 'stitch')]//div[contains(@class, 'switch')]",
            "//div[contains(text(), 'Stitch')]//following::input[@type='checkbox']",
            "//div[contains(text(), 'Stitch')]//following::div[contains(@class, 'switch')]",
        ]

        duet_selectors = [
            config["selectors"]["upload"]["duet"],
            "//div[contains(text(), 'Duet')]/following-sibling::div//input",
            "//div[contains(@class, 'duet')]//input[@type='checkbox']",
            "//div[contains(@class, 'duet')]//div[contains(@class, 'checkbox')]",
            "//div[contains(@class, 'duet')]//div[contains(@class, 'switch')]",
            "//div[contains(text(), 'Duet')]//following::input[@type='checkbox']",
            "//div[contains(text(), 'Duet')]//following::div[contains(@class, 'switch')]",
        ]

        def find_and_click_element(selectors, setting_name):
            for selector in selectors:
                try:
                    element = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )
                    if element.is_displayed():
                        try:
                            element.click()
                        except:
                            try:
                                driver.execute_script("arguments[0].click();", element)
                            except:
                                ActionChains(driver).move_to_element(
                                    element
                                ).click().perform()
                        logger.debug(green(f"Successfully toggled {setting_name}"))
                        return True
                except:
                    continue
            return False

        comment_success = find_and_click_element(comment_selectors, "comment")
        stitch_success = find_and_click_element(stitch_selectors, "stitch")
        duet_success = find_and_click_element(duet_selectors, "duet")

        if not (comment_success or stitch_success or duet_success):
            logger.warning("Could not find any interactivity settings to modify")
        else:
            logger.debug(green("Successfully set interactivity settings"))

    except Exception as e:
        logger.error(f"Failed to set interactivity settings: {str(e)}")
        pass


def _post_video(driver) -> None:
    logger.debug(green("Clicking the post button"))

    try:
        post_selectors = [
            config["selectors"]["upload"]["post"],
            "//button[contains(text(), 'Post')]",
            "//button[contains(@class, 'post')]",
            "//button[contains(@class, 'submit')]",
            "//button[@type='submit']",
            "//div[contains(@class, 'post-button')]/button",
            "//div[contains(@class, 'submit-button')]/button",
            "//div[contains(@class, 'post')]//button",
            "//div[contains(@class, 'submit')]//button",
        ]

        post_button = None
        for selector in post_selectors:
            try:
                element = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
                if element.is_displayed():
                    post_button = element
                    break
            except:
                continue

        if not post_button:
            raise Exception("Could not find post button")

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
            post_button,
        )
        time.sleep(0.2)

        click_success = False
        click_methods = [
            lambda: post_button.click(),
            lambda: driver.execute_script("arguments[0].click();", post_button),
            lambda: ActionChains(driver).move_to_element(post_button).click().perform(),
            lambda: driver.execute_script(
                "document.querySelector('button[type=\"submit\"]').click()"
            ),
        ]

        for click_method in click_methods:
            try:
                click_method()
                click_success = True
                time.sleep(1) # small wait to ensure click registers
                break
            except:
                continue

        if not click_success:
            raise Exception("All click methods failed")

        time.sleep(1)  # wait for the page to start reacting

        confirmation_selectors = [
            config["selectors"]["upload"]["post_confirmation"],
            "//*[contains(text(), 'Video uploaded successfully')]",
            "//*[contains(text(), 'Uploaded successfully')]",
            "//*[contains(text(), 'posted successfully')]",
            "//h2[contains(text(), 'Manage your posts')]",
            "//button[contains(text(), 'Upload another')]",
        ]

        confirmation_found = False
        for selector in confirmation_selectors:
            try:
                WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )
                confirmation_found = True
                break
            except:
                continue
        
        if not confirmation_found:
            try:
                logger.debug("Checking for URL change as fallback confirmation...")
                WebDriverWait(driver, 3).until(
                    EC.url_contains("creator-center/content")
                )
                confirmation_found = True
                logger.debug(green("URL changed to creator center, confirming post."))
            except:
                pass

        if not confirmation_found:
            raise Exception("No post confirmation found")

        logger.debug(green("Video posted successfully"))

    except Exception as e:
        logger.error(f"Failed to post video: {str(e)}")
        raise FailedToUpload(f"Failed to post video: {str(e)}")


def _check_valid_path(path: str) -> bool:
    if exists(path):
        return True
    return False


def _convert_videos_dict(videos_list_of_dictionaries) -> List:
    if not videos_list_of_dictionaries:
        raise RuntimeError("No videos to upload")

    valid_path = config["valid_path_names"]
    valid_description = config["valid_descriptions"]

    correct_path = valid_path[0]
    correct_description = valid_description[0]

    def intersection(lst1, lst2):
        return list(set(lst1) & set(lst2))

    return_list = []
    for elem in videos_list_of_dictionaries:
        elem = {k.strip().lower(): v for k, v in elem.items()}

        keys = elem.keys()
        path_intersection = intersection(valid_path, keys)
        description_intersection = intersection(valid_description, keys)

        if path_intersection:
            path = elem[path_intersection.pop()]

            if not _check_valid_path(path):
                raise RuntimeError("Invalid path: " + path)

            elem[correct_path] = path
        else:
            for _, value in elem.items():
                if _check_valid_path(value):
                    elem[correct_path] = value
                    break
            else:
                raise RuntimeError("Path not found in dictionary: " + str(elem))

        if description_intersection:
            elem[correct_description] = elem[description_intersection.pop()]
        else:
            for _, value in elem.items():
                if not _check_valid_path(value):
                    elem[correct_description] = value
                    break
            else:
                elem[correct_description] = ""

        return_list.append(elem)

    return return_list


def __get_driver_timezone(driver):
    timezone_str = driver.execute_script(
        "return Intl.DateTimeFormat().resolvedOptions().timeZone"
    )
    return timezone_str


def _refresh_with_alert(driver) -> None:
    try:
        driver.refresh()
        WebDriverWait(driver, config["explicit_wait"]).until(EC.alert_is_present())
        driver.switch_to.alert.accept()
    except:
        pass


class DescriptionTooLong(Exception):
    def __init__(self, message=None):
        super().__init__(message or self.__doc__)


class FailedToUpload(Exception):
    def __init__(self, message=None):
        super().__init__(message or self.__doc__)
