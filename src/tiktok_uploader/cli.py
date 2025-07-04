from argparse import ArgumentParser
from os.path import exists, join
import datetime
import json

from tiktok_uploader.upload import upload_video
from tiktok_uploader.auth import login_accounts, save_cookies


def main():
    args = get_uploader_args()
    args = validate_uploader_args(args=args)
    schedule = parse_schedule(args.schedule)
    proxy = parse_proxy(args.proxy)
    product_id = args.product_id
    result = upload_video(
        filename=args.video,
        description=args.description,
        schedule=schedule,
        username=args.username,
        password=args.password,
        cookies=args.cookies,
        proxy=proxy,
        product_id=product_id,
        sessionid=args.sessionid,
        headless=not args.attach,
    )

    print("-------------------------")
    if result:
        print("Error while uploading video")
    else:
        print("Video uploaded successfully")
    print("-------------------------")


def get_uploader_args():
    parser = ArgumentParser(
        description="TikTok uploader is a video uploader which can upload a"
        + "video from your computer to the TikTok using selenium automation"
    )
    parser.add_argument("-v", "--video", help="Video file", required=True)
    parser.add_argument("-d", "--description", help="Description", default="")
    parser.add_argument(
        "-t",
        "--schedule",
        help="Schedule UTC time in %Y-%m-%d %H:%M format ",
        default=None,
    )
    parser.add_argument(
        "--proxy", help="Proxy user:pass@host:port or host:port format", default=None
    )
    parser.add_argument(
        "--product-id",
        help="ID of the product to link in the video (if applicable)",
        default=None,
    )
    parser.add_argument("-c", "--cookies", help="The cookies you want to use")
    parser.add_argument("-s", "--sessionid", help="The session id you want to use")
    parser.add_argument("-u", "--username", help="Your TikTok email / username")
    parser.add_argument("-p", "--password", help="Your TikTok password")
    parser.add_argument(
        "--attach",
        "-a",
        action="store_true",
        default=False,
        help="Runs the program in headless mode (no browser window)",
    )

    return parser.parse_args()


def validate_uploader_args(args: dict):
    if not exists(args.video):
        raise FileNotFoundError(f"Could not find the video file at {args['video']}")
    if args.cookies and (args.username or args.password):
        raise ValueError("You can not pass in both cookies and username / password")

    return args


def auth():
    args = get_auth_args()
    args = validate_auth_args(args=args)
    if args.input:
        login_info = get_login_info(path=args.input, header=args.header)
    else:
        login_info = [(args.username, args.password)]

    username_and_cookies = login_accounts(accounts=login_info)

    for username, cookies in username_and_cookies.items():
        save_cookies(path=join(args.output, username + ".txt"), cookies=cookies)


def get_auth_args():
    parser = ArgumentParser(
        description="TikTok Auth is a program which can log you into multiple accounts sequentially"
    )
    parser.add_argument(
        "-o", "--output", default="tmp", help="The output folder to save the cookies to"
    )
    parser.add_argument("-i", "--input", help="A csv file with username and password")
    parser.add_argument("-u", "--username", help="Your TikTok email / username")
    parser.add_argument("-p", "--password", help="Your TikTok password")

    return parser.parse_args()


def validate_auth_args(args):
    if (args["username"] and args["password"]) and args["input"]:
        raise ValueError("You can not pass in both username / password and input file")

    return args


def get_login_info(path: str, header=True) -> list:
    with open(path, "r", encoding="utf-8") as file:
        file = file.readlines()
        if header:
            file = file[1:]
        return [line.split(",")[:2] for line in file]


def parse_schedule(schedule_raw):
    if schedule_raw:
        schedule = datetime.datetime.strptime(schedule_raw, "%Y-%m-%d %H:%M")
    else:
        schedule = None
    return schedule


def parse_proxy(proxy_raw):
    proxy = {}
    if proxy_raw:
        if "@" in proxy_raw:
            proxy["user"] = proxy_raw.split("@")[0].split(":")[0]
            proxy["pass"] = proxy_raw.split("@")[0].split(":")[1]
            proxy["host"] = proxy_raw.split("@")[1].split(":")[0]
            proxy["port"] = proxy_raw.split("@")[1].split(":")[1]
        else:
            proxy["host"] = proxy_raw.split(":")[0]
            proxy["port"] = proxy_raw.split(":")[1]
    return proxy
