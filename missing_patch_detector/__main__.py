"""Entry point for ``python -m missing_patch_detector``.

Configures the root logger so that INFO-level messages written by the package
modules are visible when the tool is run from the command line.
"""

from __future__ import annotations

import logging


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info(
        "Missing Patch Detector is ready. "
        "Import MissingPatchPipeline and call run() or run_for_cve() to start scanning."
    )


if __name__ == "__main__":
    main()
