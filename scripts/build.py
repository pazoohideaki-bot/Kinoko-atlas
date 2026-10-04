"""Build the published UI; preserve place data and verify Leaflet's official SRI."""
from pathlib import Path
import base64
import hashlib
import json
import re
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'dist'
VERSION = '20261004-ui2'
HASHES = {
    'leaflet.js': '20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=',
    'leaflet.css': 'p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=',
}


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


def build() -> None:
    OUT.mkdir(exist_ok=True)
    shutil.copytree(ROOT / 'assets', OUT / 'assets', dirs_exist_ok=True)
    if (ROOT / 'data').exists():
        shutil.copytree(ROOT / 'data', OUT / 'data', dirs_exist_ok=True)
    vendor = OUT / 'assets' / 'vendor'
    vendor.mkdir(exist_ok=True)
    for name in HASHES:
        vendor_asset(name, vendor / name)
    source = (ROOT / 'index.html').read_text(encoding='utf-8')
    records = re.search(r'const places=(\[.*?\]);\s*const C=', source, re.S)
    if not records:
        raise ValueError('Place data not found; refuse to publish an empty map')
    places = json.loads(records.group(1))
    if not places or len({p['id'] for p in places}) != len(places):
        raise ValueError('Missing or duplicate place records')
    source = source.replace('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css', 'assets/vendor/leaflet.css')
    source = source.replace('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', 'assets/vendor/leaflet.js')
    source = source.replace('<link rel="preconnect" href="https://unpkg.com">', '')
    source = source.replace('</head>', f'<meta name="kinoko-ui-build" content="{VERSION}"><link rel="stylesheet" href="assets/interface-v2.css?v={VERSION}"></head>')
    source = source.replace('</body>', f'<script src="assets/interface-v2.js?v={VERSION}"></script><noscript>検索と地点一覧にはJavaScriptが必要です。</noscript></body>')
    assert re.search(r'const places=(\[.*?\]);\s*const C=', source, re.S).group(1) == records.group(1)
    (OUT / 'index.html').write_text(source, encoding='utf-8')
    (OUT / '.nojekyll').touch()
    (OUT / 'build.json').write_text(json.dumps({'ui_version': VERSION, 'place_count': len(places), 'data_changed': False}), encoding='utf-8')
    print(f'Built {VERSION}; {len(places)} place records preserved unchanged')


if __name__ == '__main__':
    build()
