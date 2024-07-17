"""Helper script to sort prefixes in task custom:sort_prefixes"""

from json import dump, load
from pathlib import Path

file_path = Path("cmem_plugin_shapes") / "prefix.cc.json"

with file_path.open("r") as json_file:
    json_data = load(json_file)

with file_path.open("w") as json_file:
    dump(json_data, json_file, sort_keys=True, indent=2)
