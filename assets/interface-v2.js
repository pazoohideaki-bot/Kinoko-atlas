/* UI-only repair: leave the independently reviewed place records unchanged. */
(() => {
  'use strict';
  const root = document.documentElement;
  const shell = document.querySelector('.shell');
  const panel = document.querySelector('.panel');
  const mobile = window.matchMedia('(max-width:760px)');
  root.dataset.uiVersion = '20261004-ui2';
  const notice = document.createElement('div');
  notice.id = 'map-status';
  notice.setAttribute('role', 'status');
  shell.appendChild(notice);
  const toast = document.createElement('div');
  toast.id = 'ui-toast';
  toast.setAttribute('role', 'status');
  document.body.appendChild(toast);
  let toastTimer;
  function message(text) {
    toast.textContent = text;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.textContent = ''; }, 4500);
  }
  const toggle = document.createElement('button');
  toggle.id = 'viewToggle';
  toggle.type = 'button';
  toggle.textContent = '一覧を広く';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.setAttribute('aria-controls', 'list');
  document.querySelector('.rowbar').insertBefore(toggle, document.querySelector('#sort'));
  toggle.addEventListener('click', () => {
    const expanded = shell.classList.toggle('list-expanded');
    toggle.textContent = expanded ? '地図に戻る' : '一覧を広く';
    toggle.setAttribute('aria-expanded', String(expanded));
    scheduleLayout();
  });
  let layoutFrame = 0;
  function updateLayout() {
    layoutFrame = 0;
    const vv = window.visualViewport;
    const height = vv && vv.scale === 1 ? vv.height : window.innerHeight;
    root.style.setProperty('--app-height', `${Math.max(240, Math.round(height))}px`);
    if (!mobile.matches) {
      shell.classList.remove('list-expanded');
      toggle.textContent = '一覧を広く';
      toggle.setAttribute('aria-expanded', 'false');
    }
    if (mobile.matches && !shell.classList.contains('list-expanded')) {
      root.style.setProperty('--sheet-space', `${Math.ceil(panel.getBoundingClientRect().height)}px`);
    }
    if (map && !shell.classList.contains('list-expanded')) {
      map.invalidateSize({ pan: false });
    }
  }
  function scheduleLayout() {
    if (!layoutFrame) layoutFrame = requestAnimationFrame(updateLayout);
  }
  window.addEventListener('resize', scheduleLayout);
  window.addEventListener('orientationchange', scheduleLayout);
  if (window.visualViewport) window.visualViewport.addEventListener('resize', scheduleLayout);
  if ('ResizeObserver' in window) new ResizeObserver(scheduleLayout).observe(panel);
  const q = document.querySelector('#q');
  q.type = 'search';
  q.setAttribute('aria-label', '場所・キノコ名で検索');
  q.setAttribute('autocomplete', 'off');
  document.querySelector('#list').setAttribute('aria-label', '検索結果の地点一覧');
  document.querySelector('#count').setAttribute('aria-live', 'polite');
  document.querySelector('#locate').setAttribute('aria-label', '現在地を取得');
  document.querySelector('#fit').setAttribute('aria-label', '全地点が見える範囲に戻す');
  document.querySelector('#close').setAttribute('aria-label', '地点詳細を閉じる');
  document.querySelector('#detail').setAttribute('aria-label', '地点詳細');
  document.querySelector('#detail').setAttribute('role', 'region');
  const baseRenderList = renderList;
  renderList = function () {
    baseRenderList();
    const list = document.querySelector('#list');
    list.querySelectorAll('.card').forEach(card => {
      card.tabIndex = 0;
      card.setAttribute('aria-label', `${card.querySelector('h3').textContent}の詳細を開く`);
      card.addEventListener('keydown', event => {
        if (event.target !== card || !['Enter', ' '].includes(event.key)) return;
        event.preventDefault();
        openPlace(card.dataset.id);
      });
    });
    list.querySelectorAll('[data-fav]').forEach(button => {
      const name = button.closest('.card').querySelector('h3').textContent;
      const saved = state.favs.has(button.dataset.fav);
      button.setAttribute('aria-label', `${name}を${saved ? '保存から削除' : '保存'}`);
      button.setAttribute('aria-pressed', String(saved));
    });
    if (!list.querySelector('.card')) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = state.filter === 'fav' ? '保存した地点はまだありません。地点の★を押すと保存できます。' : '条件に合う地点がありません。検索語や絞り込みを変えてください。';
      const reset = document.createElement('button');
      reset.type = 'button';
      reset.textContent = 'すべての地点を表示';
      reset.addEventListener('click', () => {
        state.q = ''; state.filter = 'all'; q.value = '';
        document.querySelectorAll('.chip').forEach(b => b.classList.toggle('on', b.dataset.f === 'all'));
        renderAll();
      });
      empty.appendChild(reset); list.appendChild(empty);
    }
  };
  function closeDetail() {
    document.querySelector('#detail').classList.remove('open');
    state.selected = null;
    renderList();
  }
  document.querySelector('#close').onclick = closeDetail;
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeDetail(); });
  const baseRenderAll = renderAll;
  renderAll = function () {
    if (state.selected && !filtered().some(p => p.id === state.selected)) closeDetail();
    baseRenderAll();
  };
  const baseOpenPlace = openPlace;
  openPlace = function (id) {
    baseOpenPlace(id);
    document.querySelector('#detail').scrollTop = 0;
    document.querySelector('#close').focus({ preventScroll: true });
  };
  locate = function (done) {
    if (!navigator.geolocation) return message('現在地を取得できません。一覧・検索はそのまま使えます。');
    const button = document.querySelector('#locate');
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    const finish = () => { button.disabled = false; button.removeAttribute('aria-busy'); };
    navigator.geolocation.getCurrentPosition(pos => {
      finish();
      state.user = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      if (map) map.flyTo([state.user.lat, state.user.lng], 10, { animate: false });
      if (typeof done === 'function') done();
      renderAll();
    }, err => {
      finish();
      message(err.code === 1 ? '位置情報は未許可です。検索・一覧はそのまま使えます。' : '現在地を取得できませんでした。検索・一覧はそのまま使えます。');
    }, { enableHighAccuracy: false, timeout: 7000, maximumAge: 60000 });
  };
  if (fallback || !map) {
    document.querySelector('#fallback').replaceChildren();
    notice.textContent = '地図を読み込めません。一覧・検索・詳細はそのまま使えます。';
  } else {
    map.eachLayer(layer => {
      if (!(layer instanceof L.TileLayer)) return;
      layer.on('tileerror', () => { notice.textContent = '背景地図を読み込めません。地点のピン・一覧・詳細は利用できます。'; });
      layer.on('tileload', () => { notice.textContent = ''; });
    });
  }
  renderAll();
  updateLayout();
  requestAnimationFrame(() => { if (map) document.querySelector('#fit').click(); });
})();
