"""Plugin manifests: one version source, and the marketplace entry points at the plugin (finding 1020).

Claude Code reads `version` from plugins/things/.claude-plugin/plugin.json and silently ignores a `version`
in the marketplace entry, so a second copy there can only drift. The CLI's `--version` string and the README
carry the same number; this pins all of them to things_lib.__version__.
"""

import json
import os
import re

from conftest import ROOT
from things_lib import __version__

MARKETPLACE = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
PLUGIN = os.path.join(ROOT, "plugins", "things", ".claude-plugin", "plugin.json")
README = os.path.join(ROOT, "README.md")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_plugin_json_version_is_the_library_version():
    plugin = load(PLUGIN)
    assert plugin["name"] == "things"
    assert plugin["version"] == __version__
    assert plugin["license"] == "MIT"


def test_marketplace_names_the_plugin_and_carries_no_second_version():
    marketplace = load(MARKETPLACE)
    assert marketplace["name"] == "things3-skills"
    entries = marketplace["plugins"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["name"] == "things"
    assert entry["source"] == "./plugins/things"
    assert "version" not in entry, "plugin.json is the single source of the version"
    assert os.path.isfile(os.path.join(ROOT, ".claude-plugin", "..", entry["source"], ".claude-plugin", "plugin.json"))


def test_readme_and_changelog_name_the_same_version():
    with open(README, encoding="utf-8") as handle:
        readme = handle.read()
    assert "things-skills %s" % __version__ in readme
    with open(CHANGELOG, encoding="utf-8") as handle:
        changelog = handle.read()
    assert re.search(r"^## \[%s\]" % re.escape(__version__), changelog, re.MULTILINE), "CHANGELOG lacks the release heading"
