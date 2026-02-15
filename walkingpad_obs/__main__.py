"""Entry point for python -m walkingpad_obs."""

import sys

if __name__ == "__main__":
    # If --mac is given, run headless server mode
    if "--mac" in sys.argv:
        from .server import main
        main()
    else:
        # Default: launch GUI
        from .gui import main
        main()
