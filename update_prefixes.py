"""Helper script to sort prefixes in task custom:update_prefixes"""

from json import dump, loads
from pathlib import Path
from urllib.request import urlopen

with urlopen("http://prefix.cc/popular/all.file.json") as remote_file:
    json_data = loads(remote_file.read())

with (Path("cmem_plugin_shapes") / "prefix.cc.json").open("w") as local_file:
    dump(json_data, local_file, sort_keys=True, indent=2)
