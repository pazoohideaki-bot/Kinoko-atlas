"""Build the verified UI and merge reviewed, append-only occurrence catalogs."""
from pathlib import Path
import base64
import hashlib
import json
import math
import re
import shutil
import urllib.request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'dist'
VERSION = '20261004-ui2'
HASHES = {
    'leaflet.js': '20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=',
    'leaflet.css': 'p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=',
}
PATTERN = re.compile(r'const places=(\[.*?\]);\s*const C=', re.S)


def vendor_asset(name: str, target: Path) -> None:
    if target.exists():
        data = target.read_bytes()
        if base64.b64encode(hashlib.sha256(data).digest()).decode() == HASHES[name]:
            return
    urls = [f'https://unpkg.com/leaflet@1.9.4/dist/{name}',
            f'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/{name}']
    failures = []
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=40) as response:
                data = response.read()
            digest = base64.b64encode(hashlib.sha256(data).digest()).decode()
            if digest != HASHES[name]:
                raise ValueError(f'SRI mismatch for {name}')
            target.write_bytes(data)
            return
        except Exception as exc:
            failures.append(f'{url}: {exc}')
    raise RuntimeError('Cannot obtain verified Leaflet: ' + '; '.join(failures))


def validate_place(place: dict) -> None:
    for key in ('id', 'name', 'pref', 'statusLabel', 'precision', 'fee', 'legal', 'note'):
        if not isinstance(place.get(key), str) or not place[key].strip():
            raise ValueError(f'Missing text field {key}')
    if not re.fullmatch(r'[a-z0-9_\-]+', place['id']):
        raise ValueError('Unsafe place id')
    if place.get('status') not in ('green', 'yellow', 'blue', 'red'):
        raise ValueError('Invalid collection category')
    for key, limit in (('lat', 90), ('lng', 180)):
        value = place.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > limit:
            raise ValueError(f'Invalid {key}')
    if not isinstance(place.get('score'), (int, float)) or not 0 <= place['score'] <= 100:
        raise ValueError('Invalid display ordering')
    for key in ('fungi', 'tags', 'months', 'sources'):
        if not isinstance(place.get(key), list) or not place[key]:
            raise ValueError(f'Missing list {key}')
    if any(not isinstance(m, int) or not 1 <= m <= 12 for m in place['months']):
        raise ValueError('Invalid observation month')
    if any(not isinstance(v, str) or not v for v in place['fungi'] + place['tags']):
        raise ValueError('Invalid taxon or tag')
    for source in place['sources']:
        if not isinstance(source, list) or len(source) != 2 or not source[0]:
            raise ValueError('Invalid source')
        parsed = urlparse(source[1])
        if parsed.scheme != 'https' or not parsed.netloc:
            raise ValueError('Sources must use HTTPS')
    if place.get('radiation', {}).get('collection_and_consumption_advisory') and place['status'] in ('green', 'yellow'):
        raise ValueError('Do not promote an advisory area as a collection destination')
    if not place.get('record_dates') or not place.get('coordinate_role'):
        raise ValueError('New records need dates and coordinate precision')


def reviewed_additions(base: list) -> tuple[list, list, str]:
    result = list(base)
    ids = {p['id'] for p in base}
    files = []
    reviewed_at = '2026-10-04'
    for path in sorted((ROOT / 'data' / 'catalog').glob('*.json')):
        catalog = json.loads(path.read_text(encoding='utf-8'))
        if catalog.get('schema_version') != 1 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', catalog.get('reviewed_at', '')):
            raise ValueError(f'Invalid catalog metadata: {path.name}')
        for place in catalog.get('places', []):
            validate_place(place)
            if place['id'] in ids:
                raise ValueError(f'Duplicate id; update its canonical source instead: {place["id"]}')
            ids.add(place['id'])
            result.append(place)
        reviewed_at = max(reviewed_at, catalog['reviewed_at'])
        files.append(str(path.relative_to(ROOT)))
    return result, files, reviewed_at


def build() -> None:
    source = (ROOT / 'index.html').read_text(encoding='utf-8')
    records = PATTERN.search(source)
    if not records:
        raise ValueError('Place data not found; refuse to publish an empty map')
    base = json.loads(records.group(1))
    if not base or len({p['id'] for p in base}) != len(base):
        raise ValueError('Missing or duplicate base place records')
    places, catalogs, data_version = reviewed_additions(base)
    payload = json.dumps(places, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    source = source[:records.start(1)] + payload + source[records.end(1):]
    if json.loads(PATTERN.search(source).group(1))[:len(base)] != base:
        raise ValueError('Base records were unexpectedly altered')
    OUT.mkdir(exist_ok=True)
    shutil.copytree(ROOT / 'assets', OUT / 'assets', dirs_exist_ok=True)
    if (ROOT / 'data').exists():
        shutil.copytree(ROOT / 'data', OUT / 'data', dirs_exist_ok=True)
    vendor = OUT / 'assets' / 'vendor'
    vendor.mkdir(exist_ok=True)
    for name in HASHES:
        vendor_asset(name, vendor / name)
    source = source.replace('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css', 'assets/vendor/leaflet.css')
    source = source.replace('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', 'assets/vendor/leaflet.js')
    source = source.replace('<link rel="preconnect" href="https://unpkg.com">', '')
    source = re.sub(r'LIVE MAP · \d{4}-\d{2}-\d{2}', f'DATA · {data_version}', source)
    source = source.replace('</head>', f'<meta name="kinoko-ui-build" content="{VERSION}"><meta name="kinoko-data-build" content="{data_version}"><link rel="stylesheet" href="assets/interface-v2.css?v={VERSION}"></head>')
    source = source.replace('</body>', f'<script src="assets/interface-v2.js?v={VERSION}"></script><noscript>検索と地点一覧にはJavaScriptが必要です。</noscript></body>')
    if json.loads(PATTERN.search(source).group(1)) != places:
        raise ValueError('Published records differ from the reviewed catalog')
    (OUT / 'index.html').write_text(source, encoding='utf-8')
    (OUT / '.nojekyll').touch()
    (OUT / 'data' / 'places.json').write_text(json.dumps(places, ensure_ascii=False, indent=2), encoding='utf-8')
    metadata = {'ui_version': VERSION, 'data_version': data_version, 'place_count': len(places),
                'base_place_count': len(base), 'added_record_count': len(places) - len(base),
                'base_records_preserved': True, 'catalog_files': catalogs,
                'records_sha256': hashlib.sha256(payload.encode()).hexdigest()}
    (OUT / 'build.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    build()
