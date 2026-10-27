/* =========================================================================
   Авансовые отчёты — автономный режим
   Без входа в систему: любой, кто открыл программу, сразу заполняет отчёт.
   Сохранение — PDF (+ JSON) в папку сессии; печать — бланк A4 или PDF.
   ========================================================================= */
'use strict';

(function () {
  // -----------------------------------------------------------------------
  // Константы
  // -----------------------------------------------------------------------
  const SESSION_KEY = 'avans.standalone.session';
  const DRAFT_PREFIX = 'avans.standalone.draft.';
  const MAX_ADVANCES = 3;
  // Страница релизов: сюда ведёт «Скачать файл», если проверка обновлений не удалась.
  const RELEASES_URL_DEFAULT = 'https://github.com/zigorminsk-debug/Avans-Report/releases';
  const MAX_EXPENSES = 10;
  const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

  const state = {
    sessionId: localStorage.getItem(SESSION_KEY) || '',
    info: null,
    settings: null,
    version: '',
    store: null,
    storeMode: 'server',
    dirHandle: null,
    draft: null,
    lastSaved: null,
  };

  // -----------------------------------------------------------------------
  // Мелкие помощники
  // -----------------------------------------------------------------------
  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  function esc(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  const pad2 = (n) => String(n).padStart(2, '0');

  function parseIsoDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ''));
    if (!match) return null;
    return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
  }

  function fmtDate(value) {
    const d = parseIsoDate(value);
    return d ? `${pad2(d.day)}.${pad2(d.month)}.${d.year}` : (value || '');
  }

  function todayIso() {
    const now = new Date();
    return `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`;
  }

  function fmtMoney(cents) {
    const value = Number(cents || 0);
    const negative = value < 0;
    const abs = Math.abs(Math.round(value));
    const rubles = Math.floor(abs / 100);
    const kopecks = abs % 100;
    const grouped = String(rubles).replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
    return `${negative ? '−' : ''}${grouped},${pad2(kopecks)}`;
  }

  function parseCents(value) {
    if (value === null || value === undefined) return 0;
    const text = String(value).trim().replace(/[\s\u00a0]/g, '').replace(',', '.');
    if (!text) return 0;
    const exact = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(text);
    if (exact) {
      const sign = exact[1] === '-' ? -1 : 1;
      return sign * (parseInt(exact[2], 10) * 100 + parseInt((exact[3] || '0').padEnd(2, '0'), 10));
    }
    const num = Number(text);
    return isFinite(num) ? Math.round(num * 100) : NaN;
  }

  function normalizeAmountInput(input) {
    const cents = parseCents(input.value);
    if (Number.isFinite(cents) && input.value.trim() !== '') {
      input.value = (cents / 100).toFixed(2).replace('.', ',');
    }
  }

  // Сумма прописью (та же логика, что на сервере)
  const UNITS_M = ['', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять'];
  const UNITS_F = ['', 'одна', 'две', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять'];
  const TEENS = ['десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать',
    'пятнадцать', 'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать'];
  const TENS = ['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят',
    'семьдесят', 'восемьдесят', 'девяносто'];
  const HUNDREDS = ['', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот', 'шестьсот',
    'семьсот', 'восемьсот', 'девятьсот'];
  const RUBLE_FORMS = ['рубль', 'рубля', 'рублей'];
  const KOPECK_FORMS = ['копейка', 'копейки', 'копеек'];
  const THOUSAND_FORMS = ['тысяча', 'тысячи', 'тысяч'];
  const MILLION_FORMS = ['миллион', 'миллиона', 'миллионов'];
  const BILLION_FORMS = ['миллиард', 'миллиарда', 'миллиардов'];

  function pluralForm(value, forms) {
    const n = Math.abs(Math.trunc(value));
    if ([11, 12, 13, 14].indexOf(n % 100) >= 0) return forms[2];
    const last = n % 10;
    if (last === 1) return forms[0];
    if (last === 2 || last === 3 || last === 4) return forms[1];
    return forms[2];
  }

  function triple(value, female) {
    const words = [];
    const hundreds = Math.floor(value / 100);
    const rest = value % 100;
    if (hundreds) words.push(HUNDREDS[hundreds]);
    if (rest >= 10 && rest <= 19) {
      words.push(TEENS[rest - 10]);
      return words.join(' ');
    }
    const tens = Math.floor(rest / 10);
    const unit = rest % 10;
    if (tens) words.push(TENS[tens]);
    if (unit) words.push((female ? UNITS_F : UNITS_M)[unit]);
    return words.join(' ');
  }

  function groupWords(value, forms, female) {
    return value ? `${triple(value, female)} ${pluralForm(value, forms)}` : '';
  }

  function amountInWords(cents) {
    let value = Math.round(Number(cents || 0));
    const negative = value < 0;
    value = Math.abs(value);
    const rubles = Math.floor(value / 100);
    const kopecks = value % 100;
    let words;
    if (rubles === 0) {
      words = 'ноль';
    } else {
      const parts = [];
      const billions = Math.floor(rubles / 1e9);
      const millions = Math.floor((rubles % 1e9) / 1e6);
      const thousands = Math.floor((rubles % 1e6) / 1e3);
      const units = rubles % 1000;
      if (billions) parts.push(groupWords(billions, BILLION_FORMS, false));
      if (millions) parts.push(groupWords(millions, MILLION_FORMS, false));
      if (thousands) parts.push(groupWords(thousands, THOUSAND_FORMS, true));
      if (units) parts.push(triple(units, false));
      words = parts.filter(Boolean).join(' ');
    }
    let result = `${words} ${pluralForm(rubles, RUBLE_FORMS)} ${pad2(kopecks)} ${pluralForm(kopecks, KOPECK_FORMS)}`;
    if (negative) result = 'минус ' + result;
    return result.charAt(0).toUpperCase() + result.slice(1);
  }

  function debounce(fn, ms) {
    let timer = null;
    return function debounced(...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  function icon(path, size) {
    return `<svg class="ico" width="${size || 18}" height="${size || 18}" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"
      stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  }

  const ICON = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    list: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.24.57.79.96 1.41 1H21a2 2 0 0 1 0 4h-.09c-.62.04-1.17.43-1.41 1z"/>',
    print: '<path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 14h12v8H6z"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    trash: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    back: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    table: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
    save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
  };

  // -----------------------------------------------------------------------
  // API
  // -----------------------------------------------------------------------
  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  async function api(path, options) {
    const opts = options || {};
    const headers = { 'X-Session-Id': state.sessionId };
    let body = opts.body;
    if (body !== undefined && body !== null) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    // Если есть тело, а метод не указан, это POST: браузер не пропускает
    // GET-запрос с телом («Request with GET/HEAD method cannot have body»).
    const method = opts.method || (body !== undefined && body !== null ? 'POST' : 'GET');
    let response;
    try {
      response = await fetch(path, { method, headers, body, cache: 'no-store' });
    } catch (err) {
      throw new ApiError('Нет связи с программой. Возможно, она закрыта — запустите её снова.', 0);
    }
    if (!response.ok) {
      let detail = '';
      try {
        const payload = await response.json();
        detail = typeof payload.detail === 'string' ? payload.detail
          : Array.isArray(payload.detail) ? payload.detail.map((i) => i.msg || '').join('; ') : '';
      } catch (err) { /* тело не JSON */ }
      throw new ApiError(detail || `Ошибка ${response.status}`, response.status);
    }
    if (opts.raw) return response;
    const text = await response.text();
    return text ? JSON.parse(text) : {};
  }

  async function apiBlob(path, body) {
    const response = await fetch(path, {
      method: body ? 'POST' : 'GET',
      headers: { 'X-Session-Id': state.sessionId, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      let detail = '';
      try {
        const payload = await response.json();
        detail = payload.detail || '';
      } catch (err) { /* ignore */ }
      throw new ApiError(detail || `Ошибка ${response.status}`, response.status);
    }
    return response.blob();
  }

  // -----------------------------------------------------------------------
  // Уведомления и модальные окна
  // -----------------------------------------------------------------------
  function toast(message, type, timeout) {
    const root = $('#toast-root');
    if (!root) return;
    const node = document.createElement('div');
    node.className = 'toast ' + (type || '');
    node.textContent = message;
    root.appendChild(node);
    setTimeout(() => {
      node.style.opacity = '0';
      node.style.transition = 'opacity .25s';
      setTimeout(() => node.remove(), 260);
    }, timeout || (type === 'error' ? 6500 : 3600));
  }

  function openModal(options) {
    const root = $('#modal-root');
    root.classList.remove('hidden');
    root.innerHTML = `
      <div class="modal-overlay" data-close="1"></div>
      <div class="modal ${options.wide ? 'wide' : ''}" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h2>${esc(options.title || '')}</h2>
          <div class="spacer"></div>
          <button class="modal-close" type="button" data-close="1" aria-label="Закрыть">✕</button>
        </div>
        <div class="modal-body">${options.body || ''}</div>
        ${options.actions ? `<div class="modal-actions">${options.actions}</div>` : ''}
      </div>`;
    $$('[data-close]', root).forEach((node) => node.addEventListener('click', closeModal));
    document.addEventListener('keydown', onModalKeydown);
    return root.querySelector('.modal');
  }

  function onModalKeydown(event) {
    if (event.key === 'Escape') closeModal();
  }

  function closeModal() {
    const root = $('#modal-root');
    if (!root) return;
    root.classList.add('hidden');
    root.innerHTML = '';
    document.removeEventListener('keydown', onModalKeydown);
  }

  function confirmDialog(title, message, label, danger) {
    return new Promise((resolve) => {
      const modal = openModal({
        title,
        body: `<p class="mb0">${esc(message)}</p>`,
        actions: `
          <button class="btn" data-act="cancel">Отмена</button>
          <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-act="ok">
            ${esc(label || 'Подтвердить')}</button>`,
      });
      modal.addEventListener('click', (event) => {
        const button = event.target.closest('[data-act]');
        if (!button) return;
        closeModal();
        resolve(button.dataset.act === 'ok');
      });
    });
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.originalHtml = button.innerHTML;
      button.disabled = true;
      button.innerHTML = `<span class="spinner"></span> ${esc(label || 'Подождите…')}`;
    } else {
      button.disabled = false;
      if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
    }
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  // -----------------------------------------------------------------------
  // IndexedDB — хранение выбранной папки между запусками
  // -----------------------------------------------------------------------
  function idbOpen() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('avans-standalone', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('kv');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function idbSet(key, value) {
    try {
      const db = await idbOpen();
      await new Promise((resolve, reject) => {
        const tx = db.transaction('kv', 'readwrite');
        tx.objectStore('kv').put(value, key);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
      db.close();
    } catch (err) { /* приватный режим — папка не запомнится */ }
  }

  async function idbGet(key) {
    try {
      const db = await idbOpen();
      const value = await new Promise((resolve, reject) => {
        const tx = db.transaction('kv', 'readonly');
        const request = tx.objectStore('kv').get(key);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      db.close();
      return value;
    } catch (err) {
      return null;
    }
  }

  // -----------------------------------------------------------------------
  // Хранилище: сервер (общая папка) или браузер (выбранная папка)
  // -----------------------------------------------------------------------
  const ServerStore = {
    mode: 'server',
    label: 'Общая папка программы',
    async folder() {
      const info = await api('/api/info');
      return info.storage.folder;
    },
    async save(payload) {
      const result = await api('/api/reports', { method: 'POST', body: payload });
      return {
        number: result.number,
        report: result.report,
        folder: result.folder,
        pdfName: result.files.pdf_name || `${result.number}.pdf`,
      };
    },
    async pdfBlob(number) {
      return apiBlob('/api/reports/' + encodeURIComponent(number) + '/pdf');
    },
    async openFolder() {
      await api('/api/open-folder', { method: 'POST' });
    },
    async nextNumber(year) {
      const data = await api('/api/number?year=' + year);
      return data.number;
    },
  };

  const BrowserStore = {
    mode: 'browser',
    label: 'Выбранная папка на компьютере',
    dir: null,
    async folder() {
      return this.dir ? this.dir.name : '';
    },
    async _write(name, data) {
      const handle = await this.dir.getFileHandle(name, { create: true });
      const writable = await handle.createWritable();
      await writable.write(data);
      await writable.close();
    },
    async nextNumber(year) {
      let maximum = 0;
      const entries = [];
      if (this.dir) {
        for await (const entry of this.dir.values()) entries.push(entry);
      }
      for (const entry of entries) {
        const match = /^АО-(\d{4})-(\d{4,})\.json$/.exec(entry.name);
        if (match && Number(match[1]) === Number(year)) {
          maximum = Math.max(maximum, Number(match[2]));
        }
      }
      return `АО-${year}-${String(maximum + 1).padStart(4, '0')}`;
    },
    async save(payload) {
      const year = Number(String(payload.report_date).slice(0, 4));
      const number = await this.nextNumber(year);
      const prepared = await api('/api/prepare', { method: 'POST', body: { payload, number } });
      const blob = await apiBlob('/api/pdf', prepared.report);
      await this._write(`${number}.json`, JSON.stringify(prepared.report, null, 2));
      await this._write(`${number}.pdf`, blob);
      return {
        number,
        report: prepared.report,
        folder: this.dir.name,
        pdfName: `${number}.pdf`,
      };
    },
    async pdfBlob(number) {
      const handle = await this.dir.getFileHandle(`${number}.pdf`);
      return handle.getFile();
    },
    async openFolder() {
      toast('Файлы лежат в папке «' + (this.dir ? this.dir.name : '') + '» — она выбрана вами в браузере.', 'success', 6000);
    },
  };

  async function pickDirectory() {
    if (!window.showDirectoryPicker) {
      toast('Этот браузер не умеет писать файлы в выбранную папку. Используйте Chrome, Edge или «Яндекс Браузер» — либо откройте программу, установленную на компьютер.', 'error', 9000);
      return false;
    }
    try {
      const handle = await window.showDirectoryPicker({ mode: 'readwrite', id: 'avans-standalone' });
      const permission = await handle.requestPermission({ mode: 'readwrite' });
      if (permission !== 'granted') {
        toast('Нет разрешения на запись в папку', 'error');
        return false;
      }
      BrowserStore.dir = handle;
      state.dirHandle = handle;
      await idbSet('reports-dir', handle);
      return true;
    } catch (err) {
      if (err && err.name === 'AbortError') return false;
      toast('Не удалось выбрать папку: ' + (err.message || err), 'error');
      return false;
    }
  }

  async function bindStore() {
    if (!state.sessionId) {
      state.sessionId = newSessionId();
      localStorage.setItem(SESSION_KEY, state.sessionId);
    }
    state.info = await api('/api/info');
    state.settings = state.info.settings;
    state.version = state.info.version;

    if (state.info.storage && state.info.storage.writable) {
      state.store = ServerStore;
      state.storeMode = 'server';
      return;
    }
    // Сервер не может писать файлы (например, программа лежит в защищённой папке):
    // сохраняем в папку, выбранную пользователем в браузере.
    state.store = BrowserStore;
    state.storeMode = 'browser';
    const handle = await idbGet('reports-dir');
    if (handle) {
      try {
        const permission = await handle.queryPermission({ mode: 'readwrite' });
        if (permission === 'granted') {
          BrowserStore.dir = handle;
          state.dirHandle = handle;
        } else {
          BrowserStore.dir = handle;
          state.dirHandle = handle;
          state.needsPermission = true;
        }
      } catch (err) { /* ignore */ }
    }
  }

  function newSessionId() {
    const stamp = new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 14);
    const random = Math.random().toString(16).slice(2, 8);
    return `${stamp}-${random}`;
  }

  // -----------------------------------------------------------------------
  // Каркас
  // -----------------------------------------------------------------------
  const NAV = [
    { href: '#/new', label: 'Новый отчёт', match: /^#\/new/ },
    { href: '#/help', label: 'Инструкция', match: /^#\/help/ },
    { href: '#/settings', label: 'Настройки', match: /^#\/settings/ },
  ];

  const DEVELOPER = {
    name: 'Zakharevich Igor',
    email: 'ziv@csl.by',
    phone: '+375293371412',
    phoneLabel: '+375 29 337-14-12',
  };

  function renderShell() {
    const current = location.hash || '#/new';
    const storageLabel = state.storeMode === 'server'
      ? 'Общая папка программы'
      : 'Выбранная папка';
    $('#app').innerHTML = `
      <div class="site">
        <header class="site-head">
          <div class="site-head-in">
            <a class="brand" href="#/new">
              <img class="logo" src="/static/favicon.svg" alt="">
              <span class="brand-text">
                <strong>СМ групп</strong>
                <span>Авансовые отчёты · автономный режим</span>
              </span>
            </a>
            <nav class="site-nav">
              ${NAV.map((item) => `
                <a href="${item.href}" class="${item.match.test(current) ? 'active' : ''}">
                  ${esc(item.label)}
                </a>`).join('')}
              <button class="site-nav-btn" id="btn-check-updates" type="button">
                Проверить обновления
              </button>
            </nav>
          </div>
        </header>

        <div class="site-body">
          <div class="page-head">
            <h1 id="page-title">Новый отчёт</h1>
            <div class="page-head-side">
              <span class="mode-badge ${state.storeMode === 'server' ? '' : 'offline'}">
                ${icon(ICON.folder, 14)} ${esc(storageLabel)}
              </span>
              <button class="btn btn-sm" id="btn-new-session" type="button"
                      title="Отдельная папка для новых отчётов">
                ${icon(ICON.plus, 14)} Новая сессия
              </button>
            </div>
          </div>
          <div class="content" id="content">
            <div class="center-box"><span class="spinner dark"></span> Загрузка…</div>
          </div>
        </div>

        <footer class="site-foot">
          <div class="site-foot-in">
            <div class="foot-col">
              <b>ООО «Сэйлз Модерн групп»</b>
              <span>г. Минск, пр-т Независимости, 177, пом. 71 · <a href="http://sm-group.by"
                    target="_blank" rel="noopener">sm-group.by</a></span>
              <span class="foot-note">Авансовые отчёты · автономный режим · версия
                <span data-version>${esc(state.version)}</span></span>
            </div>
            <div class="foot-col right">
              <b>Разработчик</b>
              <span>${esc(DEVELOPER.name)}</span>
              <span><a href="mailto:${esc(DEVELOPER.email)}">${esc(DEVELOPER.email)}</a>
                · <a href="tel:${esc(DEVELOPER.phone)}">${esc(DEVELOPER.phoneLabel)}</a></span>
            </div>
          </div>
        </footer>
      </div>`;
    $('#btn-check-updates').addEventListener('click', () => checkUpdates(true));
    $('#btn-new-session').addEventListener('click', startNewSession);
    route();
  }

  async function startNewSession() {
    const ok = await confirmDialog(
      'Начать новую сессию?',
      'Будет создана отдельная папка для новых отчётов. Уже сохранённые отчёты останутся на диске — они лежат в предыдущей папке.',
      'Начать новую',
    );
    if (!ok) return;
    state.sessionId = newSessionId();
    localStorage.setItem(SESSION_KEY, state.sessionId);
    state.lastSaved = null;
    state.draft = null;
    try { sessionStorage.removeItem(draftKey()); } catch (err) { /* ignore */ }
    await bindStore();
    renderShell();
    toast('Создана новая сессия', 'success');
  }

  function setTitle(text) {
    const node = $('#page-title');
    if (node) node.textContent = text;
  }

  const content = () => $('#content');
  function navigate(hash) {
    if (location.hash === hash) route();
    else location.hash = hash;
  }

  let routeSeq = 0;

  async function route() {
    const seq = ++routeSeq;
    const hash = location.hash || '#/new';
    $$('.nav a').forEach((link) => {
      link.classList.toggle('active', link.getAttribute('href') === hash);
    });
    try {
      if (hash === '#/saved') {
        // Раздел списка убран: старые ссылки ведут к заполнению нового отчёта
        location.replace('#/new');
        return;
      }
      if (hash === '#/settings') await renderSettings(seq);
      else if (hash === '#/help') renderHelp(seq);
      else await renderEditor(seq);
    } catch (err) {
      if (seq !== routeSeq) return;
      content().innerHTML = `<div class="notice error">${esc(err.message)}</div>`;
    }
  }

  // -----------------------------------------------------------------------
  // Документ (печать и предпросмотр)
  // -----------------------------------------------------------------------
  function approvalBlock(report) {
    return `
      <div class="doc-approve">
        <div class="approve-title">УТВЕРЖДАЮ</div>
        <div class="approve-sum">Отчет в сумме:
          <span class="approve-amount">${esc(report.amount_words || amountInWords((report.totals || {}).approved_cents))}</span>
        </div>
        <div class="doc-sign-grid">
          <div class="lbl">${esc(report.director_position || 'Директор')}</div>
          <div class="line"></div>
          <div class="name">${esc(report.director_name || '')}</div>
        </div>
        <div class="doc-hints"><span>(должность)</span><span>(подпись, фамилия, инициалы)</span></div>
      </div>`;
  }

  function amountsTable(report) {
    const totals = report.totals || {};
    const advances = report.advances || [];
    return `
      <table class="doc-table doc-amounts">
        <colgroup><col class="c1"><col class="c2"></colgroup>
        <thead><tr><th>Наименование показателя</th><th>Сумма, руб. коп</th></tr></thead>
        <tbody>
          <tr><td class="lbl">Получено (дата):</td>
            <td class="num">${advances.length ? '' : '—'}</td></tr>
          ${advances.map((row) => `
            <tr><td class="lbl">&nbsp;&nbsp;&nbsp;${fmtDate(row.date)}</td>
              <td class="num">${fmtMoney(row.amount_cents)}</td></tr>`).join('')}
          <tr class="total"><td class="lbl">Итого получено</td>
            <td class="num">${fmtMoney(totals.received_cents)}</td></tr>
          <tr><td class="lbl">Израсходовано</td>
            <td class="num">${fmtMoney(totals.spent_cents)}</td></tr>
          <tr><td class="lbl">Остаток денежных средств (к возврату) / - Перерасход (к возмещению)</td>
            <td class="num">${fmtMoney(totals.balance_cents)}</td></tr>
        </tbody>
      </table>`;
  }

  function expensesTable(report) {
    const totals = report.totals || {};
    const expenses = report.expenses || [];
    const rows = [];
    for (let i = 0; i < MAX_EXPENSES; i += 1) {
      const row = expenses[i];
      rows.push(`
        <tr>
          <td class="center">${row ? esc(row.date) : '&nbsp;'}</td>
          <td>${row ? esc(row.document) : '&nbsp;'}</td>
          <td class="center">${row ? esc(row.document_number) : '&nbsp;'}</td>
          <td>${row ? esc(row.purpose) : '&nbsp;'}</td>
          <td class="num">${row ? fmtMoney(row.amount_cents) : '&nbsp;'}</td>
        </tr>`);
    }
    return `
      <table class="doc-table doc-expenses">
        <colgroup><col class="d1"><col class="d2"><col class="d3"><col class="d4"><col class="d5"></colgroup>
        <thead>
          <tr>
            <th colspan="3">Документ, подтверждающий приобретение товаров (работ, услуг)</th>
            <th rowspan="2">Кому, за что уплачено. Иная информация (при необходимости)</th>
            <th rowspan="2">Сумма, руб. коп</th>
          </tr>
          <tr><th>Дата</th><th>Наименование документа</th><th>Номер</th></tr>
        </thead>
        <tbody>${rows.join('')}</tbody>
        <tfoot>
          <tr class="total"><td colspan="4" class="center">Итого</td>
            <td class="num">${fmtMoney(totals.spent_cents)}</td></tr>
        </tfoot>
      </table>`;
  }

  function signatureBlock(report) {
    return `
      <div class="doc-signs">
        <div class="row">
          <div class="lbl">Подотчетное лицо</div>
          <div class="line"></div>
          <div class="name">${esc(report.person_name)}</div>
        </div>
        <div class="hints"><span></span><span>(подпись)</span><span>(расшифровка подписи)</span></div>
        <div class="checked">
          <span>Отчет проверен. К утверждению в сумме:</span>
          <span class="amount">${fmtMoney((report.totals || {}).approved_cents)}</span>
          <span>руб.коп</span>
        </div>
        <div class="row">
          <div class="lbl">${esc(report.accountant_position || 'Бухгалтер')}</div>
          <div class="line"></div>
          <div class="name">${esc(report.accountant_name || '')}</div>
        </div>
        <div class="hints"><span></span><span>(подпись)</span><span>(подпись, фамилия, инициалы)</span></div>
      </div>`;
  }

  function documentHtml(report) {
    const d = parseIsoDate(report.report_date);
    const created = report.created_at_local
      || (report.created_at ? String(report.created_at).replace('T', ' ').slice(0, 16) : '');
    return `
      <div class="doc" id="report-document">
        <div class="doc-top">
          <div class="doc-org">${esc(report.org_name || '')}</div>
          ${approvalBlock(report)}
        </div>
        <div class="doc-title">Отчет об израсходованных суммах</div>
        <div class="doc-datebar">
          <span class="doc-date">от <span class="q">«</span>${d ? d.day : ''}<span class="q">»</span>
            ${d ? MONTHS[d.month - 1] : ''} ${d ? d.year : ''} г.</span>
        </div>
        <div class="doc-fields">
          <div class="doc-field">
            <div class="lbl">Подотчетное лицо</div>
            <div class="val">${esc(report.person_name)}</div>
            <div class="hint">(фамилия, инициалы)</div>
          </div>
          <div class="doc-field">
            <div class="lbl">Должность служащего (профессия рабочего)</div>
            <div class="val">${esc(report.person_position || '')}</div>
          </div>
          <div class="doc-field">
            <div class="lbl">Назначение аванса</div>
            <div class="val">${esc(report.purpose || '')}</div>
          </div>
        </div>
        ${amountsTable(report)}
        ${expensesTable(report)}
        ${signatureBlock(report)}
        <div class="doc-foot">Сформирован ${esc(created)}</div>
      </div>`;
  }

  // Компактные стили печатного листа: бланк должен укладываться в одну A4
  const PRINT_CSS =
    '@page{size:A4 portrait;margin:6mm;}' +
    'html,body{background:#fff;margin:0;padding:0;}' +
    'body{font-family:"Times New Roman","Liberation Serif",Times,serif;}' +
    '.print-toolbar{position:sticky;top:0;z-index:5;display:flex;gap:10px;justify-content:flex-end;' +
    'padding:8px 12px;background:#f4f4f5;border-bottom:1px solid #d7d7da;font-family:Tahoma,Arial,sans-serif;}' +
    '.print-hint{font-family:Tahoma,Arial,sans-serif;font-size:11.5px;color:#606062;' +
    'padding:6px 12px 0;}' +
    '.print-wrap{padding:6px 0 12px;}' +
    '#sheet{transform-origin:top left;}' +
    '.doc{width:auto;min-height:0;margin:0 auto;padding:0;box-shadow:none;border-radius:0;' +
    'font-size:9.1pt;line-height:1.17;}' +
    '.doc-org{font-size:12pt;}' +
    '.doc-approve{font-size:8.6pt;} .doc-approve .approve-title{font-size:11pt;margin-bottom:1.2mm;}' +
    '.doc-approve .approve-sum{margin-bottom:2mm;}' +
    '.doc-title{font-size:13.5pt;margin:3mm 0 1.5mm;}' +
    '.doc-datebar{font-size:10pt;margin-bottom:2.5mm;}' +
    '.doc-fields{margin:0 0 2.5mm;} .doc-field{margin-bottom:1.6mm;}' +
    '.doc-field .lbl,.doc-signs .row .lbl,.doc-signs .row .name{font-size:9.4pt;}' +
    '.doc-table th,.doc-table td{padding:.5mm 1.1mm;font-size:8.5pt;}' +
    '.doc-table th{font-size:8.3pt;}' +
    '.doc-table td.tall{height:5.6mm;}' +
    '.doc-amounts{margin-bottom:2.6mm;} .doc-expenses{margin-bottom:2.6mm;}' +
    '.doc-signs{margin-top:3mm;} .doc-signs .hints{font-size:7pt;margin-bottom:2mm;}' +
    '.doc-signs .checked{font-size:9.4pt;margin:2mm 0 3mm;}' +
    '.doc-foot{margin-top:2.5mm;font-size:7pt;}' +
    '@media print{.print-toolbar,.print-hint{display:none !important;} .print-wrap{padding:0;}' +
    '.doc-table th{background:#f0f0f0 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact;}}';

  // Подгоняет лист под высоту страницы A4 (поля 6 мм), чтобы бланк
  // всегда печатался на одном листе.
  const FIT_SCRIPT =
    '(function(){var sheet=document.getElementById("sheet");if(!sheet)return;' +
    'var mm=96/25.4;var pageH=(297-12)*mm;var pageW=(210-12)*mm;' +
    'sheet.style.zoom=1;' +
    'var h=sheet.getBoundingClientRect().height;var w=sheet.getBoundingClientRect().width;' +
    'var k=Math.min(h>pageH?pageH/h:1,w>pageW?pageW/w:1);' +
    'if(k<0.999){sheet.style.zoom=(Math.floor(k*1000)/1000);}' +
    'window.__fit=Math.round(k*1000)/1000;' +
    'setTimeout(function(){window.focus();window.print();},260);' +
    '})();';

  function printSheetHtml(report) {
    return '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">' +
      '<title>' + esc('Авансовый отчёт ' + (report.number || '')) + '</title>' +
      '<link rel="stylesheet" href="/shared/styles.css">' +
      '<style>' + PRINT_CSS + '</style></head><body>' +
      '<div class="print-toolbar">' +
      '<button class="btn" onclick="window.close()">Закрыть</button>' +
      '<button class="btn btn-primary" onclick="window.print()">Печать</button></div>' +
      '<div class="print-hint">Бланк подготовлен для одного листа A4 — можно печатать ' +
      'или сохранить в PDF средствами принтера.</div>' +
      '<div class="print-wrap"><div id="sheet">' +
      documentHtml(report) + '</div></div>' +
      '<script>' + FIT_SCRIPT + '<\/script></body></html>';
  }

  function printReport(report) {
    const html = printSheetHtml(report);
    const win = window.open('', '_blank');
    if (!win) {
      printViaIframe(report);
      return;
    }
    win.document.open();
    win.document.write(html);
    win.document.close();
  }

  function printViaIframe(report) {
    const frame = document.createElement('iframe');
    frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0';
    document.body.appendChild(frame);
    const doc = frame.contentWindow.document;
    doc.open();
    doc.write('<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">' +
      '<link rel="stylesheet" href="/shared/styles.css">' +
      '<style>' + PRINT_CSS + '</style></head><body>' +
      '<div class="print-wrap"><div id="sheet">' +
      documentHtml(report) + '</div></div></body></html>');
    doc.close();
    setTimeout(() => {
      try {
        const sheet = doc.getElementById('sheet');
        const pageH = (297 - 12) * 96 / 25.4;
        if (sheet) {
          const ratio = pageH / sheet.getBoundingClientRect().height;
          if (ratio < 1) sheet.style.zoom = Math.floor(ratio * 1000) / 1000;
        }
        frame.contentWindow.focus();
        frame.contentWindow.print();
      } catch (err) { /* ignore */ }
      setTimeout(() => frame.remove(), 2000);
    }, 420);
  }

  // -----------------------------------------------------------------------
  // Редактор
  // -----------------------------------------------------------------------
  function blankExpense() {
    return { date: '', document: '', document_number: '', purpose: '', amount: '' };
  }

  function emptyDraft() {
    const settings = state.settings || {};
    return {
      report_date: todayIso(),
      person_name: settings.default_person_name || '',
      person_position: settings.default_person_position || '',
      purpose: (settings.purposes && settings.purposes[0]) || 'Командировочные расходы',
      advances: [{ date: todayIso(), amount: '' }],
      expenses: [blankExpense(), blankExpense(), blankExpense()],
    };
  }

  function draftKey() {
    return DRAFT_PREFIX + state.sessionId;
  }

  function loadDraft() {
    try {
      const raw = sessionStorage.getItem(draftKey());
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed && parsed.report_date ? parsed : null;
    } catch (err) {
      return null;
    }
  }

  const saveDraftDebounced = debounce(() => {
    try {
      sessionStorage.setItem(draftKey(), JSON.stringify(state.draft));
    } catch (err) { /* ignore */ }
  }, 400);

  async function renderEditor(seq) {
    setTitle('Авансовый отчёт');
    if (!state.draft) state.draft = loadDraft() || emptyDraft();
    const restored = !!loadDraft();
    content().innerHTML = `
      ${state.lastSaved ? resultBoxHtml(state.lastSaved) : ''}
      ${state.needsPermission ? permissionBanner() : ''}
      <div class="doc-editor-bar no-print">
        <div class="title">Заполнение отчёта</div>
        <div class="totals">
          К утверждению: <b data-total-label="approved">0,00</b> руб.
        </div>
        <button class="btn btn-print" id="btn-print-draft" type="button"
                title="Печать бланка без сохранения (Ctrl+P)">
          ${icon(ICON.print, 16)} Печать без сохранения
        </button>
        <button class="btn" id="btn-pdf-draft" type="button" title="Посмотреть бланк в PDF">
          ${icon(ICON.file, 16)} Предпросмотр PDF
        </button>
        <button class="btn btn-primary" id="btn-save" type="button">
          ${icon(ICON.save, 16)} Сохранить отчёт
        </button>
      </div>
      <div class="notice warn" id="editor-hint" style="display:none"></div>
      ${restored ? `<div class="notice info no-print">Восстановлен несохранённый черновик
        <button class="btn btn-sm" id="btn-drop-draft" type="button">Начать заново</button></div>` : ''}
      <div class="doc-wrap"><div class="doc" id="editor-doc"></div></div>
      <div class="quick-tips no-print">
        <div><b>Ctrl+S</b> — сохранить отчёт, <b>Ctrl+P</b> — напечатать бланк без сохранения.
          Черновик хранится отдельно в каждой вкладке.</div>
        <div>Как заполнять и печатать — в разделе
          <a href="#/help">«Инструкция»</a> (её можно распечатать).</div>
        <div>После сохранения отчёт получает номер и сразу записывается в PDF
          (${state.storeMode === 'server' ? esc(state.info.storage.folder) : 'папку, выбранную вами'}).</div>
      </div>`;

    $('#btn-save').addEventListener('click', saveReport);
    $('#btn-print-draft').addEventListener('click', () => safe(printDraft));
    $('#btn-pdf-draft').addEventListener('click', () => safe(async () => {
      const prepared = await prepareDraft();
      const blob = await apiBlob('/api/pdf', prepared.report);
      const url = URL.createObjectURL(blob);
      const win = window.open(url, '_blank');
      if (!win) downloadBlob(blob, `${prepared.number}.pdf`);
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }));
    const drop = $('#btn-drop-draft');
    if (drop) drop.addEventListener('click', () => {
      state.draft = emptyDraft();
      try { sessionStorage.removeItem(draftKey()); } catch (err) { /* ignore */ }
      route();
    });
    const pick = $('#btn-pick-folder');
    if (pick) pick.addEventListener('click', () => safe(async () => {
      if (await pickDirectory()) {
        state.needsPermission = false;
        toast('Папка выбрана: ' + BrowserStore.dir.name, 'success');
        route();
      }
    }));
    renderEditorBody();
  }

  function permissionBanner() {
    return `
      <div class="notice warn no-print">
        Программа не может записывать файлы в общую папку, поэтому отчёты
        сохраняются в папку, которую вы выберете. Выберите её один раз — браузер её запомнит.
        <button class="btn btn-sm" id="btn-pick-folder" type="button" style="margin-left:8px">
          ${icon(ICON.folder, 14)} Выбрать папку
        </button>
      </div>`;
  }

  function resultBoxHtml(saved) {
    return `
      <div class="result-box no-print">
        <h3>Отчёт ${esc(saved.number)} сохранён в PDF</h3>
        <div class="files">
          <div>PDF: ${esc(saved.pdfName || saved.number + '.pdf')}</div>
          <div>папка: ${esc(saved.folder)}</div>
        </div>
        <div class="report-actions">
          <button class="btn btn-primary" data-result="pdf">${icon(ICON.file, 15)} Открыть PDF</button>
          <button class="btn" data-result="print">${icon(ICON.print, 15)} Печать</button>
          <button class="btn" data-result="download">${icon(ICON.download, 15)} Скачать PDF</button>
          <button class="btn" data-result="folder">${icon(ICON.folder, 15)} Открыть папку</button>
          <button class="btn" data-result="new">${icon(ICON.plus, 15)} Новый отчёт</button>
        </div>
      </div>`;
  }

  function bindResultBox() {
    const box = $('.result-box');
    if (!box || !state.lastSaved) return;
    box.addEventListener('click', (event) => safe(async () => {
      const button = event.target.closest('[data-result]');
      if (!button) return;
      const action = button.dataset.result;
      const saved = state.lastSaved;
      if (action === 'pdf') {
        const blob = await state.store.pdfBlob(saved.number);
        const url = URL.createObjectURL(blob);
        const win = window.open(url, '_blank');
        if (!win) downloadBlob(blob, `${saved.number}.pdf`);
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      }
      if (action === 'download') {
        const blob = await state.store.pdfBlob(saved.number);
        downloadBlob(blob, `${saved.number}.pdf`);
      }
      if (action === 'print') printReport(saved.report);
      if (action === 'folder') await state.store.openFolder();
      if (action === 'new') {
        state.lastSaved = null;
        state.draft = emptyDraft();
        try { sessionStorage.removeItem(draftKey()); } catch (err) { /* ignore */ }
        route();
      }
    }));
  }

  function renderEditorBody() {
    const draft = state.draft;
    const doc = $('#editor-doc');
    if (!doc) return;
    const purposes = (state.settings && state.settings.purposes) || [];

    const advances = draft.advances.map((row, index) => `
      <tr>
        <td class="cell-td"><input class="cell-input" type="date"
            data-path="advances.${index}.date" value="${esc(row.date)}"></td>
        <td class="cell-td num"><input class="cell-input" type="text" inputmode="decimal"
            placeholder="0,00" data-path="advances.${index}.amount" data-money="1"
            value="${esc(row.amount)}"></td>
        <td class="cell-td" style="width:7mm;border-left:none">
          ${draft.advances.length > 1 ? `<div class="row-tools">
            <button type="button" data-remove-advance="${index}" title="Удалить строку">✕</button>
          </div>` : ''}
        </td>
      </tr>`).join('');

    const expenses = draft.expenses.map((row, index) => `
      <tr>
        <td class="cell-td"><input class="cell-input" type="text" placeholder="дд.мм.гггг"
            data-path="expenses.${index}.date" value="${esc(row.date)}"></td>
        <td class="cell-td"><input class="cell-input" type="text" placeholder="Чек, билет…"
            data-path="expenses.${index}.document" value="${esc(row.document)}"></td>
        <td class="cell-td"><input class="cell-input" type="text"
            data-path="expenses.${index}.document_number" value="${esc(row.document_number)}"></td>
        <td class="cell-td"><input class="cell-input" type="text"
            placeholder="Кому, за что уплачено" data-path="expenses.${index}.purpose"
            value="${esc(row.purpose)}"></td>
        <td class="cell-td num"><input class="cell-input" type="text" inputmode="decimal"
            placeholder="0,00" data-path="expenses.${index}.amount" data-money="1"
            value="${esc(row.amount)}"></td>
        <td class="cell-td" style="width:7mm;border-left:none">
          <div class="row-tools">
            <button type="button" data-remove-expense="${index}" title="Удалить строку">✕</button>
          </div>
        </td>
      </tr>`).join('');

    doc.innerHTML = `
      <div class="doc-top">
        <div class="doc-org">${esc((state.settings && state.settings.org_name) || '')}</div>
        <div class="doc-approve">
          <div class="approve-title">УТВЕРЖДАЮ</div>
          <div class="approve-sum">Отчет в сумме:<span class="approve-amount" data-words></span></div>
          <div class="doc-sign-grid">
            <div class="lbl">${esc((state.settings && state.settings.director_position) || 'Директор')}</div>
            <div class="line"></div>
            <div class="name">${esc((state.settings && state.settings.director_name) || '')}</div>
          </div>
          <div class="doc-hints"><span>(должность)</span><span>(подпись, фамилия, инициалы)</span></div>
        </div>
      </div>
      <div class="doc-title">Отчет об израсходованных суммах</div>
      <div class="doc-datebar">
        <span class="doc-date">от <span class="q">«</span><span data-date-day></span><span class="q">»</span>
          <span data-date-month></span> <span data-date-year></span> г.</span>
      </div>
      <div class="doc-fields">
        <div class="doc-field">
          <div class="lbl">Подотчетное лицо</div>
          <input class="cell-input" type="text" data-path="person_name"
                 placeholder="Фамилия Имя Отчество" value="${esc(draft.person_name)}">
          <div class="hint">(фамилия, инициалы)</div>
        </div>
        <div class="doc-field">
          <div class="lbl">Должность служащего (профессия рабочего)</div>
          <input class="cell-input" type="text" data-path="person_position"
                 value="${esc(draft.person_position)}">
        </div>
        <div class="doc-field">
          <div class="lbl">Назначение аванса</div>
          <select class="cell-input" data-path="purpose">
            ${purposes.map((purpose) => `<option value="${esc(purpose)}"
              ${draft.purpose === purpose ? 'selected' : ''}>${esc(purpose)}</option>`).join('')}
            ${purposes.indexOf(draft.purpose) < 0 && draft.purpose
              ? `<option value="${esc(draft.purpose)}" selected>${esc(draft.purpose)}</option>` : ''}
          </select>
        </div>
        <div class="doc-field">
          <div class="lbl">Дата составления отчёта</div>
          <div class="val" style="border-bottom:none;padding:0">
            <input class="cell-input" type="date" data-path="report_date" value="${esc(draft.report_date)}">
          </div>
        </div>
      </div>
      <table class="doc-table doc-amounts">
        <colgroup><col class="c1"><col class="c2"></colgroup>
        <thead><tr><th>Наименование показателя</th><th>Сумма, руб. коп</th></tr></thead>
        <tbody>
          <tr><td class="lbl">Получено (дата):</td><td class="num">—</td></tr>
          ${advances}
          <tr class="total"><td class="lbl">Итого получено</td>
            <td class="num" data-total="received">0,00</td></tr>
          <tr><td class="lbl">Израсходовано</td><td class="num" data-total="spent">0,00</td></tr>
          <tr><td class="lbl">Остаток денежных средств (к возврату) / - Перерасход (к возмещению)</td>
            <td class="num" data-total="balance">0,00</td></tr>
        </tbody>
      </table>
      ${draft.advances.length < MAX_ADVANCES ? `
        <div class="add-row no-print">
          <button class="btn btn-sm" type="button" id="btn-add-advance">+ Добавить строку аванса</button>
        </div>` : ''}
      <table class="doc-table doc-expenses">
        <colgroup><col class="d1"><col class="d2"><col class="d3"><col class="d4"><col class="d5"></colgroup>
        <thead>
          <tr>
            <th colspan="3">Документ, подтверждающий приобретение товаров (работ, услуг)</th>
            <th rowspan="2">Кому, за что уплачено. Иная информация (при необходимости)</th>
            <th rowspan="2">Сумма, руб. коп</th>
          </tr>
          <tr><th>Дата</th><th>Наименование документа</th><th>Номер</th></tr>
        </thead>
        <tbody>${expenses}</tbody>
        <tfoot>
          <tr class="total"><td colspan="4" class="center">Итого</td>
            <td class="num" data-total="spent">0,00</td></tr>
        </tfoot>
      </table>
      ${draft.expenses.length < MAX_EXPENSES ? `
        <div class="add-row no-print">
          <button class="btn btn-sm" type="button" id="btn-add-expense">+ Добавить строку расхода</button>
        </div>` : ''}
      <div class="doc-signs">
        <div class="row">
          <div class="lbl">Подотчетное лицо</div>
          <div class="line"></div>
          <div class="name" data-sign-person>${esc(draft.person_name)}</div>
        </div>
        <div class="hints"><span></span><span>(подпись)</span><span>(расшифровка подписи)</span></div>
        <div class="checked">
          <span>Отчет проверен. К утверждению в сумме:</span>
          <span class="amount" data-total="approved">0,00</span>
          <span>руб.коп</span>
        </div>
        <div class="row">
          <div class="lbl">${esc((state.settings && state.settings.accountant_position) || 'Бухгалтер')}</div>
          <div class="line"></div>
          <div class="name">${esc((state.settings && state.settings.accountant_name) || '')}</div>
        </div>
        <div class="hints"><span></span><span>(подпись)</span><span>(подпись, фамилия, инициалы)</span></div>
      </div>`;

    if (!doc.dataset.bound) {
      doc.dataset.bound = '1';
      doc.addEventListener('input', onEditorInput);
      doc.addEventListener('blur', onEditorBlur, true);
      doc.addEventListener('click', onEditorClick);
    }
    refreshTotals();
    refreshDateLine();
    bindResultBox();
  }

  function onEditorBlur(event) {
    const input = event.target;
    if (input instanceof HTMLInputElement && input.dataset && input.dataset.money) {
      normalizeAmountInput(input);
      onEditorInput({ target: input });
    }
  }

  function onEditorInput(event) {
    const input = event.target;
    if (!input || !input.dataset || !input.dataset.path) return;
    const path = input.dataset.path;
    if (path === 'report_date') {
      state.draft.report_date = input.value;
      refreshDateLine();
    } else if (['person_name', 'person_position', 'purpose'].indexOf(path) >= 0) {
      state.draft[path] = input.value;
      if (path === 'person_name') {
        const sign = $('[data-sign-person]');
        if (sign) sign.textContent = input.value;
      }
    } else {
      const parts = path.split('.');
      const index = Number(parts[1]);
      if (parts[0] === 'advances' && state.draft.advances[index]) {
        state.draft.advances[index][parts[2]] = input.value;
      }
      if (parts[0] === 'expenses' && state.draft.expenses[index]) {
        state.draft.expenses[index][parts[2]] = input.value;
      }
    }
    input.classList.remove('invalid');
    refreshTotals();
    saveDraftDebounced();
  }

  function onEditorClick(event) {
    if (event.target.closest('#btn-add-advance')) {
      state.draft.advances.push({ date: '', amount: '' });
      return renderEditorBody();
    }
    if (event.target.closest('#btn-add-expense')) {
      state.draft.expenses.push(blankExpense());
      return renderEditorBody();
    }
    const removeAdvance = event.target.closest('[data-remove-advance]');
    if (removeAdvance) {
      state.draft.advances.splice(Number(removeAdvance.dataset.removeAdvance), 1);
      return renderEditorBody();
    }
    const removeExpense = event.target.closest('[data-remove-expense]');
    if (removeExpense) {
      state.draft.expenses.splice(Number(removeExpense.dataset.removeExpense), 1);
      renderEditorBody();
    }
  }

  function totals() {
    const draft = state.draft;
    const received = draft.advances.reduce((sum, row) => {
      const cents = parseCents(row.amount);
      return sum + (Number.isFinite(cents) ? cents : 0);
    }, 0);
    const spent = draft.expenses.reduce((sum, row) => {
      const cents = parseCents(row.amount);
      return sum + (Number.isFinite(cents) ? cents : 0);
    }, 0);
    return { received, spent, balance: received - spent, approved: spent };
  }

  function refreshTotals() {
    const value = totals();
    $$('[data-total]').forEach((node) => { node.textContent = fmtMoney(value[node.dataset.total]); });
    const words = $('[data-words]');
    if (words) words.textContent = amountInWords(value.approved);
    $$('[data-total-label]').forEach((node) => { node.textContent = fmtMoney(value[node.dataset.totalLabel]); });
  }

  function refreshDateLine() {
    const d = parseIsoDate(state.draft.report_date);
    const day = $('[data-date-day]');
    const month = $('[data-date-month]');
    const year = $('[data-date-year]');
    if (day) day.textContent = d ? d.day : '—';
    if (month) month.textContent = d ? MONTHS[d.month - 1] : '';
    if (year) year.textContent = d ? d.year : '';
  }

  function markInvalid(path) {
    const node = $(`.cell-input[data-path="${path}"]`);
    if (node) {
      node.classList.add('invalid');
      node.focus();
    }
  }

  function showHint(message) {
    const hint = $('#editor-hint');
    if (!hint) return;
    if (!message) {
      hint.style.display = 'none';
      hint.textContent = '';
      return;
    }
    hint.style.display = 'block';
    hint.textContent = message;
  }

  function buildPayload() {
    const draft = state.draft;
    if (!draft.report_date) {
      markInvalid('report_date');
      throw new Error('Укажите дату составления отчёта');
    }
    if (!draft.person_name || draft.person_name.trim().length < 3) {
      markInvalid('person_name');
      throw new Error('Укажите подотчётное лицо');
    }
    if (!draft.purpose) {
      markInvalid('purpose');
      throw new Error('Выберите назначение аванса');
    }
    const advances = [];
    draft.advances.forEach((row, index) => {
      if (!String(row.amount).trim()) return;
      const amount = parseCents(row.amount);
      if (!Number.isFinite(amount) || amount <= 0) {
        markInvalid(`advances.${index}.amount`);
        throw new Error(`Укажите сумму аванса в строке ${index + 1}`);
      }
      if (!row.date) {
        markInvalid(`advances.${index}.date`);
        throw new Error(`Укажите дату получения аванса в строке ${index + 1}`);
      }
      advances.push({ date: row.date, amount: String(row.amount).replace(',', '.') });
    });
    const expenses = [];
    draft.expenses.forEach((row, index) => {
      const hasText = [row.date, row.document, row.document_number, row.purpose]
        .some((value) => String(value || '').trim());
      if (!hasText && !String(row.amount).trim()) return;
      const amount = parseCents(row.amount);
      if (!Number.isFinite(amount) || amount <= 0) {
        markInvalid(`expenses.${index}.amount`);
        throw new Error(`Укажите сумму расхода в строке ${index + 1}`);
      }
      if (!String(row.purpose || '').trim()) {
        markInvalid(`expenses.${index}.purpose`);
        throw new Error(`Заполните «Кому, за что уплачено» в строке ${index + 1}`);
      }
      if (!String(row.date || '').trim()) {
        markInvalid(`expenses.${index}.date`);
        throw new Error(`Укажите дату документа в строке ${index + 1}`);
      }
      expenses.push({
        date: row.date.trim(),
        document: (row.document || '').trim(),
        document_number: (row.document_number || '').trim(),
        purpose: row.purpose.trim(),
        amount: String(row.amount).replace(',', '.'),
      });
    });
    if (!expenses.length) throw new Error('Добавьте хотя бы одну строку расходов');
    return {
      report_date: draft.report_date,
      person_name: draft.person_name.trim(),
      person_position: (draft.person_position || '').trim(),
      purpose: draft.purpose,
      advances,
      expenses,
    };
  }

  async function prepareDraft() {
    const payload = buildPayload();
    return api('/api/prepare', { method: 'POST', body: { payload } });
  }

  // Черновик «как есть»: пустые поля не мешают печати бланка.
  // Подставляем прочерки и минимальную сумму, чтобы бланк собрался всегда.
  function draftAsIs() {
    const draft = state.draft || emptyDraft();
    const today = new Date().toISOString().slice(0, 10);
    const dash = (value) => (String(value || '').trim() || '—');
    const positive = (value) => {
      const cents = parseCents(value);
      return Number.isFinite(cents) && cents > 0 ? String(value).replace(',', '.') : '0.01';
    };
    const expenses = (draft.expenses || []).filter((row) => {
      const hasText = [row.date, row.document, row.document_number, row.purpose]
        .some((value) => String(value || '').trim());
      return hasText || String(row.amount || '').trim();
    });
    return {
      report_date: draft.report_date || today,
      person_name: dash(draft.person_name),
      person_position: (draft.person_position || '').trim(),
      purpose: dash(draft.purpose),
      advances: (draft.advances || [])
        .filter((row) => String(row.amount || '').trim())
        .map((row) => ({ date: row.date || today, amount: positive(row.amount) })),
      expenses: (expenses.length ? expenses : [{ date: today, purpose: '—', amount: '' }])
        .map((row) => {
          const date = String(row.date || '').trim();
          return {
            date: /^\d{2}\.\d{2}\.\d{4}$/.test(date) ? date : today.split('-').reverse().join('.'),
            document: (row.document || '').trim(),
            document_number: (row.document_number || '').trim(),
            purpose: dash(row.purpose),
            amount: positive(row.amount),
          };
        }),
    };
  }

  // Печать без сохранения: бланк открывается сразу, отчёт на диске не создаётся.
  async function printDraft() {
    let prepared = null;
    try {
      prepared = await prepareDraft();
    } catch (err) {
      const ok = await confirmDialog(
        'Отчёт заполнен не полностью',
        `${err.message}. Можно напечатать бланк с тем, что уже заполнено — сохранять отчёт не нужно.`,
        'Печать как есть',
      );
      if (!ok) return;
      prepared = await api('/api/prepare', { method: 'POST', body: { payload: draftAsIs() } });
      prepared.number = prepared.number || '';
      prepared.report.number = prepared.report.number || '';
    }
    printReport(prepared.report);
    toast('Бланк открыт для печати — отчёт не сохранён', 'info', 4500);
  }

  async function saveReport() {
    const button = $('#btn-save');
    let payload;
    try {
      payload = buildPayload();
      showHint('');
    } catch (err) {
      showHint(err.message);
      toast(err.message, 'error');
      return;
    }
    if (state.storeMode === 'browser' && !BrowserStore.dir) {
      if (!(await pickDirectory())) return;
      state.needsPermission = false;
    }
    setBusy(button, true, 'Сохранение…');
    try {
      const saved = await state.store.save(payload);
      state.lastSaved = saved;
      state.draft = emptyDraft();
      try { sessionStorage.removeItem(draftKey()); } catch (err) { /* ignore */ }
      toast(`Отчёт ${saved.number} сохранён в PDF`, 'success', 5000);
      await route();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      showHint(err.message);
      toast(err.message, 'error', 8000);
    } finally {
      setBusy(button, false);
    }
  }

  // -----------------------------------------------------------------------
  // Инструкция
  // -----------------------------------------------------------------------
  function helpHtml() {
    const folder = state.info && state.info.storage
      ? (state.storeMode === 'server' ? state.info.storage.folder : 'папку, выбранную в браузере')
      : 'папку отчётов';
    return `
      <div class="help">
        <p class="help-lead">
          Программа заполняет авансовый отчёт по форме организации, сохраняет его в PDF
          и печатает. Вход в систему не нужен: запустили — и сразу заполняете.
        </p>

        <h3>1. Как заполнить отчёт</h3>
        <ol class="help-steps">
          <li>Откройте раздел <b>«Новый отчёт»</b> — появится бланк.</li>
          <li>Заполните шапку: <b>дату отчёта</b>, <b>фамилию, имя и отчество</b> подотчётного
            лица, <b>должность</b> и <b>назначение аванса</b> (выбирается из списка
            или вписывается вручную).</li>
          <li>В таблице «Получено» укажите <b>дату и сумму</b> выданного аванса.
            Нужна ещё одна выдача — нажмите «Добавить» (до 3 строк).</li>
          <li>В таблице расходов заполните <b>дату, документ, номер, назначение и сумму</b>
            (до 10 строк). Пустые строки в бланк не попадут.</li>
          <li>Суммы вводите как удобно: <code>1250,50</code> или <code>1250.50</code>.
            Итоги, остаток (перерасход) и сумма прописью считаются сами.</li>
          <li>Нажмите <b>«Сохранить отчёт»</b> (или <b>Ctrl+S</b>) — программа присвоит
            номер, например <code>АО-2026-0001</code>, и сразу создаст PDF.</li>
        </ol>
        <p class="help-note">Незаконченный отчёт сохраняется как черновик в этой вкладке:
          можно закрыть страницу и продолжить позже. Кнопка «Начать заново» очищает черновик.</p>

        <h3>2. Печать и PDF</h3>
        <ul class="help-list">
          <li><b>Печать без сохранения</b> (или <b>Ctrl+P</b>) — бланк открывается в новом
            окне и сразу предлагается печать. Отчёт при этом <b>не сохраняется</b>:
            номер не занимается, файлы на диске не создаются. Если какие-то поля пусты,
            программа предложит напечатать бланк «как есть».</li>
          <li>Бланк всегда укладывается на <b>один лист A4</b>: если текста много,
            программа сама немного уменьшает лист.</li>
          <li><b>Скачать PDF</b> — сохраняет готовый файл
            <code>АО-2026-0001.pdf</code> в любую папку
            (в диалоге печати также можно выбрать «Сохранить как PDF»).</li>
          <li><b>Открыть папку</b> — показывает папку, где лежат файлы отчётов.</li>
          <li><b>Предпросмотр PDF</b> — показывает бланк до сохранения, номер при этом
            ещё не занимается.</li>
        </ul>

        <h3>3. Несколько окон одновременно</h3>
        <p>
          Программу можно открыть в нескольких окнах и вкладках: у каждого окна свой
          черновик, а номера отчётов не повторяются. Повторный запуск программы
          не выдаёт «порт занят» — он просто открывает ещё одно окно к уже работающей
          программе. Кнопка <b>«Новая сессия»</b> вверху создаёт отдельную папку
          для новых отчётов.
        </p>

        <h3>4. Где лежат сохранённые отчёты</h3>
        <p>
          Сейчас отчёты сохраняются в ${esc(folder)}. Рядом с PDF лежит служебный
          файл <code>.json</code> с данными отчёта — его лучше не удалять.
          Папку открывает кнопка <b>«Открыть папку»</b> на странице результата
          и в разделе «Настройки».
        </p>
        <p class="help-note">Списка отчётов в программе нет: каждая страница — это
          заполнение нового отчёта, а сохранённые отчёты — файлы в папке.
          Удаление отчёта — обычное удаление его файлов; нумерация при этом не сбивается.</p>

        <h3>5. Настройки</h3>
        <p>
          В разделе <b>«Настройки»</b> указывают организацию, должности и фамилии
          руководителя и бухгалтера, типовые назначения аванса и данные подотчётного
          лица, которые подставляются в новый отчёт. Настройки общие для всех окон
          и попадают в бланк и в PDF.
        </p>

        <h3>6. Обновления</h3>
        <p>
          Кнопка <b>«Проверить обновления»</b> в шапке проверяет новые версии на GitHub.
          Если версия новее, программа покажет список изменений и ссылку на установщик.
          Отчёты (файлы PDF) при обновлении не удаляются.
        </p>

        <h3>7. Если что-то не работает</h3>
        <div class="table-wrap">
          <table class="data help-table">
            <thead><tr><th>Симптом</th><th>Что делать</th></tr></thead>
            <tbody>
              <tr><td>Браузер не открылся</td>
                <td>Откройте адрес из окна программы (в журнале строка «Интерфейс: …»),
                  обычно <code>http://127.0.0.1:8780/</code></td></tr>
              <tr><td>Адрес в браузере заканчивается на 8781 (или другой порт)</td>
                <td>Значит порт 8780 занят другой программой или копией старой версии —
                  программа выбрала следующий свободный порт и открыла <b>его</b>.
                  Работать нужно по адресу, который открылся: он всегда верный.
                  Чтобы вернуть 8780, закройте лишнюю копию программы</td></tr>
              <tr><td>На странице «Файлы интерфейса не найдены»</td>
                <td>Программа запущена, но рядом нет папки интерфейса: закройте все окна
                  программы и установите её заново из установщика</td></tr>
              <tr><td>Не сохраняется отчёт</td>
                <td>Проверьте дату, ФИО, назначение аванса и хотя бы одну строку расходов;
                  папка отчётов должна быть доступна для записи</td></tr>
              <tr><td>При проверке обновлений «Не удалось проверить сертификат GitHub»</td>
                <td>Проверьте дату и время на компьютере. Обновление можно скачать
                  вручную: кнопка <b>«Скачать файл»</b> в окне обновлений открывает
                  страницу релизов в браузере</td></tr>
              <tr><td>Интерфейс выглядит по-старому после обновления</td>
                <td>Нажмите <b>Ctrl+F5</b> — браузер подтянет новый интерфейс</td></tr>
              <tr><td>Нужен общий доступ и права сотрудников</td>
                <td>Для этого есть серверная версия программы («Авансовые отчёты»)</td></tr>
            </tbody>
          </table>
        </div>

        <h3>8. Разработчик</h3>
        <p>
          ${esc(DEVELOPER.name)} · <a href="mailto:${esc(DEVELOPER.email)}">${esc(DEVELOPER.email)}</a>
          · <a href="tel:${esc(DEVELOPER.phone)}">${esc(DEVELOPER.phoneLabel)}</a>
        </p>
      </div>`;
  }

  function printHelp() {
    const win = window.open('', '_blank');
    if (!win) return toast('Браузер заблокировал окно печати', 'error');
    win.document.open();
    win.document.write(
      '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">' +
      '<title>Инструкция — Авансовые отчёты</title>' +
      '<style>' +
      'body{font-family:Tahoma,Arial,sans-serif;color:#282829;font-size:12px;' +
      'line-height:1.5;margin:18mm 16mm;}' +
      'h1{font-size:17px;letter-spacing:1px;margin:0 0 4px;}' +
      'h3{font-size:12.5px;letter-spacing:.6px;text-transform:uppercase;' +
      'margin:16px 0 6px;padding-bottom:3px;border-bottom:1px solid #ccc;}' +
      'ol,ul{margin:0 0 8px 18px;padding:0;} li{margin-bottom:3px;}' +
      'code{font-family:Consolas,monospace;font-size:11.5px;}' +
      'table{width:100%;border-collapse:collapse;margin-top:6px;}' +
      'th,td{border:1px solid #bbb;padding:4px 6px;text-align:left;vertical-align:top;' +
      'font-size:11.5px;} th{background:#f2f2f3;}' +
      '.help-lead{margin:0 0 10px;}' +
      '.help-note{color:#606062;margin:4px 0 10px;}' +
      '.help-foot{margin-top:18px;padding-top:8px;border-top:1px solid #ccc;' +
      'color:#606062;font-size:11px;}' +
      '@page{size:A4;margin:14mm;}' +
      '</style></head><body>' +
      '<h1>Авансовые отчёты — автономный режим</h1>' +
      '<div style="color:#7e7e81;font-size:11px;margin-bottom:10px;">' +
      'Инструкция по работе с программой · версия ' + esc(state.version) + '</div>' +
      helpHtml() +
      '<div class="help-foot">ООО «Сэйлз Модерн групп» · ' +
      esc(DEVELOPER.name) + ' · ' + esc(DEVELOPER.email) + ' · ' +
      esc(DEVELOPER.phoneLabel) + '</div>' +
      '</body></html>');
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 350);
  }

  function renderHelp(seq) {
    if (seq !== routeSeq) return;
    setTitle('Инструкция');
    content().innerHTML = `
      <div class="card help-card">
        <div class="card-head">
          <h2>Инструкция по работе с программой</h2>
          <div class="spacer"></div>
          <button class="btn btn-sm" id="btn-help-print" type="button">
            ${icon(ICON.print, 15)} Печать инструкции
          </button>
          <button class="btn btn-primary btn-sm" id="btn-help-new" type="button">
            ${icon(ICON.plus, 15)} Заполнить отчёт
          </button>
        </div>
        ${helpHtml()}
      </div>`;
    $('#btn-help-print').addEventListener('click', printHelp);
    $('#btn-help-new').addEventListener('click', () => navigate('#/new'));
  }

  // -----------------------------------------------------------------------
  // Настройки
  // -----------------------------------------------------------------------
  async function renderSettings(seq) {
    setTitle('Настройки');
    const data = await api('/api/settings');
    if (seq !== routeSeq) return;
    const s = data.settings;
    content().innerHTML = `
      <div class="card">
        <div class="card-head"><h2>Организация и подписи</h2></div>
        <p class="card-sub">Эти данные попадают в бланк отчёта и в PDF. Настройки общие для всех окон программы.
          Как работать с программой — в разделе <a href="#/help">«Инструкция»</a>.</p>
        <form id="settings-form">
          <div class="settings-grid">
            <div class="field">
              <label for="s-org">Организация (шапка бланка)</label>
              <input type="text" id="s-org" value="${esc(s.org_name)}">
            </div>
            <div class="field">
              <label for="s-director-position">Должность руководителя</label>
              <input type="text" id="s-director-position" value="${esc(s.director_position)}">
            </div>
            <div class="field">
              <label for="s-director-name">Фамилия, инициалы руководителя</label>
              <input type="text" id="s-director-name" value="${esc(s.director_name)}">
            </div>
            <div class="field">
              <label for="s-accountant-position">Должность бухгалтера</label>
              <input type="text" id="s-accountant-position" value="${esc(s.accountant_position)}">
            </div>
            <div class="field">
              <label for="s-accountant-name">Фамилия, инициалы бухгалтера</label>
              <input type="text" id="s-accountant-name" value="${esc(s.accountant_name)}">
            </div>
            <div class="field">
              <label for="s-person">Подставлять ФИО в новый отчёт</label>
              <input type="text" id="s-person" value="${esc(s.default_person_name || '')}"
                     placeholder="необязательно">
            </div>
            <div class="field">
              <label for="s-position">Подставлять должность</label>
              <input type="text" id="s-position" value="${esc(s.default_person_position || '')}"
                     placeholder="необязательно">
            </div>
            <div class="field">
              <label for="s-purposes">Назначение аванса (по одному в строке)</label>
              <textarea id="s-purposes">${esc((s.purposes || []).join('\n'))}</textarea>
            </div>
          </div>
          <button class="btn btn-primary" type="submit">${icon(ICON.check, 16)} Сохранить настройки</button>
        </form>
      </div>
      <div class="card">
        <div class="card-head"><h2>Хранение файлов</h2></div>
        <dl class="kv">
          <dt>Режим сохранения</dt>
          <dd>${state.storeMode === 'server'
            ? 'общая папка программы (файлы доступны всем окнам и вкладкам)'
            : 'папка, выбранная в браузере'}</dd>
          <dt>Папка</dt>
          <dd class="mono">${esc(state.storeMode === 'server'
            ? state.info.storage.folder
            : (BrowserStore.dir ? BrowserStore.dir.name : 'не выбрана'))}</dd>
          <dt>Текущая сессия</dt>
          <dd class="mono">${esc(state.sessionId)}</dd>
          <dt>Версия</dt>
          <dd>${esc(state.version)}</dd>
        </dl>
        ${state.storeMode === 'browser' ? `
          <button class="btn" id="btn-pick-folder2" type="button" style="margin-top:12px">
            ${icon(ICON.folder, 15)} Выбрать папку для отчётов</button>` : `
          <button class="btn" id="btn-open-folder3" type="button" style="margin-top:12px">
            ${icon(ICON.folder, 15)} Открыть папку с отчётами</button>`}
        <div class="setup-hint" style="margin-top:14px">
          Программа не требует входа: любой, кто её запустил, может заполнить отчёт.
          Каждый запуск создаёт свою сессию и свою папку с отчётами — их можно
          открыть кнопкой «Открыть папку».
        </div>
      </div>
      <div class="card dev-card">
        <div class="card-head"><h2>Разработчик</h2></div>
        <div class="dev-line"><b>${esc(DEVELOPER.name)}</b></div>
        <div class="dev-line">
          Почта: <a href="mailto:${esc(DEVELOPER.email)}">${esc(DEVELOPER.email)}</a>
        </div>
        <div class="dev-line">
          Телефон: <a href="tel:${esc(DEVELOPER.phone)}">${esc(DEVELOPER.phoneLabel)}</a>
        </div>
        <div class="dev-line" style="margin-top:8px">
          Программа для
          <a href="http://sm-group.by" target="_blank" rel="noopener">ООО «Сэйлз Модерн групп»</a>
        </div>
      </div>`;

    $('#settings-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type=submit]');
      setBusy(button, true, 'Сохранение…');
      try {
        const payload = {
          org_name: $('#s-org').value.trim(),
          director_position: $('#s-director-position').value.trim(),
          director_name: $('#s-director-name').value.trim(),
          accountant_position: $('#s-accountant-position').value.trim(),
          accountant_name: $('#s-accountant-name').value.trim(),
          default_person_name: $('#s-person').value.trim(),
          default_person_position: $('#s-position').value.trim(),
          purposes: $('#s-purposes').value.split('\n').map((line) => line.trim()).filter(Boolean),
        };
        const result = await api('/api/settings', { method: 'PUT', body: payload });
        state.settings = result.settings;
        toast('Настройки сохранены', 'success');
      } catch (err) {
        toast(err.message, 'error');
      } finally {
        setBusy(button, false);
      }
    });
    const pick = $('#btn-pick-folder2');
    if (pick) pick.addEventListener('click', () => safe(async () => {
      if (await pickDirectory()) {
        state.needsPermission = false;
        toast('Папка выбрана: ' + BrowserStore.dir.name, 'success');
        route();
      }
    }));
    const openFolder = $('#btn-open-folder3');
    if (openFolder) openFolder.addEventListener('click', () => safe(() => state.store.openFolder()));
  }

  // -----------------------------------------------------------------------
  // Обновления
  // -----------------------------------------------------------------------
  async function checkUpdates(force) {
    const modal = openModal({
      title: 'Обновления программы',
      body: '<div class="center-box" style="min-height:120px"><span class="spinner dark"></span> Проверяем GitHub…</div>',
    });
    let info;
    try {
      info = await api('/api/update/check' + (force ? '?force=1' : ''));
    } catch (err) {
      modal.querySelector('.modal-body').innerHTML =
        `<div class="notice error mb0">${esc(err.message)}</div>`;
      return;
    }
    const assets = info.assets || {};
    const asset = assets[state.info.platform === 'windows' ? 'windows_installer' : 'linux_archive']
      || assets.windows_installer || null;
    modal.querySelector('.modal-body').innerHTML = `
      <dl class="kv">
        <dt>Установленная версия</dt><dd><b>${esc(info.current_version)}</b></dd>
        <dt>Последний релиз</dt><dd>${info.latest_version ? '<b>' + esc(info.latest_version) + '</b>' : '—'}</dd>
        <dt>Статус</dt><dd>${info.error ? '<span class="text-danger">' + esc(info.error) + '</span>'
          : (info.update_available ? '<span class="text-ok">Доступно обновление</span>'
            : 'Установлена последняя версия')}</dd>
        ${asset ? `<dt>Файл обновления</dt><dd>${esc(asset.name)}</dd>` : ''}
      </dl>
      ${info.release_notes ? `<div class="section-title">Что нового</div>
        <div class="release-notes">${esc(info.release_notes)}</div>` : ''}
      <p class="modal-note" style="margin-top:12px">
        Обновления публикуются в
        <a href="https://github.com/${esc(state.info.github_repo)}/releases" target="_blank"
           rel="noopener">github.com/${esc(state.info.github_repo)}</a>.
        Отчёты (файлы PDF) при обновлении не удаляются.
      </p>`;
    const head = modal.querySelector('.modal-head');
    head.insertAdjacentHTML('afterend', `
      <div class="modal-actions" style="margin:0 0 14px;justify-content:flex-start">
        <button class="btn" data-act="close">Закрыть</button>
        <a class="btn" href="${esc(info.release_url || info.download_url || RELEASES_URL_DEFAULT)}"
          target="_blank" rel="noopener">${icon(ICON.download, 15)} Скачать файл</a>
        ${info.can_install ? `<button class="btn btn-primary" data-act="install">
          ${icon(ICON.refresh, 15)} Установить и перезапустить</button>` : ''}
      </div>`);
    modal.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-act]');
      if (!button) return;
      if (button.dataset.act === 'close') closeModal();
      if (button.dataset.act === 'install') {
        setBusy(button, true, 'Установка…');
        try {
          const result = await api('/api/update/install', { method: 'POST' });
          closeModal();
          toast(result.message || 'Установщик запущен', 'success', 8000);
        } catch (err) {
          setBusy(button, false);
          toast(err.message, 'error', 9000);
        }
      }
    });
  }

  // -----------------------------------------------------------------------
  // Запуск
  // -----------------------------------------------------------------------
  async function safe(fn) {
    try {
      await fn();
    } catch (err) {
      toast(err.message || String(err), 'error', 8000);
    }
  }

  function editorHotkeys(event) {
    if (!(event.ctrlKey || event.metaKey)) return;
    const onEditor = location.hash === '' || location.hash === '#/new';
    if (event.key.toLowerCase() === 's') {
      event.preventDefault();
      if (onEditor) saveReport();
      return;
    }
    // Ctrl+P — печать бланка без сохранения, а не печать страницы интерфейса
    if (event.key.toLowerCase() === 'p' && onEditor) {
      event.preventDefault();
      safe(printDraft);
    }
  }

  let booted = false;

  async function boot() {
    if (booted) return;
    booted = true;
    document.addEventListener('keydown', editorHotkeys);
    try {
      await bindStore();
    } catch (err) {
      $('#app').innerHTML = `
        <div class="content" style="max-width:640px;margin:40px auto">
          <div class="notice error">
            ${esc(err.message)}
          </div>
          <p class="text-muted">Проверьте, что программа запущена (ярлык «Авансовые отчёты — автономный режим»),
          и обновите страницу.</p>
        </div>`;
      return;
    }
    renderShell();
  }

  window.addEventListener('hashchange', route);

  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
