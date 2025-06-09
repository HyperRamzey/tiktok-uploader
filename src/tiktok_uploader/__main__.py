"""TikTok Uploader entry point script"""

import sys
import os

try:
    from tiktok_uploader import cli, __version__
except ImportError as e:
    print(f"❌ Failed to import TikTok Uploader: {e}")
    print("Please ensure the package is properly installed.")
    sys.exit(1)


def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] in ["--version", "-V"]:
            print(f"TikTok Uploader v{__version__}")
            sys.exit(0)

        if len(sys.argv) > 1 and sys.argv[1] == "auth":
            sys.argv.pop(1)
            cli.auth()
        else:
            cli.main()

    except KeyboardInterrupt:
        print("\n⚠️ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
