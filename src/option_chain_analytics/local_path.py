"""Central local-drive paths for private data and generated OCA output.

``OCA_DATA_PATH`` and ``OCA_OUTPUT_PATH`` may override the source-checkout
defaults. Returned strings are absolute and include a trailing platform
separator so provider subdirectories can follow the established QIS-style
``f"{lp.get_resource_path()}provider\\"`` convention.
"""

import os
from pathlib import Path
from typing import Dict


def _find_repository_root() -> Path:
    """Return the nearest ancestor containing ``pyproject.toml``."""
    for parent in Path(__file__).resolve().parents:
        if parent.joinpath('pyproject.toml').is_file():
            return parent
    return Path.cwd()


def _get_directory(env_var: str, directory_name: str) -> str:
    """Resolve one configured/default directory with a trailing separator."""
    path = Path(os.environ.get(env_var, _find_repository_root().joinpath(directory_name)))
    return f"{path.resolve()}{os.sep}"


def get_paths() -> Dict[str, str]:
    """Return repository-local data and output paths.

    ``OCA_DATA_PATH`` and ``OCA_OUTPUT_PATH`` override the defaults. This
    keeps private datasets and generated output outside the installed package.
    """
    data_path = get_resource_path()
    return {
        'RESOURCE_PATH': data_path,
        'LOCAL_RESOURCE_PATH': data_path,
        'UNIVERSE_PATH': data_path,
        'OUTPUT_PATH': get_output_path(),
    }


def get_resource_path() -> str:
    """Return ``OCA_DATA_PATH`` or the repository's ignored ``data/`` path."""
    return _get_directory(env_var='OCA_DATA_PATH', directory_name='data')


def get_local_resource_path() -> str:
    """Compatibility alias for :func:`get_resource_path`."""
    return get_resource_path()


def get_output_path() -> str:
    """Return ``OCA_OUTPUT_PATH`` or the repository's ignored ``outputs/`` path."""
    return _get_directory(env_var='OCA_OUTPUT_PATH', directory_name='outputs')
