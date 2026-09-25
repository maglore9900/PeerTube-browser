"""The plugins this project ships.

A package, not a category the loader knows about: discovery is entry points, and
what makes these stock is that they are declared in the `un.plugins.stock` group,
which only this project's pyproject.toml can write to. The directory exists so the
module paths match the group - moving a file here changes no behaviour on its own,
and re-pointing its entry-point line is what does.

Anyone else's plugins declare `un.plugins` and live in their own distribution.
"""
