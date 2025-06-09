from argparse import ArgumentParser
from os.path import exists, join
import json
import sys
import os

from tiktok_uploader.upload import upload_video
from tiktok_uploader.auth import login_accounts, save_cookies
from tiktok_uploader.utils import green, red, yellow, blue, validate_video_file
from tiktok_uploader import config


def main():
    try:
        args = get_uploader_args()
        args = validate_uploader_args(args=args)

        proxy = parse_proxy(args.proxy)

        print(blue("TikTok Uploader Starting..."))
        print(f"Video: {args.video}")
        print(
            f"Description: {args.description[:50]}..."
            if len(args.description) > 50
            else f"Description: {args.description}"
        )

        if proxy:
            print(f"Proxy: {proxy.get('host', 'N/A')}")

        result = upload_video(
            filename=args.video,
            description=args.description,
            username=args.username,
            password=args.password,
            cookies=args.cookies,
            proxy=proxy,
            sessionid=args.sessionid,
            headless=not args.attach,
        )

        print("=" * 50)
        if result:
            print(red("❌ Error while uploading video"))
            print(red(f"Failed uploads: {len(result)}"))
            sys.exit(1)
        else:
            print(green("✅ Video uploaded successfully"))
        print("=" * 50)

    except KeyboardInterrupt:
        print(yellow("\n⚠️ Upload cancelled by user"))
        sys.exit(1)
    except Exception as e:
        print(red(f"❌ Fatal error: {e}"))
        sys.exit(1)


def get_uploader_args():
    parser = ArgumentParser(
        description="TikTok Uploader - Upload videos to TikTok using automation",
        epilog="Example: tiktok-uploader -v video.mp4 -d 'My video description' -c cookies.txt",
    )

    # Primary arguments
    parser.add_argument(
        "-v",
        "--video",
        help="Path to video file to upload",
        required=True,
        metavar="FILE",
    )
    parser.add_argument(
        "-d",
        "--description",
        help="Video description (supports hashtags and mentions)",
        default="",
        metavar="TEXT",
    )

    # Secondary arguments
    parser.add_argument(
        "--proxy",
        help="Proxy in format user:pass@host:port or host:port",
        default=None,
        metavar="PROXY",
    )

    # Authentication group
    auth_group = parser.add_argument_group(
        "authentication", "Choose one authentication method"
    )
    auth_group.add_argument(
        "-c", "--cookies", help="Path to cookies file", metavar="FILE"
    )
    auth_group.add_argument(
        "-s", "--sessionid", help="TikTok sessionid cookie value", metavar="ID"
    )
    auth_group.add_argument(
        "-u", "--username", help="TikTok email or username", metavar="USER"
    )
    auth_group.add_argument("-p", "--password", help="TikTok password", metavar="PASS")

    browser_group = parser.add_argument_group(
        "browser", "Browser configuration options"
    )
    browser_group.add_argument(
        "--attach",
        "-a",
        action="store_true",
        default=False,
        help="Show browser window (disable headless mode)",
    )

    return parser.parse_args()


def validate_uploader_args(args):
    if not exists(args.video):
        raise FileNotFoundError(f"❌ Video file not found: {args.video}")

    if not validate_video_file(args.video, config["supported_file_types"]):
        supported = ", ".join(config["supported_file_types"])
        raise ValueError(f"❌ Unsupported video format. Supported: {supported}")
    file_size_mb = os.path.getsize(args.video) / (1024 * 1024)
    auth_methods = sum(
        [
            bool(args.cookies),
            bool(args.sessionid),
            bool(args.username and args.password),
        ]
    )

    if auth_methods == 0:
        raise ValueError("❌ No authentication method provided. Use -c, -s, or -u/-p")

    if auth_methods > 1:
        raise ValueError("❌ Multiple authentication methods provided. Choose only one")

    if args.cookies and not exists(args.cookies):
        raise FileNotFoundError(f"❌ Cookies file not found: {args.cookies}")

    if (args.username and not args.password) or (args.password and not args.username):
        raise ValueError("❌ Both username and password are required for login")

    if len(args.description) > config.get("max_description_length", 150):
        max_len = config.get("max_description_length", 150)
        print(yellow(f"⚠️ Description truncated to {max_len} characters"))
        args.description = args.description[:max_len]

    return args


