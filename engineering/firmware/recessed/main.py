"""B3 Pico entry point with gain-5 readout and mandatory paired nail cells."""

import json
import magnetic_main

magnetic_main.PROTOCOL = "yam-b3/1"

if __name__ == "__main__":
    try:
        with open("config.json") as stream:
            config = json.load(stream)
        if config.get("nail_cells") is not True:
            raise ValueError("The complete B3 finger requires both N0 nail cells")
        magnetic_main.main()
    except (OSError, ValueError) as error:
        print(json.dumps({"type": "fatal", "protocol": "yam-b3/1", "reason": str(error)}))
