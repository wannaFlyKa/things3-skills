# Vendored: things.py 1.0.1

`things/` is [things.py](https://github.com/thingsapi/things.py) 1.0.1 (Apache-2.0, see
`LICENSE-things.py`), copied unmodified from the PyPI sdist so that the plugin works without any
`pip install`. `things_lib/read.py` puts this directory at the front of `sys.path` before it imports
`things`, so the bundled copy always wins over a system-installed one. To refresh it: download the
`things.py` sdist from PyPI, copy `things/__init__.py`, `things/api.py` and `things/database.py`
(not `conftest.py`) over the files in `things/`, and copy the sdist `LICENSE` to `LICENSE-things.py`.