def auth():
    try:
        args = get_auth_args()
        args = validate_auth_args(args=args)

        print(blue("TikTok Account Authentication Starting..."))

        if args.input:
            login_info = get_login_info(path=args.input, header=args.header)
            print(f"Processing {len(login_info)} accounts from file")
        else:
            login_info = [(args.username, args.password)]
            print(f"Processing single account: {args.username}")

        os.makedirs(args.output, exist_ok=True)

        username_and_cookies = login_accounts(accounts=login_info)

        success_count = 0
        for username, cookies in username_and_cookies.items():
            try:
                cookie_path = join(args.output, f"{username}.txt")
                save_cookies(path=cookie_path, cookies=cookies)
                print(green(f"Saved cookies for {username}"))
                success_count += 1
            except Exception as e:
                print(red(f"❌ Failed to save cookies for {username}: {e}"))

        print("=" * 50)
        print(
            green(
                f"Authentication completed: {success_count}/{len(login_info)} accounts"
            )
        )
        print(f"Cookies saved to: {args.output}")
        print("=" * 50)

    except Exception as e:
        print(red(f"❌ Authentication failed: {e}"))
        sys.exit(1)


def get_auth_args():
    parser = ArgumentParser(
        description="TikTok Account Authenticator - Login to accounts and save cookies"
    )

    parser.add_argument(
        "-o",
        "--output",
        default="cookies",
        help="Output directory for saved cookies",
        metavar="DIR",
    )
    parser.add_argument(
        "-i", "--input", help="CSV file with username,password pairs", metavar="FILE"
    )
    parser.add_argument(
        "--header", action="store_true", default=True, help="CSV file has header row"
    )
    parser.add_argument("-u", "--username", help="Single username", metavar="USER")
    parser.add_argument("-p", "--password", help="Single password", metavar="PASS")

    return parser.parse_args()


def validate_auth_args(args):
    has_single = bool(args.username and args.password)
    has_file = bool(args.input)

    if not (has_single or has_file):
        raise ValueError("❌ Provide either username/password or input CSV file")

    if has_single and has_file:
        raise ValueError("❌ Cannot use both single credentials and CSV file")

    if args.input and not exists(args.input):
        raise FileNotFoundError(f"❌ Input file not found: {args.input}")

    return args


def get_login_info(path: str, header=True) -> list:
    try:
        with open(path, "r", encoding="utf-8") as file:
            lines = file.readlines()
            if header:
                lines = lines[1:]

            login_info = []
            for i, line in enumerate(lines, start=1):
                parts = line.strip().split(",")
                if len(parts) < 2:
                    print(yellow(f"Skipping invalid line {i}: {line.strip()}"))
                    continue
                login_info.append((parts[0].strip(), parts[1].strip()))

            return login_info
    except Exception as e:
        raise ValueError(f"❌ Failed to parse input file: {e}")


def parse_proxy(proxy_raw):
    if not proxy_raw:
        return None
    proxy_parts = proxy_raw.split("@")

    if len(proxy_parts) == 2:
        auth_part = proxy_parts[0]
        host_part = proxy_parts[1]

        if ":" in auth_part:
            username, password = auth_part.split(":", 1)
        else:
            username, password = auth_part, ""
    else:
        host_part = proxy_parts[0]
        username, password = "", ""

    if ":" in host_part:
        host, port = host_part.rsplit(":", 1)
        try:
            port = int(port)
        except ValueError:
            raise ValueError("❌ Invalid proxy port number")
    else:
        raise ValueError(
            "❌ Proxy must include port (format: host:port or user:pass@host:port)"
        )

    proxy_dict = {
        "host": host,
        "port": port,
    }

    if username:
        proxy_dict["username"] = username
    if password:
        proxy_dict["password"] = password

    return proxy_dict
