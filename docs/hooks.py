"""MkDocs hooks: the documentation of Pubgrade-Sidecar as a section of the site.

Pubgrade-Sidecar keeps its documentation in its own repository (`docs/`, with
its own `mkdocs.yml` and a strict build in its CI). This site includes it as
the section "Pubgrade-Sidecar", from the Git submodule
`external/pubgrade-sidecar`, pinned to a commit of the Sidecar's branch `dev`
(Dependabot proposes updates monthly; see "Documentation" in
`docs/development.md`):

- The Sidecar's pages are added under `sidecar/` (the Sidecar's own links and
  `site_url` point there), in the order of the `nav` of its `mkdocs.yml`, as
  the last section of this site's navigation.
- Its pages must be self-contained: snippets (`pymdownx.snippets`) would be
  read from this repository, not the Sidecar's, so the build fails on any.

Its code reference (mkdocstrings) finds the Sidecar's package through the
`paths` of the Python handler in `mkdocs.yml`.
"""

from pathlib import Path
import re
from typing import Any

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.exceptions import PluginError
from mkdocs.structure.files import File, Files
from mkdocs.structure.pages import Page
from mkdocs.utils.yaml import yaml_load

# The submodule with the Sidecar's repository
SIDECAR = Path("external/pubgrade-sidecar")
# Directory of the Sidecar's pages in this site
PREFIX = "sidecar/"
# Title of the Sidecar's section in the navigation
SECTION = "Pubgrade-Sidecar"
# Markers of `pymdownx.snippets` in any of its forms (e.g. `--8<-- "file"`,
# `-8<- 'file'`, or a block of file names between two markers)
SNIPPET = re.compile(r"^\s*-+8<-+", re.MULTILINE)

NavItem = str | dict[str, Any]


def _docs_dir() -> Path:
    """Return the Sidecar's docs directory, checking that it is checked out.

    Returns:
        Path of the Sidecar's `docs/` directory.

    Raises:
        PluginError: If the submodule isn't checked out.
    """
    docs = SIDECAR / "docs"
    if not (SIDECAR / "mkdocs.yml").is_file() or not docs.is_dir():
        raise PluginError(
            f"{SIDECAR} is missing: check out the submodule with "
            "`git submodule update --init`"
        )
    return docs


def _prefix(item: NavItem) -> NavItem:
    """Move an entry of the Sidecar's navigation under `sidecar/`.

    Args:
        item: Entry of the `nav` of the Sidecar's `mkdocs.yml`: a page path,
            or a mapping of a title to a page path, a URL or a list of
            entries.

    Returns:
        The entry with its page paths prefixed; URLs are left as they are.
    """
    if isinstance(item, str):
        return item if "://" in item else PREFIX + item
    return {
        title: [_prefix(child) for child in value]
        if isinstance(value, list)
        else _prefix(value)
        for title, value in item.items()
    }


def on_config(config: MkDocsConfig) -> MkDocsConfig:
    """Add the Sidecar's pages to the navigation, as the last section.

    Args:
        config: The site's configuration.

    Returns:
        The configuration, with the section added.

    Raises:
        PluginError: If the submodule isn't checked out, or the Sidecar's
            `mkdocs.yml` has no `nav`.
    """
    _docs_dir()
    with open(SIDECAR / "mkdocs.yml", encoding="utf-8") as stream:
        sidecar_config = yaml_load(stream)
    nav: list[NavItem] | None = sidecar_config.get("nav")
    if not nav:
        raise PluginError(f"{SIDECAR}/mkdocs.yml has no `nav`")
    config.nav = list(config.nav or []) + [{SECTION: [_prefix(i) for i in nav]}]
    return config


def on_files(files: Files, config: MkDocsConfig) -> Files:
    """Add the Sidecar's pages and other files of its `docs/` under `sidecar/`.

    Args:
        files: The site's files.
        config: The site's configuration.

    Returns:
        The files, with the Sidecar's added.
    """
    docs = _docs_dir()
    for path in sorted(docs.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files.append(
                File.generated(
                    config,
                    PREFIX + path.relative_to(docs).as_posix(),
                    abs_src_path=str(path.resolve()),
                )
            )
    return files


def on_page_markdown(
    markdown: str, page: Page, config: MkDocsConfig, files: Files
) -> str:
    """Fail on snippets in the Sidecar's pages, which would resolve here.

    Args:
        markdown: The page's Markdown.
        page: The page.
        config: The site's configuration.
        files: The site's files.

    Returns:
        The Markdown, unchanged.

    Raises:
        PluginError: If a page of the Sidecar includes snippets.
    """
    if page.file.src_uri.startswith(PREFIX) and SNIPPET.search(markdown):
        raise PluginError(
            f"{page.file.src_uri}: snippets are not supported in the pages of "
            "Pubgrade-Sidecar, as they would be read from this repository"
        )
    return markdown
