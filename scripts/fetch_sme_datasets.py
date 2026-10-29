"""Acquire public SME research data/documents without executing publisher code.

Raw downloads stay in ignored .local/datasets. This never trains or replaces the
serving model. Source URLs were inspected on publisher pages on 2026-10-28.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
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
    with urlopen(request, timeout=20) as response:
        parts, total = [], 0
        while chunk := response.read1(262144):
            parts.append(chunk)
            total += len(chunk)
            if total > 50_000_000 or time.monotonic() - started > 120:
                raise ValueError('Download exceeded the size or time limit')
        data = b''.join(parts)
        final_url = response.url
    if len(data) > 50_000_000:
        raise ValueError('Download exceeded the 50 MB research-file limit')
    if source['file'].endswith(('.zip', '.xlsx')) and not data.startswith(b'PK'):
        raise ValueError('Expected a ZIP-format data archive, not a webpage')
    if source['file'].endswith('.json'):
        json.loads(data)
    if source.get('publisher_md5'):
        if hashlib.md5(data, usedforsecurity=False).hexdigest() != source['publisher_md5']:
            raise ValueError('Downloaded archive differs from publisher checksum')
    path = DESTINATION / source['file']
    path.write_bytes(data)
    return {**source, 'downloaded_at': datetime.now(timezone.utc).isoformat(),
            'final_url': final_url, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


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
        if cached and path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == cached['sha256']:
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
