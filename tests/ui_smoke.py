"""Real-browser hit testing: a visible DOM node may still be hidden under map tiles."""
import argparse
import json
from pathlib import Path
import re
import sys
from playwright.sync_api import sync_playwright

VERSION = '20261004-ui2'
parser = argparse.ArgumentParser()
parser.add_argument('--url', required=True)
parser.add_argument('--out', default='checks/local')
parser.add_argument('--baseline')
args = parser.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
report = {'url': args.url, 'ui_version': VERSION, 'cases': [], 'errors': []}


def front(page, selector):
    return page.locator(selector).first.evaluate('''el => {
      const r=el.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2;
      const top=document.elementFromPoint(x,y);
      return {ok:!!top && (top===el || el.contains(top)), x, y,
              actual:top ? top.tagName+'.'+top.className : null};
    }''')


def require(condition, name):
    if not condition:
        raise AssertionError(name)


def open_page(context, url):
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
    require(response and response.status == 200, 'HTTP 200')
    page.wait_for_selector(f'html[data-ui-version="{VERSION}"]', timeout=20000)
    page.wait_for_function('document.querySelectorAll(".card").length > 0')
    page.wait_for_timeout(900)
    return page, errors


def exercise(browser, engine, width, height, full):
    mobile = width <= 760
    context = browser.new_context(viewport={'width': width, 'height': height},
                                  is_mobile=mobile, has_touch=mobile, locale='ja-JP')
    case = {'engine': engine, 'viewport': [width, height], 'passed': False}
    page = None
    try:
        page, errors = open_page(context, args.url)
        require(page.evaluate('typeof L !== "undefined" && !!map'), 'Real Leaflet map initialized')
        n = page.evaluate('places.length')
        require(page.locator('.card').count() == n, 'All records rendered')
        require(page.evaluate('markers.size') == n, 'Map and list have same records')
        for selector in ['#q', '.chip[data-f="all"]', '.card', '#sort']:
            result = front(page, selector)
            require(result['ok'], f'{selector} is covered: {result}')
        require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'No horizontal page overflow')
        case['place_count'] = n
        case['loaded_tiles'] = page.locator('.leaflet-tile-loaded').count()
        page.screenshot(path=str(out / f'{engine}-{width}x{height}.png'))
        page.locator('.card').first.click()
        require(page.locator('#detail').evaluate('el=>el.classList.contains("open")'), 'Details opened by real click')
        require(front(page, '#close')['ok'], 'Close control is not covered')
        page.screenshot(path=str(out / f'{engine}-{width}x{height}-detail.png'))
        page.locator('#close').click()
        require(not page.locator('#detail').evaluate('el=>el.classList.contains("open")'), 'Details closed')
        page.locator('#q').fill('五十沢')
        require(page.locator('.card').count() == 1, 'Search returns Ikarasawa')
        require(page.locator('.badge').first.evaluate('el=>el.classList.contains("blue")'), 'Research-only status retained')
        page.locator('#q').fill('')
        page.locator('[data-f="morel"]').click()
        require(page.locator('.card').count() == page.evaluate('places.filter(p=>p.tags.includes("morel")).length'), 'Morel filter')
        page.locator('[data-f="truffle"]').click()
        require(page.locator('.card').count() == page.evaluate('places.filter(p=>p.tags.includes("truffle")).length'), 'Truffle filter')
        page.locator('[data-f="collect"]').click()
        require(page.locator('.card[data-id="ikarasawa"]').count() == 0, 'Unconfirmed place excluded from collection filter')
        require(page.locator('.card .badge.blue,.card .badge.red').count() == 0, 'Collection filter honors statuses')
        page.locator('[data-f="all"]').click()
        if mobile:
            page.locator('#viewToggle').click()
            require(page.locator('.shell').evaluate('el=>el.classList.contains("list-expanded")'), 'Expand list')
            require(front(page, '#q')['ok'], 'Search remains usable in list view')
            page.locator('.card').last.scroll_into_view_if_needed()
            require(front(page, '.card:last-child')['ok'], 'Last card accessible by vertical scroll')
            page.screenshot(path=str(out / f'{engine}-{width}x{height}-list.png'))
            page.locator('#viewToggle').click()
            page.locator('.card').first.scroll_into_view_if_needed()
            require(not page.locator('.shell').evaluate('el=>el.classList.contains("list-expanded")'), 'Return to map')
            require(front(page, '#q')['ok'], 'Search remains in front after view change')
        page.locator('#q').fill('__no_place_ui_test__')
        require(page.locator('.card').count() == 0, 'Empty search')
        require(page.locator('.empty-state').is_visible(), 'Explicit empty state')
        page.locator('.empty-state button').click()
        require(page.locator('.card').count() == n, 'Reset filters')
        if full:
            page.locator('.fav').first.click()
            page.locator('[data-f="fav"]').click()
            require(page.locator('.card').count() == 1, 'Favorites filter')
            page.reload(wait_until='domcontentloaded')
            page.wait_for_selector(f'html[data-ui-version="{VERSION}"]')
            require(page.locator('.fav.on').count() == 1, 'Favorite persists across reload')
            page.evaluate('navigator.geolocation.getCurrentPosition = (ok,fail)=>fail({code:1})')
            page.locator('#locate').click()
            require('未許可' in page.locator('#ui-toast').inner_text(), 'Denied location handled without blocking UI')
            require(front(page, '#q')['ok'], 'Denied location does not cover search')
            page.evaluate('map.setZoom(9, {animate:false}); map.panBy([50,30], {animate:false})')
            require(front(page, '#q')['ok'], 'Map pan/zoom does not cover search')
        require(not errors, f'JavaScript errors: {errors}')
        case['javascript_errors'] = errors
        case['passed'] = True
    except Exception as error:
        case['error'] = str(error)
        if page:
            page.screenshot(path=str(out / f'{engine}-{width}x{height}-FAIL.png'))
        report['errors'].append(case['error'])
    finally:
        report['cases'].append(case)
        context.close()


