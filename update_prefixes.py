"""Helper script to sort prefixes in task custom:update_prefixes"""

from json import dump, loads
from pathlib import Path
from urllib.request import urlopen

with urlopen("http://prefix.cc/popular/all.file.json") as f:
    json_data = loads(f.read().decode("utf-8"))

with (Path("cmem_plugin_shapes") / "prefix.cc.json").open("w") as json_file:
    dump(json_data, json_file, sort_keys=True, indent=2)
