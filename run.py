#!/usr/bin/env python3
"""Start the app.

    python run.py

Then open http://127.0.0.1:5001 . To use it from a phone on the same wifi,
open http://<your-computer's-ip>:5001 instead.

Port 5001 rather than Flask's usual 5000 because macOS uses 5000 for AirPlay
Receiver. Environment variables you can set:

    PORT=8000          listen on a different port
    HOST=127.0.0.1     listen on this machine only, no phone access
    FLASK_DEBUG=1      turn the debugger on (see the warning below)

Debug mode is OFF by default, on purpose. Flask's debugger lets anyone who can
reach the app run arbitrary Python on this laptop through the browser, so it
must never be on while the app is reachable from the network. Turning it on
therefore also restricts the app to this machine unless you override HOST
yourself.
"""

import os

from app import create_app

app = create_app()


def _is_on(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = _is_on("FLASK_DEBUG")

    # With the debugger off, listening on every interface is how The Center Director
    # reaches this from her phone -- that is the whole point of the prototype.
    # With the debugger on, that same setting would hand a remote code
    # execution console to anyone on the wifi, so default to this machine only.
    # B104 is suppressed on the next line. Binding to every interface is
    # deliberate and is the whole point of the prototype -- The Center Director uses this
    # from her phone. It is only ever reached with the debugger off, and the
    # check below enforces that.
    default_host = "127.0.0.1" if debug else "0.0.0.0"  # nosec B104
    host = os.environ.get("HOST", default_host)

    if debug and host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "\n  REFUSING TO START.\n"
            "  FLASK_DEBUG is on and HOST is set to "
            f"'{host}', which would expose a remote code execution\n"
            "  console to everyone on this network. Use HOST=127.0.0.1, or "
            "turn debug off.\n"
        )
        raise SystemExit(1)

    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  Reachable from other devices on this network on port {port}.")

    app.run(host=host, port=port, debug=debug)
