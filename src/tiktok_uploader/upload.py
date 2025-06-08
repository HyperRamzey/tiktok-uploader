"""
`tiktok_uploader` module for uploading videos to TikTok

Key Functions
-------------
upload_video : Uploads a single TikTok video
upload_videos : Uploads multiple TikTok videos
"""

from os.path import abspath, exists
from typing import List, Optional
import time
import pytz
import datetime
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
from tiktok_uploader.utils import bold, cyan, green, red
from tiktok_uploader.proxy_auth_extension.proxy_auth_extension import proxy_is_working


def upload_video(
    filename=None,
    description="",
    cookies="",
    schedule: datetime.datetime = None,
    username="",
    password="",
    sessionid=None,
    cookies_list=None,
    cookies_str=None,
    proxy=None,
    product_id: Optional[str] = None,
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
                "schedule": schedule,
                "product_id": product_id,
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
            schedule = video.get("schedule", None)
            product_id = video.get("product_id", None)

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

            if schedule:
                timezone = pytz.UTC
                if schedule.tzinfo is None:
                    schedule = schedule.astimezone(timezone)
                elif int(schedule.utcoffset().total_seconds()) == 0:
                    schedule = timezone.localize(schedule)
                else:
                    print(
                        f"{schedule} is invalid, the schedule datetime must be naive or aware with UTC timezone, skipping"
                    )
                    failed.append(video)
                    continue

                valid_tiktok_minute_multiple = 5
                schedule = _get_valid_schedule_minute(
                    schedule, valid_tiktok_minute_multiple
                )
                if not _check_valid_schedule(schedule):
                    print(
                        f"{schedule} is invalid, the schedule datetime must be as least 20 minutes in the future, and a maximum of 10 days, skipping"
                    )
                    failed.append(video)
                    continue

            complete_upload_form(
                driver,
                path,
                description,
                schedule,
                skip_split_window,
                product_id=product_id,
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
    schedule: datetime.datetime,
    skip_split_window: bool,
    product_id: Optional[str] = None,
    num_retries: int = 1,
    headless=False,
    **kwargs,
) -> None:
    _go_to_upload(driver)
    time.sleep(2)
    _remove_cookies_window(driver)

    upload_complete_event = threading.Event()

    def upload_video():
        _set_video(driver, path=path, **kwargs)
        upload_complete_event.set()

    upload_thread = threading.Thread(target=upload_video)
    upload_thread.start()

    upload_complete_event.wait()

    if not skip_split_window:
        _remove_split_window(driver)
    _set_interactivity(driver, **kwargs)
    _set_description(driver, description)
    if schedule:
        _set_schedule_video(driver, schedule)
    if product_id:
        _add_product_link(driver, product_id)
    _post_video(driver)


def _go_to_upload(driver) -> None:
    logger.debug(green("Navigating to upload page"))

    if driver.current_url != config["paths"]["upload"]:
        driver.get(config["paths"]["upload"])
    else:
        _refresh_with_alert(driver)

    root_selector = EC.presence_of_element_located((By.ID, "root"))
    WebDriverWait(driver, config["explicit_wait"]).until(root_selector)

    driver.switch_to.default_content()


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

    description = description.encode("utf-8", "ignore").decode("utf-8")

    saved_description = description

    WebDriverWait(driver, config["implicit_wait"]).until(
        EC.presence_of_element_located(
            (By.XPATH, config["selectors"]["upload"]["description"])
        )
    )

    desc = driver.find_element(By.XPATH, config["selectors"]["upload"]["description"])

    desc.click()

    WebDriverWait(driver, config["explicit_wait"]).until(lambda driver: desc.text != "")

    desc.send_keys(Keys.END)
    _clear(desc)

    WebDriverWait(driver, config["explicit_wait"]).until(lambda driver: desc.text == "")

    desc.click()

    time.sleep(1)

    try:
        words = description.split(" ")
        for word in words:
            if word[0] == "#":
                desc.send_keys(word)
                desc.send_keys(" " + Keys.BACKSPACE)
                WebDriverWait(driver, config["implicit_wait"]).until(
                    EC.presence_of_element_located(
                        (By.XPATH, config["selectors"]["upload"]["mention_box"])
                    )
                )
                time.sleep(config["add_hashtag_wait"])
                desc.send_keys(Keys.ENTER)
            elif word[0] == "@":
                logger.debug(green("- Adding Mention: " + word))
                desc.send_keys(word)
                desc.send_keys(" ")
                time.sleep(1)
                desc.send_keys(Keys.BACKSPACE)

                WebDriverWait(driver, config["explicit_wait"]).until(
                    EC.presence_of_element_located(
                        (By.XPATH, config["selectors"]["upload"]["mention_box_user_id"])
                    )
                )

                found = False
                waiting_interval = 0.5
                timeout = 5
                start_time = time.time()

                while not found and (time.time() - start_time < timeout):
                    user_id_elements = driver.find_elements(
                        By.XPATH, config["selectors"]["upload"]["mention_box_user_id"]
                    )
                    time.sleep(1)

                    for i in range(len(user_id_elements)):
                        user_id_element = user_id_elements[i]
                        if user_id_element and user_id_element.is_enabled:
                            username = user_id_element.text.split(" ")[0]
                            if username.lower() == word[1:].lower():
                                found = True
                                print("Matching User found : Clicking User")
                                for j in range(i):
                                    desc.send_keys(Keys.DOWN)
                                desc.send_keys(Keys.ENTER)
                                break

                        if not found:
                            print(
                                f"No match. Waiting for {waiting_interval} seconds..."
                            )
                            time.sleep(waiting_interval)

            else:
                desc.send_keys(word + " ")

    except Exception as exception:
        print("Failed to set description: ", exception)
        _clear(desc)
        desc.send_keys(saved_description)


def _clear(element) -> None:
    element.send_keys(2 * len(element.text) * Keys.BACKSPACE)


def _set_video(driver, path: str = "", num_retries: int = 3, **kwargs) -> None:
    logger.debug(green("Uploading video file"))

    for _ in range(num_retries):
        try:
            driverWait = WebDriverWait(driver, config["explicit_wait"])
            upload_boxWait = EC.presence_of_element_located(
                (By.XPATH, config["selectors"]["upload"]["upload_video"])
            )
            driverWait.until(upload_boxWait)
            upload_box = driver.find_element(
                By.XPATH, config["selectors"]["upload"]["upload_video"]
            )
            upload_box.send_keys(path)
            process_confirmation = EC.presence_of_element_located(
                (By.XPATH, config["selectors"]["upload"]["process_confirmation"])
            )
            WebDriverWait(driver, config["explicit_wait"]).until(process_confirmation)
            return
        except TimeoutException as exception:
            print("TimeoutException occurred:\n", exception)
        except Exception as exception:
            print(exception)
            raise FailedToUpload(exception)


def _remove_cookies_window(driver) -> None:
    logger.debug(green(f"Removing cookies window"))
    try:
        time.sleep(2)
        cookies_banner = WebDriverWait(driver, config["implicit_wait"]).until(
            EC.presence_of_element_located(
                (By.TAG_NAME, config["selectors"]["upload"]["cookies_banner"]["banner"])
            )
        )

        shadow_root = cookies_banner.shadow_root
        if shadow_root:
            item = WebDriverWait(driver, config["implicit_wait"]).until(
                EC.visibility_of(
                    shadow_root.find_element(
                        By.CSS_SELECTOR,
                        config["selectors"]["upload"]["cookies_banner"]["button"],
                    )
                )
            )

            accept_button = WebDriverWait(driver, config["implicit_wait"]).until(
                EC.element_to_be_clickable(item.find_elements(By.TAG_NAME, "button")[0])
            )
            accept_button.click()
            logger.debug(green("Cookies accepted"))
        else:
            logger.error("Shadow root not found for cookies banner.")

    except Exception as e:
        logger.error(f"Error while accepting cookies: {e}")


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
                element = WebDriverWait(driver, 5).until(
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

        time.sleep(2)

        comment_selectors = [
            config["selectors"]["upload"]["comment"],
            "//div[contains(@class, 'comment')]//input[@type='checkbox']",
            "//div[contains(@class, 'comment')]//div[contains(@class, 'checkbox')]",
            "//div[contains(@class, 'comment')]//div[contains(@class, 'switch')]",
        ]

        stitch_selectors = [
            config["selectors"]["upload"]["stitch"],
            "//div[contains(@class, 'stitch')]//input[@type='checkbox']",
            "//div[contains(@class, 'stitch')]//div[contains(@class, 'checkbox')]",
            "//div[contains(@class, 'stitch')]//div[contains(@class, 'switch')]",
        ]

        duet_selectors = [
            config["selectors"]["upload"]["duet"],
            "//div[contains(@class, 'duet')]//input[@type='checkbox']",
            "//div[contains(@class, 'duet')]//div[contains(@class, 'checkbox')]",
            "//div[contains(@class, 'duet')]//div[contains(@class, 'switch')]",
        ]

        def find_and_click_element(selectors, setting_name):
            for selector in selectors:
                try:
                    element = WebDriverWait(driver, 5).until(
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


def _set_schedule_video(driver, schedule: datetime.datetime) -> None:
    logger.debug(green("Setting schedule"))

    driver_timezone = __get_driver_timezone(driver)
    schedule = schedule.astimezone(driver_timezone)

    month = schedule.month
    day = schedule.day
    hour = schedule.hour
    minute = schedule.minute

    try:
        switch = driver.find_element(
            By.XPATH, config["selectors"]["schedule"]["switch"]
        )
        switch.click()
        __date_picker(driver, month, day)
        __time_picker(driver, hour, minute)
    except Exception as e:
        msg = f"Failed to set schedule: {e}"
        logger.error(red(msg))
        raise FailedToUpload()


def __date_picker(driver, month: int, day: int) -> None:
    logger.debug(green("Picking date"))

    condition = EC.presence_of_element_located(
        (By.XPATH, config["selectors"]["schedule"]["date_picker"])
    )
    date_picker = WebDriverWait(driver, config["implicit_wait"]).until(condition)
    date_picker.click()

    condition = EC.presence_of_element_located(
        (By.XPATH, config["selectors"]["schedule"]["calendar"])
    )
    calendar = WebDriverWait(driver, config["implicit_wait"]).until(condition)

    calendar_month = driver.find_element(
        By.XPATH, config["selectors"]["schedule"]["calendar_month"]
    ).text
    n_calendar_month = datetime.datetime.strptime(calendar_month, "%B").month
    if n_calendar_month != month:
        if n_calendar_month < month:
            arrow = driver.find_elements(
                By.XPATH, config["selectors"]["schedule"]["calendar_arrows"]
            )[-1]
        else:
            arrow = driver.find_elements(
                By.XPATH, config["selectors"]["schedule"]["calendar_arrows"]
            )[0]
        arrow.click()
    valid_days = driver.find_elements(
        By.XPATH, config["selectors"]["schedule"]["calendar_valid_days"]
    )

    day_to_click = None
    for day_option in valid_days:
        if int(day_option.text) == day:
            day_to_click = day_option
            break
    if day_to_click:
        day_to_click.click()
    else:
        raise Exception("Day not found in calendar")

    __verify_date_picked_is_correct(driver, month, day)


def __verify_date_picked_is_correct(driver, month: int, day: int):
    date_selected = driver.find_element(
        By.XPATH, config["selectors"]["schedule"]["date_picker"]
    ).text
    date_selected_month = int(date_selected.split("-")[1])
    date_selected_day = int(date_selected.split("-")[2])

    if date_selected_month == month and date_selected_day == day:
        logger.debug(green("Date picked correctly"))
    else:
        msg = f"Something went wrong with the date picker, expected {month}-{day} but got {date_selected_month}-{date_selected_day}"
        logger.error(msg)
        raise Exception(msg)


def __time_picker(driver, hour: int, minute: int) -> None:
    logger.debug(green("Picking time"))

    condition = EC.presence_of_element_located(
        (By.XPATH, config["selectors"]["schedule"]["time_picker"])
    )
    time_picker = WebDriverWait(driver, config["implicit_wait"]).until(condition)
    time_picker.click()

    condition = EC.presence_of_element_located(
        (By.XPATH, config["selectors"]["schedule"]["time_picker_container"])
    )
    time_picker_container = WebDriverWait(driver, config["implicit_wait"]).until(
        condition
    )

    hour_options = driver.find_elements(
        By.XPATH, config["selectors"]["schedule"]["timepicker_hours"]
    )
    minute_options = driver.find_elements(
        By.XPATH, config["selectors"]["schedule"]["timepicker_minutes"]
    )

    hour_to_click = hour_options[hour]
    minute_option_correct_index = int(minute / 5)
    minute_to_click = minute_options[minute_option_correct_index]

    time.sleep(1)
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        hour_to_click,
    )
    time.sleep(1)
    hour_to_click.click()

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        minute_to_click,
    )
    time.sleep(1)
    minute_to_click.click()

    time_picker.click()

    time.sleep(0.5)
    __verify_time_picked_is_correct(driver, hour, minute)


def __verify_time_picked_is_correct(driver, hour: int, minute: int):
    time_selected = driver.find_element(
        By.XPATH, config["selectors"]["schedule"]["time_picker_text"]
    ).text
    time_selected_hour = int(time_selected.split(":")[0])
    time_selected_minute = int(time_selected.split(":")[1])

    if time_selected_hour == hour and time_selected_minute == minute:
        logger.debug(green("Time picked correctly"))
    else:
        msg = (
            f"Something went wrong with the time picker, "
            f"expected {hour:02d}:{minute:02d} "
            f"but got {time_selected_hour:02d}:{time_selected_minute:02d}"
        )
        raise Exception(msg)


def _post_video(driver) -> None:
    logger.debug(green("Clicking the post button"))

    try:
        post = WebDriverWait(driver, config["implicit_wait"]).until(
            EC.element_to_be_clickable(
                (By.XPATH, config["selectors"]["upload"]["post"])
            )
        )

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", post
        )
        time.sleep(1)

        try:
            post.click()
        except ElementClickInterceptedException:
            logger.debug(green("Direct click failed, trying JavaScript click"))
            driver.execute_script("arguments[0].click();", post)
        except Exception:
            logger.debug(
                green("Both click methods failed, trying alternative selector")
            )
            driver.execute_script(
                "document.querySelector(\"button[type='submit']\").click()"
            )

        post_confirmation = EC.presence_of_element_located(
            (By.XPATH, config["selectors"]["upload"]["post_confirmation"])
        )
        WebDriverWait(driver, 5).until(post_confirmation)

        logger.debug(green("Video posted successfully"))
    except Exception as e:
        logger.error(f"Failed to post video: {str(e)}")
        raise FailedToUpload("Failed to click post button or confirm upload")


