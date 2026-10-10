"""B2 Pico entry point; shared B1 acquisition is packaged as magnetic_main.py."""

import json
import magnetic_main

magnetic_main.PROTOCOL = "yam-b2/1"

if __name__ == "__main__":
    try:
        magnetic_main.main()
    except (OSError, ValueError) as error:
        print(json.dumps({"type":"fatal","protocol":"yam-b2/1","reason":str(error)}))
