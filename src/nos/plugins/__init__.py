"""
Bundled workflow / node / link plugins (reference implementations).

Module paths use the prefix ``nos.plugins`` (e.g. ``nos.plugins.nodes.web_scraper.base_requests``).

The :mod:`nos.platform.plugins` package contains the Flask startup plugin loader (entry points,
``plugins`` DB bind on a separate database file, registry bridge). Engine implementations stay under
``nodes/``, ``workflows/``, etc.
"""