def _check_valid_path(path: str) -> bool:
    if not path:
        return False
    return exists(path) and path.split(".")[-1] in config["supported_file_types"]


def _get_valid_schedule_minute(schedule, valid_multiple) -> datetime.datetime:
    if _is_valid_schedule_minute(schedule.minute, valid_multiple):
        return schedule
    else:
        return _set_valid_schedule_minute(schedule, valid_multiple)


def _is_valid_schedule_minute(minute, valid_multiple) -> bool:
    if minute % valid_multiple != 0:
        return False
    else:
        return True


def _set_valid_schedule_minute(schedule, valid_multiple) -> datetime.datetime:
    minute = schedule.minute

    remainder = minute % valid_multiple
    integers_to_valid_multiple = 5 - remainder
    schedule += datetime.timedelta(minutes=integers_to_valid_multiple)

    return schedule


def _check_valid_schedule(schedule: datetime.datetime) -> bool:
    valid_tiktok_minute_multiple = 5
    margin_to_complete_upload_form = 5

    datetime_utc_now = pytz.UTC.localize(datetime.datetime.utcnow())
    min_datetime_tiktok_valid = datetime_utc_now + datetime.timedelta(minutes=15)
    min_datetime_tiktok_valid += datetime.timedelta(
        minutes=margin_to_complete_upload_form
    )
    max_datetime_tiktok_valid = datetime_utc_now + datetime.timedelta(days=10)
    if schedule < min_datetime_tiktok_valid or schedule > max_datetime_tiktok_valid:
        return False
    elif not _is_valid_schedule_minute(schedule.minute, valid_tiktok_minute_multiple):
        return False
    else:
        return True


