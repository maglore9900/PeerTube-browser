#!/bin/sh
# Install and enable the claude_subscription plugin in the pixi project you run this from.
#
# Two steps, both DELEGATED. `un plugins enable` already performs the targeted
# .un/config.toml line edit that preserves the file's comments, and `pixi add` already
# knows whether the dependency is present - so reimplementing either here would be a
# second, worse copy of something that works.
#
# Order matters and the abort is the point: enabling a plugin that is not installed writes
# a name into .un/config.toml that reaches nothing, and un then refuses to start. A failed
# install must not become a broken project.
#
# Usage, from the root of the project that should get the plugin:
#
#     sh /path/to/claude_subscription/install.sh
#
# Afterwards: add a [providers.<name>] entry with adaptor = "claude-code", then `un login`.
# See README.md.

set -eu

PLUGIN="claude_subscription"
# The DISTRIBUTION name from pyproject.toml, which is not the plugin name: `pixi add`
# needs `<name> @ <url>` for a local path and refuses a bare directory with "URL
# requirement must be preceded by a package name".
DIST="un-claude-subscription"
# The directory this script lives in, so the plugin is installed from its own source tree
# rather than from wherever the operator happened to be standing. Absolute, because
# `file://` + a relative path is not a URL pixi can resolve.
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# `-e` already aborts on a non-zero exit; this says why, because "pixi add failed" is a
# sentence and a bare non-zero exit is not.
if ! pixi add --pypi "$DIST @ file://$SOURCE"; then
    echo "install failed: pixi could not add the plugin from $SOURCE" >&2
    echo "nothing was enabled, so this project is unchanged" >&2
    exit 1
fi

# Through `pixi run`, not bare `un`. The console script is installed INTO the project's
# pixi environment, so it is on PATH only inside `pixi shell` or `pixi run` - and this
# script is normally invoked from a plain shell, where a bare `un` is "command not found"
# AFTER the dependency was already added. `pixi run` works either way.
pixi run un plugins enable "$PLUGIN"
echo "You need to set adaptor to claude-code to use this plugin"