with sync_playwright() as p:
    if args.baseline:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)
        page = context.new_page()
        vendor = Path('dist/assets/vendor')
        page.route(re.compile(r'https://unpkg.com/leaflet@1.9.4/dist/leaflet\.(js|css)'),
                   lambda route: route.fulfill(path=str(vendor / route.request.url.rsplit('/',1)[-1])))
        page.goto(args.baseline, wait_until='domcontentloaded')
        page.wait_for_timeout(900)
        report['baseline_search_hit_test'] = front(page, '#q')
        page.screenshot(path=str(out / 'before-mobile.png'))
        browser.close()
    for engine, sizes in [('chromium', [(390,844),(320,568),(430,932),(1440,900),(844,390),(390,450)]),
                          ('webkit', [(390,844),(320,568)])]:
        browser = getattr(p, engine).launch()
        for width, height in sizes:
            exercise(browser, engine, width, height, width == 390 and height == 844)
        if engine == 'chromium':
            context = browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)
            context.route('**/assets/vendor/leaflet.js', lambda route: route.abort())
            page, errors = open_page(context, args.url)
            try:
                require(front(page, '#q')['ok'], 'Search survives map library failure')
                require(page.locator('.fmark').count() == 0, 'No fictional map when library fails')
                require('地図を読み込めません' in page.locator('#map-status').inner_text(), 'Map error is explained')
                page.locator('.card').first.click()
                require(page.locator('#detail').evaluate('el=>el.classList.contains("open")'), 'Details survive map failure')
                require(not errors, f'Fallback JavaScript errors: {errors}')
                page.screenshot(path=str(out / 'offline-library-fallback.png'))
                report['cases'].append({'engine':'chromium','case':'map-library-unavailable','passed':True})
            except Exception as error:
                report['errors'].append(str(error))
            context.close()
        browser.close()
report['passed'] = not report['errors']
(out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(0 if report['passed'] else 1)
