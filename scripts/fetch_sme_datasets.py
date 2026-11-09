"""Acquire public SME research data/documents without executing publisher code.

Raw downloads stay in ignored .local/datasets. This never trains or replaces the
serving model. Use --sources to select a specific publisher release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / '.local' / 'datasets' / 'sme-field-research'
SOURCES = {
    'bangladesh': {
        'url': 'https://zenodo.org/records/20560302/files/shoumyac/bd-sme-research-v2.0.zip?download=1',
        'file': 'bangladesh-sme-v2.zip', 'page': 'https://zenodo.org/records/20560302',
        'license': 'Data CC BY 4.0; code MIT',
        'publisher_md5': 'ea158739d1096731ff0df8954c34e076',
    },
    'polish': {
        'url': 'https://archive.ics.uci.edu/static/public/365/polish%2Bcompanies%2Bbankruptcy%2Bdata.zip',
        'file': 'polish-company-bankruptcy.zip',
        'page': 'https://archive.ics.uci.edu/dataset/365/polish+companies+bankruptcy+data',
        'license': 'CC BY 4.0',
    },
    'sba_dictionary': {
        'url': 'https://data.sba.gov/sites/default/files/uploaded_resources/7a_504_foia_data_dictionary.xlsx',
        'file': 'sba-foia-dictionary.xlsx', 'page': 'https://data.sba.gov/dataset/7a-504-foia',
        'license': 'U.S. Government Works',
    },
    'sba_loans': {
        'url': 'https://raw.githubusercontent.com/stelladeecoder/sba_dataset/30555800a5cc1e37f02d7684c7dbd4796c87812d/SBAcase.11.13.17.csv',
        'file': 'sba-case.csv',
        'page': 'https://doi.org/10.1080/10691898.2018.1434342',
        'license': 'Public SBA records in Li, Mickel and Taylor (2018) teaching supplement',
        'expected_sha256': '3fc1a6519ae8450cbf6721c9f37797224d77c755b5b52baf58ee046478f8932b',
    },
    'retail_orders': {
        # The full workbook timed out. This pinned extract supports a method
        # check on one partial day, with no claim of full-month coverage.
        'url': 'https://raw.githubusercontent.com/rwh950/xiaoshan/c0716210a0ba1114a028b0afa55194fe1cc50b1c/week03_ecommerce/data/sample/online_retail_sample.csv',
        'file': 'retail-sample.csv',
        'page': 'https://archive.ics.uci.edu/dataset/352/online+retail',
        'license': 'CC BY 4.0 (Daqing Chen, 2015)',
        'expected_sha256': '4701bec69b5773dd1377623223bdd43253d91c3ee695a128b2177cb215709115',
    },
    'ssbf': {
        'url': 'https://www.federalreserve.gov/PUBS/oss/oss3/ssbf03/ssbf03.dat.Z',
        'file': 'ssbf03.dat.Z',
        'page': 'https://www.federalreserve.gov/PUBS/oss/oss3/ssbf03/ssbf03home.html',
        'license': 'Federal Reserve public-use survey data',
    },
    'ssbf_layout': {
        'url': 'https://www.federalreserve.gov/PUBS/oss/oss3/ssbf03/ascii_instruct03.txt',
        'file': 'ssbf03-layout.txt',
        'page': 'https://www.federalreserve.gov/PUBS/oss/oss3/ssbf03/ssbf03home.html',
        'license': 'Federal Reserve public-use survey documentation',
    },
    'pakistan_metadata': {
        'url': 'https://microdata.worldbank.org/metadata/export/6461/json',
        'file': 'pakistan-wbes-2022-metadata.json',
        'page': 'https://microdata.worldbank.org/catalog/6461',
        'license': 'Survey microdata terms are external; metadata is not the microdata',
    },
}


def acquire(name: str) -> dict:
    source = SOURCES[name]
    request = Request(source['url'], headers={'User-Agent': 'ForiFlow dataset provenance research'})
    started = time.monotonic()
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False) if source.get('publisher_md5') else None
    total = 0
    temporary = NamedTemporaryFile(dir=DESTINATION, suffix='.download', delete=False)
    path = Path(temporary.name)
    try:
        with temporary, urlopen(request, timeout=60) as response:
            final_url = response.url
            declared_bytes = response.headers.get('Content-Length')
            while chunk := response.read1(262144):
                total += len(chunk)
                if total > 50_000_000 or time.monotonic() - started > 240:
                    raise ValueError('Download exceeded the size or time limit')
                sha256.update(chunk)
                if md5 is not None:
                    md5.update(chunk)
                temporary.write(chunk)
        if declared_bytes is not None and total != int(declared_bytes):
            raise ValueError('Downloaded byte count differs from the source release')
        if 'expected_sha256' in source and sha256.hexdigest() != source['expected_sha256']:
            raise ValueError('Downloaded file differs from the pinned fingerprint')
        with path.open('rb') as stream:
            header = stream.readline(65536)
        if source['file'].endswith(('.zip', '.xlsx')) and not header.startswith(b'PK'):
            raise ValueError('Expected a ZIP-format data archive, not a webpage')
        if source['file'].endswith('.json'):
            json.loads(path.read_bytes())
        if name == 'sba_loans' and not all(
            column in header for column in (b'DisbursementDate', b'Term', b'Default')
        ):
            raise ValueError('Expected the SBA loan CSV header')
        if name == 'ssbf' and not header.startswith(b'\x1f\x9d'):
            raise ValueError('Expected a Unix compress data file')
        if name == 'ssbf_layout' and b'A0_IMPLICAT' not in path.read_bytes().upper():
            raise ValueError('Expected the Federal Reserve survey layout')
        if md5 is not None and md5.hexdigest() != source['publisher_md5']:
            raise ValueError('Downloaded archive differs from publisher checksum')
        path.replace(DESTINATION / source['file'])
    finally:
        path.unlink(missing_ok=True)
    return {**source, 'downloaded_at': datetime.now(timezone.utc).isoformat(),
            'final_url': final_url, 'bytes': total, 'sha256': sha256.hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', nargs='+', choices=list(SOURCES), default=list(SOURCES))
    args = parser.parse_args()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    manifest_path = DESTINATION / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    failures = []
    pending = []
    for name in args.sources:
        cached = manifest.get(name)
        path = DESTINATION / SOURCES[name]['file']
        cached_sha256 = None
        if cached and path.is_file():
            with path.open('rb') as stream:
                cached_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        expected = SOURCES[name].get('expected_sha256')
        if cached and cached_sha256 == cached['sha256'] and (expected is None or expected == cached_sha256):
            print(json.dumps({'source': name, 'verified_cache': True}), flush=True)
        else:
            pending.append(name)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(acquire, name): name for name in pending}
        for future in as_completed(futures):
            name = futures[future]
            try:
                manifest[name] = future.result()
                print(json.dumps({'source': name, 'bytes': manifest[name]['bytes'], 'sha256': manifest[name]['sha256']}), flush=True)
            except Exception as error:
                failures.append(name)
                print(json.dumps({'source': name, 'error': str(error)}), flush=True)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    if failures:
        raise SystemExit('Could not acquire: ' + ', '.join(failures))


if __name__ == '__main__':
    main()