def _get_splice_index(
    nearest_mention: int, nearest_hashtag: int, description: str
) -> int:
    if nearest_mention == -1 and nearest_hashtag == -1:
        return len(description)
    elif nearest_hashtag == -1:
        return nearest_mention
    elif nearest_mention == -1:
        return nearest_hashtag
    else:
        return min(nearest_mention, nearest_hashtag)


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


def __get_driver_timezone(driver) -> pytz.timezone:
    timezone_str = driver.execute_script(
        "return Intl.DateTimeFormat().resolvedOptions().timeZone"
    )
    return pytz.timezone(timezone_str)


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


def _add_product_link(driver, product_id: str) -> None:
    logger.debug(green(f"Attempting to add product link for ID: {product_id}..."))
    try:
        wait = WebDriverWait(driver, 20)
        add_link_button_xpath = (
            "//button[contains(@class, 'Button__root') and contains(., 'Add')]"
        )
        add_link_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, add_link_button_xpath))
        )
        add_link_button.click()
        logger.debug(green("Clicked 'Add Product Link' button."))
        time.sleep(1)
        try:
            first_next_button_xpath = "//button[contains(@class, 'TUXButton--primary') and .//div[text()='Next']]"
            first_next_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, first_next_button_xpath))
            )
            first_next_button.click()
            logger.debug(green("Clicked first 'Next' button in modal."))
            time.sleep(1)
        except TimeoutException:
            logger.debug("First 'Next' button not found or not needed, proceeding...")
        search_input_xpath = "//input[@placeholder='Search products']"
        search_input = wait.until(
            EC.visibility_of_element_located((By.XPATH, search_input_xpath))
        )
        search_input.clear()
        search_input.send_keys(product_id)
        search_input.send_keys(Keys.RETURN)
        logger.debug(green(f"Entered product ID '{product_id}' and pressed Enter."))
        time.sleep(2)
        product_radio_xpath = f"//tr[.//span[contains(text(), '{product_id}')] or .//div[contains(text(), '{product_id}')]]//input[@type='radio' and contains(@class, 'TUXRadioStandalone-input')]"
        logger.debug(f"Looking for radio button with XPath: {product_radio_xpath}")
        product_radio = wait.until(
            EC.element_to_be_clickable((By.XPATH, product_radio_xpath))
        )
        driver.execute_script("arguments[0].click();", product_radio)
        logger.debug(green(f"Selected product radio for ID: {product_id}"))
        time.sleep(1)
        second_next_button_xpath = (
            "//button[contains(@class, 'TUXButton--primary') and .//div[text()='Next']]"
        )
        second_next_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, second_next_button_xpath))
        )
        second_next_button.click()
        logger.debug(green("Clicked second 'Next' button."))
        time.sleep(1)
        final_add_button_xpath = (
            "//button[contains(@class, 'TUXButton--primary') and .//div[text()='Add']]"
        )
        final_add_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, final_add_button_xpath))
        )
        final_add_button.click()
        logger.debug(green("Clicked final 'Add' button. Product link should be added."))
        wait.until(
            EC.invisibility_of_element_located((By.XPATH, final_add_button_xpath))
        )
        logger.debug(green("Product link modal closed."))

    except TimeoutException as e:
        logger.error(
            red(
                f"Error: Timed out waiting for element during product link addition. XPath might be wrong or element didn't appear."
            )
        )
        print(
            f"Warning: Failed to add product link {product_id} due to timeout. Continuing upload without link."
        )
    except NoSuchElementException as e:
        logger.error(
            red(
                f"Error: Could not find element during product link addition. XPath might be wrong."
            )
        )
        print(
            f"Warning: Failed to add product link {product_id} because an element was not found. Continuing upload without link."
        )
    except Exception as e:
        logger.error(
            red(f"An unexpected error occurred while adding product link: {e}")
        )
        print(
            f"Warning: An unexpected error occurred while adding product link {product_id}. Continuing upload without link."
        )
