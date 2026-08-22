"""Verify that an OCA wheel contains code and metadata, but no local research data."""

from __future__ import annotations

import argparse
from email.parser import Parser
from pathlib import Path, PurePosixPath
from tarfile import open as open_tarfile
from zipfile import ZipFile

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

RAW_DATA_SUFFIXES = {'.csv', '.db', '.feather', '.parquet', '.pickle', '.pkl'}
REPOSITORY_ONLY_ROOTS = {'agents', 'examples', 'outputs', 'tests'}
PRIVATE_SOURCE_ROOTS = {'agents', 'data', 'outputs'}


def load_expected_project_metadata(repository_root: Path) -> tuple[str, str, set[str]]:
    with (repository_root / 'pyproject.toml').open('rb') as stream:
        project = tomllib.load(stream)['project']
    return project['version'], project['requires-python'], set(project['optional-dependencies'])


def verify_distribution(dist_dir: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    expected_version, expected_python, expected_extras = load_expected_project_metadata(repository_root)
    wheels = sorted(dist_dir.glob('*.whl'))
    source_distributions = sorted(dist_dir.glob('*.tar.gz'))
    if len(wheels) != 1 or len(source_distributions) != 1:
        raise AssertionError(
            f'expected one wheel and one source distribution, found {wheels=} and {source_distributions=}'
        )

    with ZipFile(wheels[0]) as archive:
        members = [PurePosixPath(name) for name in archive.namelist() if not name.endswith('/')]
        member_names = {str(member) for member in members}
        required_core_modules = {
            'option_chain_analytics/conventions.py',
            'option_chain_analytics/data/cache.py',
            'option_chain_analytics/data/cboe.py',
            'option_chain_analytics/data/deribit.py',
            'option_chain_analytics/data/loaders.py',
            'option_chain_analytics/data/tardis.py',
            'option_chain_analytics/option_data.py',
            'option_chain_analytics/reconstruction.py',
        }
        missing_core_modules = required_core_modules - member_names
        if missing_core_modules:
            raise AssertionError(f'wheel is missing public core modules: {missing_core_modules}')
        retired_modules = {
            'option_chain_analytics/chain_loader_from_ts.py',
            'option_chain_analytics/chain_ts.py',
            'option_chain_analytics/config.py',
            'option_chain_analytics/data/chain_loader_from_ts.py',
            'option_chain_analytics/data/chain_ts.py',
            'option_chain_analytics/data/config.py',
            'option_chain_analytics/ts_loaders.py',
        }
        packaged_retired_modules = retired_modules & member_names
        if packaged_retired_modules:
            raise AssertionError(f'wheel contains retired compatibility modules: {packaged_retired_modules}')
        packaged_ccxt_files = {name for name in member_names if 'ccxt' in name.lower()}
        if packaged_ccxt_files:
            raise AssertionError(f'wheel contains retired CCXT integration files: {packaged_ccxt_files}')
        if 'option_chain_analytics/data/simulated.py' not in member_names:
            raise AssertionError('wheel is missing deterministic simulated data support')
        if 'option_chain_analytics/data/thetadata.py' not in member_names:
            raise AssertionError('wheel is missing ThetaData EOD support')
        if 'option_chain_analytics/utils/forward_discount.py' not in member_names:
            raise AssertionError('wheel is missing provider-independent parity fitting')
        packaged_fitter_files = {
            name for name in member_names if name.startswith('option_chain_analytics/fitters/')
        }
        if packaged_fitter_files:
            raise AssertionError(f'wheel contains the retired fitters package: {packaged_fitter_files}')
        if 'option_chain_analytics/fitters/qp_price_fitter.py' in member_names:
            raise AssertionError('wheel contains the retired CVXPY quote fitter')
        if not any(str(member).endswith('.dist-info/METADATA') for member in members):
            raise AssertionError('wheel is missing METADATA')

        repository_only = [member for member in members if member.parts[0] in REPOSITORY_ONLY_ROOTS]
        raw_data = [member for member in members if member.suffix.lower() in RAW_DATA_SUFFIXES]
        development_runners = [
            member for member in members if 'run_local' in member.parts or member.name.endswith('_run.py')
        ]
        if repository_only or raw_data or development_runners:
            raise AssertionError(
                'wheel contains private/repository-only/development files: '
                f'{repository_only + raw_data + development_runners}'
            )

        metadata_name = next(str(member) for member in members if str(member).endswith('.dist-info/METADATA'))
        metadata = Parser().parsestr(archive.read(metadata_name).decode('utf-8'))
        if metadata['Name'].replace('_', '-').lower() != 'option-chain-analytics':
            raise AssertionError(f"unexpected distribution name: {metadata['Name']}")
        if metadata['Version'] != expected_version:
            raise AssertionError(f"unexpected development version: {metadata['Version']}")
        if metadata['Requires-Python'] != expected_python:
            raise AssertionError(f"unexpected Python requirement: {metadata['Requires-Python']}")
        if metadata['License-Expression'] != 'MIT':
            raise AssertionError(f"unexpected license expression: {metadata['License-Expression']}")
        extras = set(metadata.get_all('Provides-Extra', []))
        if extras != expected_extras:
            raise AssertionError(f'unexpected optional extras: {extras}')

    with open_tarfile(source_distributions[0], mode='r:gz') as archive:
        source_members = [PurePosixPath(member.name) for member in archive.getmembers() if member.isfile()]
        relative_members = [PurePosixPath(*member.parts[1:]) for member in source_members if len(member.parts) > 1]
        source_names = {str(member) for member in relative_members}
        development_runners = [
            member for member in relative_members
            if 'run_local' in member.parts or member.name.endswith('_run.py')
        ]
        if development_runners:
            raise AssertionError(f'source distribution contains development runners: {development_runners}')
        required_source_files = {
            'CHANGELOG.md',
            'CITATION.cff',
            'CODE_OF_CONDUCT.md',
            'CONTRIBUTING.md',
            'RELEASING.md',
            'SECURITY.md',
            'docs/index.md',
            'examples/README.md',
            'examples/build_thetadata_eod_cache.py',
            'examples/fetch_thetadata_eod.py',
            'examples/first_success.py',
            'tools/verify_distribution.py',
        }
        missing_source_files = required_source_files - source_names
        if missing_source_files:
            raise AssertionError(f'source distribution is missing public materials: {missing_source_files}')
        if 'examples/build_local_options_caches.py' in source_names:
            raise AssertionError('source distribution contains the private local-cache builder')
        private_source_files = [
            member for member in relative_members if member.parts and member.parts[0] in PRIVATE_SOURCE_ROOTS
        ]
        generated_docs = [
            member for member in relative_members if member.parts[:2] == ('docs', '_build')
        ]
        raw_source_data = [member for member in relative_members if member.suffix.lower() in RAW_DATA_SUFFIXES]
        if private_source_files or generated_docs or raw_source_data:
            raise AssertionError(
                'source distribution contains private/local/generated files: '
                f'{private_source_files + generated_docs + raw_source_data}'
            )

    print(f'verified wheel: {wheels[0].name}')
    print(f'verified source distribution: {source_distributions[0].name}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('dist_dir', nargs='?', type=Path, default=Path('dist'))
    args = parser.parse_args()
    verify_distribution(args.dist_dir)


if __name__ == '__main__':
    main()
