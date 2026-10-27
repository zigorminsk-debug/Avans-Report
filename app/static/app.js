/* =========================================================================
   Авансовые отчёты — клиентское приложение (vanilla JS, без сборки)
   ========================================================================= */
'use strict';

(function () {
  // -----------------------------------------------------------------------
  // Константы и состояние
  // -----------------------------------------------------------------------
  const TOKEN_KEY = 'avans.token';
  const DRAFT_PREFIX = 'avans.draft.';
  const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  const ROLE_LABELS = { admin: 'Администратор', supervisor: 'Супервайзер', user: 'Пользователь' };
  const MAX_ADVANCES = 3;
  const MAX_EXPENSES = 10;

  const state = {
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: null,
    settings: null,
    version: '',
    repo: '',
    platform: '',
    selfUpdate: false,
    publicInfo: null,
    users: null,
    filters: { from: '', to: '', status: '', owner: '', q: '', scope: 'auto' },
    editor: null,
  };

  // -----------------------------------------------------------------------
  // Вспомогательные функции
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

  function pad2(n) { return String(n).padStart(2, '0'); }

  function parseIsoDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ''));
    if (!match) return null;
    return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
  }

  function fmtDate(value) {
    const d = parseIsoDate(value);
    return d ? `${pad2(d.day)}.${pad2(d.month)}.${d.year}` : (value || '');
  }

  function fmtDateTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    return `${pad2(date.getDate())}.${pad2(date.getMonth() + 1)}.${date.getFullYear()} ` +
      `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
  }

  function longDate(value) {
    const d = parseIsoDate(value);
    return d ? `«${d.day}» ${MONTHS[d.month - 1]} ${d.year} г.` : '';
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
    let text = String(value).trim().replace(/[\s\u00a0]/g, '').replace(',', '.');
    if (!text) return 0;
    const exact = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(text);
    if (exact) {
      const sign = exact[1] === '-' ? -1 : 1;
      const rubles = parseInt(exact[2], 10);
      const kopecks = parseInt((exact[3] || '0').padEnd(2, '0'), 10);
      return sign * (rubles * 100 + kopecks);
    }
    const num = Number(text);
    if (!isFinite(num)) return NaN;
    return Math.round(num * 100);
  }

  function normalizeAmountInput(input) {
    const cents = parseCents(input.value);
    if (Number.isFinite(cents) && input.value.trim() !== '') {
      input.value = (cents / 100).toFixed(2).replace('.', ',');
    }
  }

  // Сумма прописью (русский язык) — та же логика, что и на сервере
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
    let rest = value % 100;
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
    if (!value) return '';
    return `${triple(value, female)} ${pluralForm(value, forms)}`;
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

  function initials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  function debounce(fn, ms) {
    let timer = null;
    return function debounced(...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  function classNames(map) {
    return Object.keys(map).filter((key) => map[key]).join(' ');
  }

  // -----------------------------------------------------------------------
  // Иконки
  // -----------------------------------------------------------------------
  const ICONS = {
    list: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.24.57.79.96 1.41 1H21a2 2 0 0 1 0 4h-.09c-.62.04-1.17.43-1.41 1z"/>',
    print: '<path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 14h12v8H6z"/>',
    mail: '<path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><path d="M22 6l-10 7L2 6"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    trash: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    back: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    db: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  };

  function icon(name, size) {
    const path = ICONS[name] || ICONS.info;
    const s = size || 18;
    return `<svg class="ico" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"
      aria-hidden="true">${path}</svg>`;
  }

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
    const headers = {};
    if (state.token) headers.Authorization = 'Bearer ' + state.token;
    let body = opts.body;
    if (body !== undefined && body !== null && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, {
        method: opts.method || 'GET',
        headers,
        body,
        cache: 'no-store',
      });
    } catch (err) {
      throw new ApiError('Нет связи с сервером. Проверьте подключение.', 0);
    }
    if (response.status === 401) {
      const detail = await safeDetail(response);
      if (state.token && path !== '/api/auth/login' && path !== '/api/setup') {
        clearSession();
        renderAuth('login', detail || 'Сессия истекла. Войдите заново.');
      }
      throw new ApiError(detail || 'Требуется вход', 401);
    }
    if (!response.ok) {
      const detail = await safeDetail(response);
      throw new ApiError(detail || `Ошибка ${response.status}`, response.status);
    }
    if (opts.raw) return response;
    const text = await response.text();
    return text ? JSON.parse(text) : {};
  }

  async function safeDetail(response) {
    try {
      const data = await response.json();
      if (typeof data.detail === 'string') return data.detail;
      if (Array.isArray(data.detail) && data.detail.length) {
        return data.detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
      }
      return '';
    } catch (err) {
      return '';
    }
  }

  async function downloadFile(path, fallbackName) {
    const response = await api(path, { raw: true });
    const blob = await response.blob();
    let filename = fallbackName || 'file';
    const disposition = response.headers.get('content-disposition') || '';
    const utfMatch = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    const plainMatch = /filename="?([^";]+)"?/i.exec(disposition);
    if (utfMatch) filename = decodeURIComponent(utfMatch[1]);
    else if (plainMatch) filename = plainMatch[1];
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  // -----------------------------------------------------------------------
  // Уведомления, модальные окна
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
    }, timeout || (type === 'error' ? 6500 : 3800));
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

  function confirmDialog(title, message, confirmLabel, danger) {
    return new Promise((resolve) => {
      const modal = openModal({
        title,
        body: `<p class="mb0">${esc(message)}</p>`,
        actions: `
          <button class="btn" data-act="cancel">Отмена</button>
          <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-act="ok">
            ${esc(confirmLabel || 'Подтвердить')}
          </button>`,
      });
      modal.addEventListener('click', (event) => {
        const button = event.target.closest('[data-act]');
        if (!button) return;
        closeModal();
        resolve(button.dataset.act === 'ok');
      });
    });
  }

  function setBusy(button, busy, busyLabel) {
    if (!button) return;
    if (busy) {
      button.dataset.originalHtml = button.innerHTML;
      button.disabled = true;
      button.innerHTML = `<span class="spinner"></span> ${esc(busyLabel || 'Подождите…')}`;
    } else {
      button.disabled = false;
      if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
    }
  }

  // -----------------------------------------------------------------------
  // Авторизация
  // -----------------------------------------------------------------------
  function clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    state.token = '';
    state.user = null;
  }

  function renderAuth(mode, message) {
    state.user = null;
    document.body.classList.remove('viewing-report');
    const isSetup = mode === 'setup';
    const app = $('#app');
    app.innerHTML = `
      <div class="auth-wrap">
        <div class="auth-card">
          <div class="auth-brand">
            <img class="logo" src="/favicon.svg" alt="">
            <div>
              <h1>Авансовые отчёты</h1>
              <span>${isSetup ? 'Первичная настройка программы' : 'Вход в систему'}</span>
            </div>
          </div>
          <div class="auth-alert ${message ? 'show error' : ''}" id="auth-error">${esc(message || '')}</div>
          ${isSetup ? setupFormHtml() : loginFormHtml()}
          <div class="auth-foot">
            Версия <span id="auth-version">${esc(state.publicInfo ? state.publicInfo.version : '')}</span>
            ${state.publicInfo && state.publicInfo.org_name
              ? ' · ' + esc(state.publicInfo.org_name) : ''}
          </div>
        </div>
      </div>`;

    if (isSetup) {
      $('#setup-form').addEventListener('submit', onSetupSubmit);
    } else {
      $('#login-form').addEventListener('submit', onLoginSubmit);
    }
    const firstInput = app.querySelector('input');
    if (firstInput) firstInput.focus();
  }

  function loginFormHtml() {
    return `
      <form id="login-form" autocomplete="on">
        <div class="field">
          <label for="login-username">Логин</label>
          <input type="text" id="login-username" name="username" autocomplete="username"
                 autocapitalize="none" spellcheck="false" required>
        </div>
        <div class="field">
          <label for="login-password">Пароль</label>
          <input type="password" id="login-password" name="password" autocomplete="current-password" required>
        </div>
        <button class="btn btn-primary" type="submit">Войти</button>
      </form>`;
  }

  function setupFormHtml() {
    return `
      <p class="text-muted" style="font-size:13.5px">
        Создайте учётную запись администратора. Она понадобится для настройки почты
        и управления пользователями.
      </p>
      <form id="setup-form" autocomplete="off">
        <div class="field">
          <label for="setup-org">Организация</label>
          <input type="text" id="setup-org" name="org_name" value="ООО &quot;Сэйлз Модерн групп&quot;">
        </div>
        <div class="field">
          <label for="setup-name">ФИО администратора</label>
          <input type="text" id="setup-name" name="full_name" placeholder="Иванов Иван Иванович" required>
        </div>
        <div class="field">
          <label for="setup-username">Логин</label>
          <input type="text" id="setup-username" name="username" autocomplete="username"
                 placeholder="admin" autocapitalize="none" spellcheck="false" required>
        </div>
        <div class="field">
          <label for="setup-password">Пароль</label>
          <input type="password" id="setup-password" name="password" autocomplete="new-password" required>
          <span class="hint">Не менее 8 символов, буквы и цифры.</span>
        </div>
        <div class="field">
          <label for="setup-password2">Повторите пароль</label>
          <input type="password" id="setup-password2" name="password2" autocomplete="new-password" required>
        </div>
        <button class="btn btn-primary" type="submit">Создать и войти</button>
      </form>`;
  }

  function authError(message) {
    const box = $('#auth-error');
    if (!box) return;
    box.textContent = message;
    box.className = 'auth-alert show error';
  }

  async function onLoginSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type=submit]');
    const field = (name) => form.querySelector(`[name="${name}"]`);
    const username = field('username').value.trim();
    const password = field('password').value;
    if (!username || !password) {
      authError('Введите логин и пароль');
      return;
    }
    setBusy(button, true, 'Вход…');
    try {
      const data = await api('/api/auth/login', { method: 'POST', body: { username, password } });
      state.token = data.token;
      localStorage.setItem(TOKEN_KEY, data.token);
      applySession(data);
      renderShell();
      navigate(location.hash && location.hash !== '#/login' ? location.hash : '#/reports');
      if (state.user.must_change_password) {
        toast('Смените пароль, выданный администратором', 'error', 6000);
        navigate('#/profile');
      }
    } catch (err) {
      authError(err.message);
    } finally {
      setBusy(button, false);
    }
  }

  async function onSetupSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type=submit]');
    const field = (name) => form.querySelector(`[name="${name}"]`);
    const password = field('password').value;
    if (password !== field('password2').value) {
      authError('Пароли не совпадают');
      return;
    }
    setBusy(button, true, 'Создание…');
    try {
      const data = await api('/api/setup', {
        method: 'POST',
        body: {
          username: field('username').value.trim(),
          password,
          full_name: field('full_name').value.trim(),
          org_name: field('org_name').value.trim(),
        },
      });
      state.token = data.token;
      localStorage.setItem(TOKEN_KEY, data.token);
      applySession(data);
      renderShell();
      navigate('#/reports');
      toast('Учётная запись администратора создана', 'success');
    } catch (err) {
      authError(err.message);
    } finally {
      setBusy(button, false);
    }
  }

  function applySession(data) {
    if (data.user) state.user = data.user;
    if (data.settings) state.settings = data.settings;
    if (data.version) state.version = data.version;
    if (data.github_repo) state.repo = data.github_repo;
    if (data.platform) state.platform = data.platform;
    if (typeof data.self_update_supported === 'boolean') state.selfUpdate = data.self_update_supported;
  }

  async function logout() {
    try { await api('/api/auth/logout', { method: 'POST' }); } catch (err) { /* игнорируем */ }
    clearSession();
    renderAuth('login');
    history.replaceState(null, '', location.pathname);
  }

  // -----------------------------------------------------------------------
  // Каркас
  // -----------------------------------------------------------------------
  function navItems() {
    const role = state.user.role;
    const items = [
      { href: '#/reports', label: 'Отчёты', icon: 'list', match: /^#\/reports/ },
      { href: '#/reports/new', label: 'Новый отчёт', icon: 'plus', match: /^#\/reports\/new/ },
    ];
    if (role === 'admin' || role === 'supervisor') {
      items.push({ href: '#/users', label: 'Пользователи', icon: 'users', match: /^#\/users/ });
    }
    if (role === 'admin') {
      items.push({ href: '#/settings', label: 'Настройки', icon: 'settings', match: /^#\/settings/ });
    }
    items.push({ href: '#/profile', label: 'Профиль', icon: 'user', match: /^#\/profile/ });
    return items;
  }

  function renderShell() {
    const user = state.user;
    const items = navItems();
    const current = location.hash || '#/reports';
    $('#app').innerHTML = `
      <div class="shell">
        <aside class="sidebar">
          <div class="brand">
            <img class="logo" src="/favicon.svg" alt="">
            <div class="brand-text">
              <strong>Авансовые отчёты</strong>
              <span>${esc(state.settings && state.settings.org_name ? state.settings.org_name : 'Учёт авансовых отчётов')}</span>
            </div>
          </div>
          <nav class="nav">
            ${items.map((item) => `
              <a href="${item.href}" class="${item.match.test(current) ? 'active' : ''}">
                ${icon(item.icon)}<span>${esc(item.label)}</span>
              </a>`).join('')}
          </nav>
          <div class="sidebar-foot">
            <div class="user-chip">
              <div class="avatar">${esc(initials(user.full_name))}</div>
              <div class="who">
                <b title="${esc(user.full_name)}">${esc(user.full_name)}</b>
                <span>${esc(user.role_label || ROLE_LABELS[user.role] || '')}</span>
              </div>
            </div>
            <button class="btn btn-outline-light btn-sm" id="btn-check-updates" type="button">
              ${icon('refresh', 15)} Проверить обновления
            </button>
            <div class="version-line">
              <span>Версия <span data-version>${esc(state.version)}</span></span>
              <button class="btn-link" id="btn-logout" type="button"
                      style="color:#b9cddb;font-size:12px">Выйти</button>
            </div>
          </div>
        </aside>
        <div class="main">
          <header class="topbar">
            <h1 id="page-title">Отчёты</h1>
            <div class="spacer"></div>
            <span class="meta">${esc(user.role_label || '')}</span>
          </header>
          <div class="content" id="content">
            <div class="center-box"><span class="spinner dark"></span> Загрузка…</div>
          </div>
        </div>
      </div>`;

    $('#btn-logout').addEventListener('click', logout);
    $('#btn-check-updates').addEventListener('click', () => checkUpdates(true));
    route();
  }

  function setTitle(text) {
    const node = $('#page-title');
    if (node) node.textContent = text;
  }

  function content() {
    return $('#content');
  }

  function navigate(hash) {
    if (location.hash === hash) route();
    else location.hash = hash;
  }

  // -----------------------------------------------------------------------
  // Маршрутизация
  // -----------------------------------------------------------------------
  let routeSeq = 0;

  async function route() {
    if (!state.user) return;
    const seq = ++routeSeq;
    const hash = location.hash || '#/reports';
    document.body.classList.remove('viewing-report');
    if (state.editor && hash !== '#/reports/new') {
      state.editor = null;
      document.removeEventListener('keydown', editorKeydown);
    }

    $$('.nav a').forEach((link) => {
      const href = link.getAttribute('href');
      link.classList.toggle('active', href === '#/reports'
        ? hash === '#/reports' || /^#\/reports\/(?!new)/.test(hash)
        : hash.startsWith(href));
    });

    try {
      if (hash === '#/reports' || hash === '#/reports/') {
        await renderReportsList(seq);
      } else if (hash === '#/reports/new') {
        await renderEditor(null, seq);
      } else if (/^#\/reports\/\d+$/.test(hash)) {
        await renderReportView(Number(hash.split('/').pop()), seq);
      } else if (hash === '#/users') {
        await renderUsers(seq);
      } else if (hash === '#/settings') {
        await renderSettings(seq);
      } else if (hash === '#/profile') {
        await renderProfile(seq);
      } else {
        navigate('#/reports');
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      if (seq !== routeSeq) return;
      content().innerHTML = `<div class="notice error">${esc(err.message)}</div>`;
    }
  }

  // -----------------------------------------------------------------------
  // Список отчётов
  // -----------------------------------------------------------------------
  function statusBadge(report) {
    if (report.status === 'sent') return '<span class="badge sent">Отправлен</span>';
    if ((report.email_status || '').startsWith('error')) return '<span class="badge error">Ошибка почты</span>';
    return '<span class="badge saved">Сохранён</span>';
  }

  async function ensureUsers() {
    if (state.users) return state.users;
    if (state.user.role === 'user') return [];
    try {
      const data = await api('/api/users');
      state.users = data.items;
    } catch (err) {
      state.users = [];
    }
    return state.users;
  }

  async function renderReportsList(seq) {
    setTitle('Отчёты');
    const seesAll = state.user.role === 'admin' || state.user.role === 'supervisor';
    const users = seesAll ? await ensureUsers() : [];
    const f = state.filters;
    content().innerHTML = `
      <div class="card">
        <div class="card-head">
          <h2>${seesAll && f.scope !== 'mine' ? 'Все отчёты' : 'Мои отчёты'}</h2>
          <div class="spacer"></div>
          <button class="btn btn-primary" id="btn-new" type="button">
            ${icon('plus', 16)} Новый отчёт
          </button>
        </div>
        <div class="toolbar" id="filters">
          ${seesAll ? `
            <div class="field">
              <label for="f-scope">Область</label>
              <select id="f-scope">
                <option value="auto" ${f.scope === 'auto' ? 'selected' : ''}>Все отчёты</option>
                <option value="mine" ${f.scope === 'mine' ? 'selected' : ''}>Только мои</option>
              </select>
            </div>
            <div class="field">
              <label for="f-owner">Сотрудник</label>
              <select id="f-owner" ${f.scope === 'mine' ? 'disabled' : ''}>
                <option value="">Все сотрудники</option>
                ${users.map((u) => `<option value="${u.id}" ${String(f.owner) === String(u.id) ? 'selected' : ''}>
                  ${esc(u.full_name)}${u.is_active ? '' : ' (заблокирован)'}</option>`).join('')}
              </select>
            </div>` : ''}
          <div class="field">
            <label for="f-from">Период с</label>
            <input type="date" id="f-from" value="${esc(f.from)}">
          </div>
          <div class="field">
            <label for="f-to">по</label>
            <input type="date" id="f-to" value="${esc(f.to)}">
          </div>
          <div class="field">
            <label for="f-status">Статус</label>
            <select id="f-status">
              <option value="">Любой</option>
              <option value="saved" ${f.status === 'saved' ? 'selected' : ''}>Сохранён</option>
              <option value="sent" ${f.status === 'sent' ? 'selected' : ''}>Отправлен</option>
            </select>
          </div>
          <div class="field grow">
            <label for="f-q">Поиск</label>
            <input type="search" id="f-q" value="${esc(f.q)}" placeholder="Номер, ФИО, назначение, адрес…">
          </div>
          <button class="btn" id="btn-reset" type="button">Сбросить</button>
        </div>
      </div>
      <div class="card" id="reports-card">
        <div class="center-box"><span class="spinner dark"></span> Загрузка…</div>
      </div>`;

    $('#btn-new').addEventListener('click', () => navigate('#/reports/new'));
    $('#btn-reset').addEventListener('click', () => {
      state.filters = { from: '', to: '', status: '', owner: '', q: '', scope: 'auto' };
      renderReportsList(++routeSeq);
    });

    const reload = debounce(() => loadReportsTable(seq), 280);
    const bind = (id, key, immediate) => {
      const node = $('#' + id);
      if (!node) return;
      node.addEventListener('input', () => {
        state.filters[key] = node.value;
        if (immediate) reload();
      });
      node.addEventListener('change', () => {
        state.filters[key] = node.value;
        reload();
      });
    };
    bind('f-from', 'from', true);
    bind('f-to', 'to', true);
    bind('f-status', 'status', true);
    bind('f-q', 'q', true);
    bind('f-owner', 'owner', true);
    bind('f-scope', 'scope', true);

    const scope = $('#f-scope');
    if (scope) {
      scope.addEventListener('change', () => {
        const owner = $('#f-owner');
        if (owner) owner.disabled = scope.value === 'mine';
      });
    }
    await loadReportsTable(seq);
  }

  async function loadReportsTable(seq) {
    const f = state.filters;
    const query = { limit: 300 };
    if (f.from) query.date_from = f.from;
    if (f.to) query.date_to = f.to;
    if (f.status) query.status = f.status;
    if (f.q) query.q = f.q;
    if (f.owner && f.scope !== 'mine') query.user_id = f.owner;
    query.scope = f.scope === 'mine' ? 'mine' : 'auto';

    const params = new URLSearchParams(query).toString();
    const data = await api('/api/reports?' + params);
    if (seq !== routeSeq) return;
    const card = $('#reports-card');
    if (!card) return;
    const showsOwner = data.scope === 'all';
    if (!data.items.length) {
      card.innerHTML = `
        <div class="empty-state">
          <div class="big">${icon('file', 40)}</div>
          <h3>Отчётов пока нет</h3>
          <p>Создайте первый авансовый отчёт — он сохранится на сервере и станет доступен для печати и отправки.</p>
          <button class="btn btn-primary" id="btn-new-empty">${icon('plus', 16)} Создать отчёт</button>
        </div>`;
      const btn = $('#btn-new-empty');
      if (btn) btn.addEventListener('click', () => navigate('#/reports/new'));
      return;
    }
    const canDelete = state.user.role === 'admin';
    card.innerHTML = `
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>Номер</th>
              <th>Дата</th>
              ${showsOwner ? '<th>Сотрудник</th>' : ''}
              <th>Подотчётное лицо</th>
              <th>Назначение</th>
              <th class="num">К утверждению</th>
              <th>Статус</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${data.items.map((report) => `
              <tr>
                <td class="nowrap"><a href="#/reports/${report.id}"><b>${esc(report.number)}</b></a></td>
                <td class="nowrap">${fmtDate(report.report_date)}</td>
                ${showsOwner ? `<td>${esc(report.owner.full_name)}</td>` : ''}
                <td>${esc(report.person_name)}
                  ${report.person_position ? `<br><small>${esc(report.person_position)}</small>` : ''}</td>
                <td>${esc(report.purpose)}</td>
                <td class="num">${fmtMoney(report.totals.approved_cents)}</td>
                <td>${statusBadge(report)}
                  ${report.sent_at ? `<br><small>${fmtDateTime(report.sent_at)}</small>` : ''}</td>
                <td class="actions">
                  <button class="btn btn-sm" data-action="open" data-id="${report.id}">Открыть</button>
                  <button class="btn btn-sm" data-action="print" data-id="${report.id}"
                          title="Печать">${icon('print', 14)}</button>
                  <button class="btn btn-sm" data-action="pdf" data-id="${report.id}"
                          title="Скачать PDF">${icon('file', 14)}</button>
                  <button class="btn btn-sm" data-action="excel" data-id="${report.id}"
                          title="Скачать Excel">${icon('download', 14)}</button>
                  <button class="btn btn-sm" data-action="email" data-id="${report.id}"
                          title="Отправить по почте">${icon('mail', 14)}</button>
                  ${canDelete ? `<button class="btn btn-sm btn-danger" data-action="delete"
                          data-id="${report.id}" title="Удалить">${icon('trash', 14)}</button>` : ''}
                </td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
      <div class="list-summary">
        <span>Всего отчётов: <b>${data.total}</b></span>
        <span>Сумма к утверждению: <b>${fmtMoney(data.total_amount_cents)} руб.</b></span>
        ${data.scope === 'all' ? '<span>Показаны отчёты всех сотрудников</span>' : ''}
      </div>`;

    const tableHost = card.querySelector('.table-wrap');
    tableHost.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-action]');
      if (!button) return;
      const id = Number(button.dataset.id);
      const action = button.dataset.action;
      if (action === 'open') return navigate('#/reports/' + id);
      if (action === 'print') return printReportById(id);
      if (action === 'pdf') return safe(() => downloadFile(`/api/reports/${id}/pdf`));
      if (action === 'excel') return safe(() => downloadFile(`/api/reports/${id}/excel`));
      if (action === 'email') return openEmailModal(id);
      if (action === 'delete') return deleteReport(id);
    });
  }

  async function deleteReport(id) {
    const ok = await confirmDialog(
      'Удалить отчёт?',
      'Действие необратимо: отчёт будет удалён с сервера без возможности восстановления. ' +
      'Удалять отчёты может только администратор.',
      'Удалить',
      true,
    );
    if (!ok) return;
    await safe(async () => {
      await api(`/api/reports/${id}`, { method: 'DELETE' });
      toast('Отчёт удалён', 'success');
      if (location.hash === '#/reports/' + id) navigate('#/reports');
      else loadReportsTable(++routeSeq);
    });
  }

  // -----------------------------------------------------------------------
  // Документ отчёта (просмотр и печать)
  // -----------------------------------------------------------------------
  function approvalBlockHtml(report) {
    return `
      <div class="doc-approve">
        <div class="approve-title">УТВЕРЖДАЮ</div>
        <div class="approve-sum">Отчет в сумме:
          <span class="approve-amount">${esc(report.amount_words || '')}</span>
        </div>
        <div class="doc-sign-grid">
          <div class="lbl">${esc(report.director_position || 'Директор')}</div>
          <div class="line"></div>
          <div class="name">${esc(report.director_name || '')}</div>
        </div>
        <div class="doc-hints">
          <span>(должность)</span><span>(подпись, фамилия, инициалы)</span>
        </div>
      </div>`;
  }

  function amountsTableHtml(report) {
    const totals = report.totals || {};
    const advances = report.advances || [];
    return `
      <table class="doc-table doc-amounts">
        <colgroup><col class="c1"><col class="c2"></colgroup>
        <thead>
          <tr><th>Наименование показателя</th><th>Сумма, руб. коп</th></tr>
        </thead>
        <tbody>
          <tr>
            <td class="lbl">Получено (дата):</td>
            <td class="num">${advances.length ? '' : '—'}</td>
          </tr>
          ${advances.map((advance) => `
            <tr>
              <td class="lbl">&nbsp;&nbsp;&nbsp;${fmtDate(advance.date)}</td>
              <td class="num">${fmtMoney(advance.amount_cents)}</td>
            </tr>`).join('')}
          <tr class="total">
            <td class="lbl">Итого получено</td>
            <td class="num">${fmtMoney(totals.received_cents)}</td>
          </tr>
          <tr>
            <td class="lbl">Израсходовано</td>
            <td class="num">${fmtMoney(totals.spent_cents)}</td>
          </tr>
          <tr>
            <td class="lbl">Остаток денежных средств (к возврату) / - Перерасход (к возмещению)</td>
            <td class="num">${fmtMoney(totals.balance_cents)}</td>
          </tr>
        </tbody>
      </table>`;
  }

  function expensesTableHtml(report) {
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
        <colgroup>
          <col class="d1"><col class="d2"><col class="d3"><col class="d4"><col class="d5">
        </colgroup>
        <thead>
          <tr>
            <th colspan="3">Документ, подтверждающий приобретение товаров (работ, услуг)</th>
            <th rowspan="2">Кому, за что уплачено. Иная информация (при необходимости)</th>
            <th rowspan="2">Сумма, руб. коп</th>
          </tr>
          <tr>
            <th>Дата</th>
            <th>Наименование документа</th>
            <th>Номер</th>
          </tr>
        </thead>
        <tbody>${rows.join('')}</tbody>
        <tfoot>
          <tr class="total">
            <td colspan="4" class="center">Итого</td>
            <td class="num">${fmtMoney(totals.spent_cents)}</td>
          </tr>
        </tfoot>
      </table>`;
  }

  function signaturesHtml(report) {
    return `
      <div class="doc-signs">
        <div class="row">
          <div class="lbl">Подотчетное лицо</div>
          <div class="line"></div>
          <div class="name">${esc(report.person_name)}</div>
        </div>
        <div class="hints">
          <span></span><span>(подпись)</span><span>(расшифровка подписи)</span>
        </div>
        <div class="checked">
          <span>Отчет проверен. К утверждению в сумме:</span>
          <span class="amount">${fmtMoney(report.totals.approved_cents)}</span>
          <span>руб.коп</span>
        </div>
        <div class="row">
          <div class="lbl">${esc(report.accountant_position || 'Бухгалтер')}</div>
          <div class="line"></div>
          <div class="name">${esc(report.accountant_name || '')}</div>
        </div>
        <div class="hints">
          <span></span><span>(подпись)</span><span>(подпись, фамилия, инициалы)</span>
        </div>
      </div>`;
  }

  function documentHtml(report) {
    return `
      <div class="doc" id="report-document">
        <div class="doc-top">
          <div class="doc-org">${esc(report.org_name || '')}</div>
          ${approvalBlockHtml(report)}
        </div>
        <div class="doc-title">Отчет об израсходованных суммах</div>
        <div class="doc-datebar">
          <span class="doc-no">№ ${esc(report.number)}</span>
          <span class="doc-date">от <span class="q">«</span>${parseIsoDate(report.report_date) ? parseIsoDate(report.report_date).day : ''}<span class="q">»</span>
            ${parseIsoDate(report.report_date) ? MONTHS[parseIsoDate(report.report_date).month - 1] : ''}
            ${parseIsoDate(report.report_date) ? parseIsoDate(report.report_date).year : ''} г.</span>
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

        ${amountsTableHtml(report)}
        ${expensesTableHtml(report)}
        ${signaturesHtml(report)}

        <div class="doc-foot">
          Отчёт № ${esc(report.number)} · сформирован ${fmtDateTime(report.created_at)}
        </div>
      </div>`;
  }

  // -----------------------------------------------------------------------
  // Просмотр отчёта
  // -----------------------------------------------------------------------
  async function renderReportView(id, seq) {
    setTitle('Авансовый отчёт');
    const report = await api('/api/reports/' + id);
    if (seq !== routeSeq) return;
    document.body.classList.add('viewing-report');
    const isAdmin = state.user.role === 'admin';
    const canEmail = true;
    const sentInfo = report.sent_at
      ? `<div class="notice success mb0">Отправлен ${fmtDateTime(report.sent_at)}
           ${report.sent_to ? ' на ' + esc(report.sent_to) : ''}</div>`
      : '';
    const emailError = (report.email_status || '').startsWith('error')
      ? `<div class="notice error">Последняя отправка не удалась: ${esc(report.email_status.slice(7))}</div>`
      : '';

    content().innerHTML = `
      <div class="card no-print">
        <div class="card-head" style="margin-bottom:0">
          <div>
            <h2 style="margin-bottom:2px">Отчёт № ${esc(report.number)}</h2>
            <div class="text-muted" style="font-size:13px">
              ${esc(report.owner.full_name)} · создан ${fmtDateTime(report.created_at)}
              · статус: ${report.status === 'sent' ? 'отправлен' : 'сохранён'}
            </div>
          </div>
          <div class="spacer"></div>
          <div class="flex">
            <a class="btn" href="#/reports">${icon('back', 15)} К списку</a>
            <button class="btn" id="btn-print" type="button">${icon('print', 15)} Печать</button>
            <button class="btn" id="btn-pdf" type="button">${icon('file', 15)} PDF</button>
            <button class="btn" id="btn-excel" type="button">${icon('download', 15)} Excel</button>
            ${canEmail ? `<button class="btn" id="btn-email" type="button">${icon('mail', 15)} Отправить</button>` : ''}
            <button class="btn" id="btn-copy" type="button">${icon('plus', 15)} Новый на основе</button>
            ${isAdmin ? `<button class="btn btn-danger" id="btn-delete" type="button">${icon('trash', 15)} Удалить</button>` : ''}
          </div>
        </div>
        ${sentInfo ? '<div style="margin-top:12px">' + sentInfo + '</div>' : ''}
        ${emailError}
        <div class="notice info" style="margin:14px 0 0">
          Сохранённый отчёт нельзя изменить — можно создать новый отчёт на его основе
          или с нуля.
        </div>
      </div>
      <div class="doc-wrap">${documentHtml(report)}</div>`;

    $('#btn-print').addEventListener('click', () => printReport(report));
    $('#btn-pdf').addEventListener('click', () => safe(() =>
      downloadFile(`/api/reports/${report.id}/pdf`)));
    $('#btn-excel').addEventListener('click', () => safe(() =>
      downloadFile(`/api/reports/${report.id}/excel`)));
    $('#btn-email').addEventListener('click', () => openEmailModal(report.id));
    $('#btn-copy').addEventListener('click', () => {
      state.pendingSource = report;
      navigate('#/reports/new');
    });
    if (isAdmin) $('#btn-delete').addEventListener('click', () => deleteReport(report.id));
  }

  async function printReportById(id) {
    await safe(async () => {
      const report = await api('/api/reports/' + id);
      printReport(report);
    });
  }

  function printReport(report) {
    const styles = '<link rel="stylesheet" href="/static/styles.css">';
    const title = 'Авансовый отчёт № ' + report.number;
    const markup = documentHtml(report);
    const html = '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">' +
      '<title>' + esc(title) + '</title>' + styles +
      '<style>@page{size:A4 portrait;margin:8mm;} body{background:#fff;padding:0;margin:0;}' +
      '.print-toolbar{position:sticky;top:0;display:flex;gap:10px;justify-content:flex-end;' +
      'padding:10px 14px;background:#f4f7fa;border-bottom:1px solid #dbe3ea;}' +
      '.print-wrap{padding:10px 0 24px;} .doc{box-shadow:none;margin:0 auto;}' +
      '@media print{.print-toolbar{display:none;} .print-wrap{padding:0;} .doc{padding:0;}}</style>' +
      '</head><body><div class="print-toolbar no-print">' +
      '<button class="btn" onclick="window.close()">Закрыть</button>' +
      '<button class="btn btn-primary" onclick="window.print()">Печать</button>' +
      '</div><div class="print-wrap">' + markup + '</div>' +
      '<script>window.addEventListener("load",function(){setTimeout(function(){window.print();},420);});<\/script>' +
      '</body></html>';

    const win = window.open('', '_blank');
    if (!win) {
      printViaIframe(markup);
      return;
    }
    win.document.open();
    win.document.write(html);
    win.document.close();
  }

  function printViaIframe(markup) {
    const frame = document.createElement('iframe');
    frame.style.position = 'fixed';
    frame.style.right = '0';
    frame.style.bottom = '0';
    frame.style.width = '0';
    frame.style.height = '0';
    frame.style.border = '0';
    document.body.appendChild(frame);
    const doc = frame.contentWindow.document;
    doc.open();
    doc.write('<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">' +
      '<link rel="stylesheet" href="/static/styles.css">' +
      '<style>@page{size:A4 portrait;margin:8mm;}</style></head><body>' + markup + '</body></html>');
    doc.close();
    setTimeout(() => {
      try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch (err) { /* ignore */ }
      setTimeout(() => frame.remove(), 2000);
    }, 300);
  }

  // -----------------------------------------------------------------------
  // Редактор отчёта
  // -----------------------------------------------------------------------
  function emptyDraft(report) {
    const source = report || {};
    const settings = state.settings || {};
    return {
      report_date: source.report_date || todayIso(),
      person_name: source.person_name || state.user.full_name || '',
      person_position: source.person_position || state.user.position || '',
      purpose: source.purpose || (settings.purposes && settings.purposes[0]) || 'Командировочные расходы',
      advances: source.advances
        ? source.advances.map((row) => ({ date: row.date || '', amount: (row.amount_cents / 100).toFixed(2).replace('.', ',') }))
        : [{ date: todayIso(), amount: '' }],
      expenses: source.expenses
        ? source.expenses.map((row) => ({
          date: row.date || '',
          document: row.document || '',
          document_number: row.document_number || '',
          purpose: row.purpose || '',
          amount: (row.amount_cents / 100).toFixed(2).replace('.', ','),
        }))
        : [blankExpense(), blankExpense(), blankExpense()],
    };
  }

  function blankExpense() {
    return { date: '', document: '', document_number: '', purpose: '', amount: '' };
  }

  function draftKey() {
    return DRAFT_PREFIX + (state.user ? state.user.id : 'anon');
  }

  function loadDraft() {
    try {
      const raw = localStorage.getItem(draftKey());
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || !parsed.report_date) return null;
      return parsed;
    } catch (err) {
      return null;
    }
  }

  function saveDraft() {
    if (!state.editor) return;
    try {
      localStorage.setItem(draftKey(), JSON.stringify(state.editor.draft));
    } catch (err) { /* приватный режим */ }
  }

  const saveDraftDebounced = debounce(saveDraft, 400);

  function clearDraft() {
    try { localStorage.removeItem(draftKey()); } catch (err) { /* ignore */ }
  }

  async function renderEditor(source, seq) {
    const origin = source || state.pendingSource || null;
    state.pendingSource = null;
    setTitle(origin ? 'Отчёт на основе сохранённого' : 'Новый авансовый отчёт');
    let draft = origin ? emptyDraft(origin) : loadDraft();
    const restored = !origin && draft;
    if (!draft) draft = emptyDraft(null);
    state.editor = { draft, source: origin };
    content().innerHTML = `
      ${restored ? `<div class="notice info">Восстановлен несохранённый черновик.
        <button class="btn btn-sm" id="btn-drop-draft" type="button">Начать заново</button></div>` : ''}
      <div class="doc-editor-bar no-print">
        <div class="title">${origin ? 'Новый отчёт на основе № ' + esc(origin.number) : 'Заполнение отчёта'}</div>
        <div class="totals">
          Израсходовано: <b data-total-label="spent">0,00</b> ·
          К утверждению: <b data-total-label="approved">0,00</b> руб.
        </div>
        <button class="btn" id="btn-cancel" type="button">Отмена</button>
        <button class="btn btn-primary" id="btn-save" type="button">
          ${icon('check', 16)} Сохранить отчёт
        </button>
      </div>
      <div class="notice warn" id="editor-hint" style="display:none"></div>
      <div class="doc-wrap"><div class="doc" id="editor-doc"></div></div>`;

    if (restored) {
      const drop = $('#btn-drop-draft');
      if (drop) drop.addEventListener('click', () => {
        clearDraft();
        state.editor.draft = emptyDraft(null);
        renderEditorBody();
        const notice = drop.closest('.notice');
        if (notice) notice.remove();
      });
    }
    $('#btn-cancel').addEventListener('click', async () => {
      const ok = await confirmDialog('Выйти без сохранения?',
        'Несохранённые изменения будут потеряны (черновик останется на этом компьютере).',
        'Выйти');
      if (ok) navigate('#/reports');
    });
    $('#btn-save').addEventListener('click', saveReport);

    renderEditorBody();
    document.addEventListener('keydown', editorKeydown);
  }

  function editorKeydown(event) {
    if (!state.editor) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      saveReport();
    }
  }

  function renderEditorBody() {
    const draft = state.editor.draft;
    const doc = $('#editor-doc');
    if (!doc) return;
    const purposes = (state.settings && state.settings.purposes) || [];
    const advances = draft.advances.map((row, index) => `
      <tr>
        <td class="cell-td">
          <input class="cell-input" type="date" data-path="advances.${index}.date" value="${esc(row.date)}">
        </td>
        <td class="cell-td num">
          <input class="cell-input" type="text" inputmode="decimal" placeholder="0,00"
                 data-path="advances.${index}.amount" data-money="1" value="${esc(row.amount)}">
        </td>
        <td class="cell-td" style="width:7mm;border-left:none">
          ${draft.advances.length > 1 ? `<div class="row-tools">
            <button type="button" data-remove-advance="${index}" title="Удалить строку">✕</button>
          </div>` : ''}
        </td>
      </tr>`).join('');

    const expenses = draft.expenses.map((row, index) => `
      <tr>
        <td class="cell-td">
          <input class="cell-input" type="text" data-path="expenses.${index}.date"
                 placeholder="дд.мм.гггг" value="${esc(row.date)}">
        </td>
        <td class="cell-td">
          <input class="cell-input" type="text" data-path="expenses.${index}.document"
                 placeholder="Чек, билет…" value="${esc(row.document)}">
        </td>
        <td class="cell-td">
          <input class="cell-input" type="text" data-path="expenses.${index}.document_number"
                 value="${esc(row.document_number)}">
        </td>
        <td class="cell-td">
          <input class="cell-input" type="text" data-path="expenses.${index}.purpose"
                 placeholder="Кому, за что уплачено" value="${esc(row.purpose)}">
        </td>
        <td class="cell-td num">
          <input class="cell-input" type="text" inputmode="decimal" placeholder="0,00"
                 data-path="expenses.${index}.amount" data-money="1" value="${esc(row.amount)}">
        </td>
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
          <div class="approve-sum">Отчет в сумме:
            <span class="approve-amount" data-words></span>
          </div>
          <div class="doc-sign-grid">
            <div class="lbl">${esc((state.settings && state.settings.director_position) || 'Директор')}</div>
            <div class="line"></div>
            <div class="name">${esc((state.settings && state.settings.director_name) || '')}</div>
          </div>
          <div class="doc-hints">
            <span>(должность)</span><span>(подпись, фамилия, инициалы)</span>
          </div>
        </div>
      </div>
      <div class="doc-title">Отчет об израсходованных суммах</div>
      <div class="doc-datebar">
        <span class="doc-no">Новый отчёт</span>
        <span class="doc-date">от <span class="q">«</span><span data-date-day></span><span class="q">»</span>
          <span data-date-month></span> <span data-date-year></span> г.</span>
      </div>

      <div class="doc-fields">
        <div class="doc-field">
          <div class="lbl">Подотчетное лицо</div>
          <input class="cell-input" type="text" data-path="person_name"
                 placeholder="Фамилия Имя Отчество" value="${esc(draft.person_name)}" required>
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
        <thead>
          <tr><th>Наименование показателя</th><th>Сумма, руб. коп</th></tr>
        </thead>
        <tbody>
          <tr><td class="lbl">Получено (дата):</td><td class="num">—</td></tr>
          ${advances}
          <tr class="total">
            <td class="lbl">Итого получено</td>
            <td class="num" data-total="received">0,00</td>
          </tr>
          <tr>
            <td class="lbl">Израсходовано</td>
            <td class="num" data-total="spent">0,00</td>
          </tr>
          <tr>
            <td class="lbl">Остаток денежных средств (к возврату) / - Перерасход (к возмещению)</td>
            <td class="num" data-total="balance">0,00</td>
          </tr>
        </tbody>
      </table>
      ${draft.advances.length < MAX_ADVANCES ? `
        <div class="add-row no-print">
          <button class="btn btn-sm" type="button" id="btn-add-advance">+ Добавить строку аванса</button>
        </div>` : ''}

      <table class="doc-table doc-expenses">
        <colgroup>
          <col class="d1"><col class="d2"><col class="d3"><col class="d4"><col class="d5">
        </colgroup>
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
          <tr class="total">
            <td colspan="4" class="center">Итого</td>
            <td class="num" data-total="spent">0,00</td>
          </tr>
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
        <div class="hints">
          <span></span><span>(подпись)</span><span>(расшифровка подписи)</span>
        </div>
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
        <div class="hints">
          <span></span><span>(подпись)</span><span>(подпись, фамилия, инициалы)</span>
        </div>
      </div>`;

    if (!doc.dataset.bound) {
      doc.dataset.bound = '1';
      doc.addEventListener('input', onEditorInput);
      doc.addEventListener('change', onEditorChange);
      doc.addEventListener('blur', onEditorBlur, true);
      doc.addEventListener('click', onEditorClick);
    }
    refreshTotals();
    refreshDateLine();
  }

  function onEditorBlur(event) {
    const input = event.target;
    if (input instanceof HTMLInputElement && input.dataset.money) {
      normalizeAmountInput(input);
    }
  }

  function onEditorInput(event) {
    const input = event.target;
    if (!input || !input.dataset || !input.dataset.path) return;
    const path = input.dataset.path;
    if (path === 'report_date') {
      state.editor.draft.report_date = input.value;
      refreshDateLine();
    } else if (path === 'person_name' || path === 'person_position' || path === 'purpose') {
      state.editor.draft[path] = input.value;
      if (path === 'person_name') {
        const sign = $('[data-sign-person]');
        if (sign) sign.textContent = input.value;
      }
    } else {
      const parts = path.split('.');
      const index = Number(parts[1]);
      if (parts[0] === 'advances') state.editor.draft.advances[index][parts[2]] = input.value;
      if (parts[0] === 'expenses') state.editor.draft.expenses[index][parts[2]] = input.value;
    }
    input.classList.remove('invalid');
    refreshTotals();
    saveDraftDebounced();
  }

  function onEditorChange(event) {
    const input = event.target;
    if (input && input.dataset && input.dataset.path === 'report_date') refreshDateLine();
  }

  function onEditorClick(event) {
    const addAdvance = event.target.closest('#btn-add-advance');
    if (addAdvance) {
      state.editor.draft.advances.push({ date: '', amount: '' });
      renderEditorBody();
      return;
    }
    const addExpense = event.target.closest('#btn-add-expense');
    if (addExpense) {
      state.editor.draft.expenses.push(blankExpense());
      renderEditorBody();
      return;
    }
    const removeAdvance = event.target.closest('[data-remove-advance]');
    if (removeAdvance) {
      state.editor.draft.advances.splice(Number(removeAdvance.dataset.removeAdvance), 1);
      renderEditorBody();
      return;
    }
    const removeExpense = event.target.closest('[data-remove-expense]');
    if (removeExpense) {
      state.editor.draft.expenses.splice(Number(removeExpense.dataset.removeExpense), 1);
      renderEditorBody();
    }
  }

  function currentTotals() {
    const draft = state.editor ? state.editor.draft : null;
    if (!draft) return { received: 0, spent: 0, balance: 0, approved: 0 };
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
    const totals = currentTotals();
    $$('[data-total]').forEach((node) => {
      node.textContent = fmtMoney(totals[node.dataset.total]);
    });
    const words = $('[data-words]');
    if (words) words.textContent = amountInWords(totals.approved);
    $$('[data-total-label]').forEach((node) => {
      node.textContent = fmtMoney(totals[node.dataset.totalLabel]);
    });
  }

  function refreshDateLine() {
    const draft = state.editor ? state.editor.draft : null;
    if (!draft) return;
    const d = parseIsoDate(draft.report_date);
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

  function showEditorHint(message) {
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
    const draft = state.editor.draft;
    if (!draft.report_date) {
      markInvalid('report_date');
      throw new Error('Укажите дату составления отчёта');
    }
    if (!draft.person_name || draft.person_name.trim().length < 3) {
      markInvalid('person_name');
      throw new Error('Укажите подотчётное лицо (фамилия, инициалы)');
    }
    if (!draft.purpose) {
      markInvalid('purpose');
      throw new Error('Выберите назначение аванса');
    }

    const advances = [];
    draft.advances.forEach((row, index) => {
      // Строка без суммы считается незаполненной и в отчёт не попадает
      if (!String(row.amount).trim()) return;
      const amount = parseCents(row.amount);
      if (!Number.isFinite(amount) || amount <= 0) {
        markInvalid(`advances.${index}.amount`);
        throw new Error(`Укажите сумму полученного аванса в строке ${index + 1}`);
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
      if (!row.purpose || !row.purpose.trim()) {
        markInvalid(`expenses.${index}.purpose`);
        throw new Error(`Заполните «Кому, за что уплачено» в строке ${index + 1}`);
      }
      if (!row.date || !row.date.trim()) {
        markInvalid(`expenses.${index}.date`);
        throw new Error(`Укажите дату документа в строке ${index + 1}`);
      }
      expenses.push({
        date: row.date.trim(),
        document: row.document.trim(),
        document_number: row.document_number.trim(),
        purpose: row.purpose.trim(),
        amount: String(row.amount).replace(',', '.'),
      });
    });

    if (!expenses.length) {
      throw new Error('Добавьте хотя бы одну строку расходов');
    }

    return {
      report_date: draft.report_date,
      person_name: draft.person_name.trim(),
      person_position: (draft.person_position || '').trim(),
      purpose: draft.purpose,
      advances,
      expenses,
    };
  }

  async function saveReport() {
    if (!state.editor) return;
    const button = $('#btn-save');
    let payload;
    try {
      payload = buildPayload();
      showEditorHint('');
    } catch (err) {
      showEditorHint(err.message);
      toast(err.message, 'error');
      return;
    }
    setBusy(button, true, 'Сохранение…');
    try {
      const report = await api('/api/reports', { method: 'POST', body: payload });
      clearDraft();
      state.editor = null;
      document.removeEventListener('keydown', editorKeydown);
      toast('Отчёт сохранён. Теперь его можно распечатать или отправить.', 'success', 5000);
      navigate('#/reports/' + report.id);
    } catch (err) {
      showEditorHint(err.message);
      toast(err.message, 'error');
    } finally {
      setBusy(button, false);
    }
  }

  // -----------------------------------------------------------------------
  // Отправка по почте
  // -----------------------------------------------------------------------
  async function openEmailModal(reportId) {
    const report = await api('/api/reports/' + reportId);
    const defaultRecipient = (state.settings && state.settings.default_recipient) || '';
    const smtp = (state.settings && state.settings.smtp) || {};
    const smtpReady = !!smtp.host;
    const modal = openModal({
      title: 'Отправить отчёт по почте',
      body: `
        <p class="text-muted" style="font-size:13.5px">
          Отчёт № ${esc(report.number)} от ${fmtDate(report.report_date)} будет отправлен
          вложением в формате Excel вместе с краткой сводкой.
        </p>
        <div class="field">
          <label for="email-to">Получатели</label>
          <input type="text" id="email-to" value="${esc(defaultRecipient)}"
                 placeholder="responsible@example.com">
          <span class="hint">Несколько адресов можно указать через запятую.</span>
        </div>
        <div class="field">
          <label for="email-comment">Комментарий (необязательно)</label>
          <textarea id="email-comment" placeholder="Например: прошу утвердить отчёт"></textarea>
        </div>
        <label class="checkbox" for="email-print">
          <input type="checkbox" id="email-print"> Открыть бланк для печати после отправки
        </label>
        <div class="notice warn" id="email-warning"
             style="${defaultRecipient ? 'display:none' : ''}">
          Получатель не задан в настройках — укажите адрес вручную.
        </div>
        <div class="notice error"${smtpReady ? ' style="display:none"' : ''}>
          Почтовый сервер (SMTP) не настроен. Отправка станет доступна после
          настройки в разделе «Настройки» — обратитесь к администратору.
        </div>`,
      actions: `
        <button class="btn" data-act="cancel">Отмена</button>
        <button class="btn btn-primary" data-act="send" ${smtpReady ? '' : 'disabled'}>
          ${icon('mail', 16)} Отправить</button>`,
    });

    const send = async (button) => {
      const to = $('#email-to').value.trim();
      if (!to) {
        toast('Укажите адрес получателя', 'error');
        $('#email-to').focus();
        return;
      }
      const alsoPrint = $('#email-print').checked;
      setBusy(button, true, 'Отправка…');
      try {
        const result = await api(`/api/reports/${reportId}/email`, {
          method: 'POST',
          body: { to, comment: $('#email-comment').value.trim() },
        });
        closeModal();
        toast('Письмо отправлено' + (to ? ' на ' + result.recipients.join(', ') : ''), 'success');
        if (alsoPrint) printReport(result.report);
        if (location.hash === '#/reports/' + reportId) renderReportView(reportId, ++routeSeq);
        else loadReportsTable(++routeSeq);
      } catch (err) {
        toast(err.message, 'error', 8000);
      } finally {
        setBusy(button, false);
      }
    };

    modal.addEventListener('click', (event) => {
      const button = event.target.closest('[data-act]');
      if (!button) return;
      if (button.dataset.act === 'cancel') closeModal();
      if (button.dataset.act === 'send') send(button);
    });
    $('#email-to').focus();
  }

  // -----------------------------------------------------------------------
  // Пользователи
  // -----------------------------------------------------------------------
  async function renderUsers(seq) {
    setTitle('Пользователи');
    if (state.user.role !== 'admin' && state.user.role !== 'supervisor') {
      content().innerHTML = '<div class="notice error">Недостаточно прав</div>';
      return;
    }
    const data = await api('/api/users');
    if (seq !== routeSeq) return;
    state.users = data.items;
    const isAdmin = state.user.role === 'admin';
    content().innerHTML = `
      <div class="card">
        <div class="card-head">
          <h2>Учётные записи</h2>
          <div class="spacer"></div>
          <button class="btn btn-primary" id="btn-add-user" type="button">
            ${icon('plus', 16)} Создать пользователя
          </button>
        </div>
        <p class="card-sub">
          ${isAdmin
            ? 'Администратор может создавать пользователей с любой ролью, блокировать и удалять учётные записи.'
            : 'Супервайзер может создавать обычных пользователей и задавать им новый пароль.'}
        </p>
        <div class="table-wrap" id="users-table">
          <table class="data">
            <thead>
              <tr>
                <th>Сотрудник</th>
                <th>Логин</th>
                <th>Должность</th>
                <th>E-mail</th>
                <th>Роль</th>
                <th class="num">Отчётов</th>
                <th>Состояние</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${data.items.map((user) => `
                <tr>
                  <td><b>${esc(user.full_name)}</b></td>
                  <td class="mono">${esc(user.username)}</td>
                  <td>${esc(user.position || '—')}</td>
                  <td>${esc(user.email || '—')}</td>
                  <td><span class="badge role-${esc(user.role)}">${esc(user.role_label)}</span></td>
                  <td class="num">${user.report_count}</td>
                  <td>${user.is_active
                    ? '<span class="badge sent">Активен</span>'
                    : '<span class="badge inactive">Заблокирован</span>'}
                    ${user.must_change_password ? '<br><small class="text-muted">сменит пароль</small>' : ''}</td>
                  <td class="actions">
                    <button class="btn btn-sm" data-user-action="password" data-id="${user.id}">
                      Пароль</button>
                    ${isAdmin ? `
                      <button class="btn btn-sm" data-user-action="toggle" data-id="${user.id}"
                              data-active="${user.is_active ? '1' : '0'}">
                        ${user.is_active ? 'Заблокировать' : 'Разблокировать'}</button>
                      <button class="btn btn-sm btn-danger" data-user-action="delete" data-id="${user.id}"
                              title="Удалить">${icon('trash', 14)}</button>` : ''}
                  </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>`;

    $('#btn-add-user').addEventListener('click', () => openUserModal());
    $('#users-table').addEventListener('click', async (event) => {
      const button = event.target.closest('[data-user-action]');
      if (!button) return;
      const id = Number(button.dataset.id);
      const action = button.dataset.userAction;
      const target = data.items.find((item) => item.id === id);
      if (!target) return;
      if (action === 'password') openPasswordModal(target);
      if (action === 'toggle') {
        await safe(async () => {
          await api('/api/users/' + id, {
            method: 'PATCH',
            body: { is_active: button.dataset.active !== '1' },
          });
          toast(button.dataset.active === '1' ? 'Учётная запись заблокирована' : 'Учётная запись разблокирована',
            'success');
          state.users = null;
          renderUsers(++routeSeq);
        });
      }
      if (action === 'delete') {
        const ok = await confirmDialog('Удалить пользователя?',
          `Учётная запись «${target.full_name}» будет удалена безвозвратно. ` +
          'Если у сотрудника есть отчёты, удаление невозможно — используйте блокировку.',
          'Удалить', true);
        if (!ok) return;
        await safe(async () => {
          await api('/api/users/' + id, { method: 'DELETE' });
          toast('Пользователь удалён', 'success');
          state.users = null;
          renderUsers(++routeSeq);
        });
      }
    });
  }

  function openUserModal() {
    const isAdmin = state.user.role === 'admin';
    const roleOptions = isAdmin
      ? `<option value="user" selected>Пользователь</option>
         <option value="supervisor">Супервайзер</option>
         <option value="admin">Администратор</option>`
      : '<option value="user" selected>Пользователь</option>';
    const modal = openModal({
      title: 'Новый пользователь',
      wide: true,
      body: `
        <div class="field-row">
          <div class="field">
            <label for="u-username">Логин</label>
            <input type="text" id="u-username" placeholder="ivanov" autocapitalize="none" spellcheck="false">
            <span class="hint">3–32 символа: латиница, цифры, «.», «-», «_».</span>
          </div>
          <div class="field">
            <label for="u-role">Роль</label>
            <select id="u-role">${roleOptions}</select>
          </div>
        </div>
        <div class="field">
          <label for="u-name">ФИО</label>
          <input type="text" id="u-name" placeholder="Иванов Иван Иванович">
        </div>
        <div class="field-row">
          <div class="field">
            <label for="u-position">Должность</label>
            <input type="text" id="u-position">
          </div>
          <div class="field">
            <label for="u-email">E-mail</label>
            <input type="email" id="u-email" placeholder="ivanov@example.com">
          </div>
        </div>
        <div class="field-row">
          <div class="field">
            <label for="u-password">Пароль</label>
            <input type="password" id="u-password" autocomplete="new-password">
            <span class="hint">Не менее 8 символов, буквы и цифры.</span>
          </div>
          <div class="field">
            <label for="u-password2">Повторите пароль</label>
            <input type="password" id="u-password2" autocomplete="new-password">
          </div>
        </div>
        <div class="notice info" style="margin-bottom:0">
          При первом входе пользователь увидит напоминание сменить пароль.
          Пользователь видит только свои отчёты; супервайзер и администратор — все.
        </div>`,
      actions: `
        <button class="btn" data-act="cancel">Отмена</button>
        <button class="btn btn-primary" data-act="create">Создать</button>`,
    });

    modal.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-act]');
      if (!button) return;
      if (button.dataset.act === 'cancel') return closeModal();
      if (button.dataset.act !== 'create') return;
      const password = $('#u-password').value;
      if (password !== $('#u-password2').value) {
        toast('Пароли не совпадают', 'error');
        return;
      }
      setBusy(button, true, 'Создание…');
      try {
        await api('/api/users', {
          method: 'POST',
          body: {
            username: $('#u-username').value.trim(),
            full_name: $('#u-name').value.trim(),
            position: $('#u-position').value.trim(),
            email: $('#u-email').value.trim(),
            role: $('#u-role').value,
            password,
          },
        });
        closeModal();
        toast('Пользователь создан', 'success');
        state.users = null;
        renderUsers(++routeSeq);
      } catch (err) {
        toast(err.message, 'error', 7000);
      } finally {
        setBusy(button, false);
      }
    });
    $('#u-username').focus();
  }

  function openPasswordModal(target) {
    const modal = openModal({
      title: 'Новый пароль',
      body: `
        <p class="text-muted" style="font-size:13.5px">
          Пользователь: <b>${esc(target.full_name)}</b> (${esc(target.username)})
        </p>
        <div class="field">
          <label for="p-password">Новый пароль</label>
          <input type="password" id="p-password" autocomplete="new-password">
          <span class="hint">Не менее 8 символов, буквы и цифры.</span>
        </div>
        <div class="field">
          <label for="p-password2">Повторите пароль</label>
          <input type="password" id="p-password2" autocomplete="new-password">
        </div>`,
      actions: `
        <button class="btn" data-act="cancel">Отмена</button>
        <button class="btn btn-primary" data-act="save">Сохранить пароль</button>`,
    });
    modal.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-act]');
      if (!button) return;
      if (button.dataset.act === 'cancel') return closeModal();
      const password = $('#p-password').value;
      if (password !== $('#p-password2').value) {
        toast('Пароли не совпадают', 'error');
        return;
      }
      setBusy(button, true, 'Сохранение…');
      try {
        await api('/api/users/' + target.id, { method: 'PATCH', body: { password } });
        closeModal();
        toast('Пароль изменён', 'success');
      } catch (err) {
        toast(err.message, 'error', 7000);
      } finally {
        setBusy(button, false);
      }
    });
    $('#p-password').focus();
  }

  // -----------------------------------------------------------------------
  // Настройки
  // -----------------------------------------------------------------------
  async function renderSettings(seq) {
    setTitle('Настройки');
    if (state.user.role !== 'admin') {
      content().innerHTML = '<div class="notice error">Раздел доступен только администратору</div>';
      return;
    }
    const [settingsData, systemInfo] = await Promise.all([
      api('/api/settings'),
      api('/api/system/info').catch(() => null),
    ]);
    if (seq !== routeSeq) return;
    const s = settingsData.settings;
    const smtp = s.smtp || {};
    content().innerHTML = `
      <form id="settings-form">
        <div class="card">
          <div class="card-head"><h2>Организация и подписи</h2></div>
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
              <label for="s-default-recipient">Ответственный по умолчанию</label>
              <input type="text" id="s-default-recipient" value="${esc(s.default_recipient)}"
                     placeholder="responsible@example.com">
              <span class="hint">Адрес подставляется при отправке отчёта.</span>
            </div>
            <div class="field">
              <label for="s-purposes">Назначение аванса (по одному в строке)</label>
              <textarea id="s-purposes">${esc((s.purposes || []).join('\n'))}</textarea>
            </div>
            <div class="field">
              <label for="s-session">Время жизни сессии, часов</label>
              <input type="number" id="s-session" min="1" max="720" value="${esc(s.session_hours || 12)}">
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head">
            <h2>Почтовый сервер (SMTP)</h2>
            <div class="spacer"></div>
            <span class="badge ${smtp.host ? 'sent' : 'muted'}">
              ${smtp.host ? 'Настроено' : 'Не настроено'}</span>
          </div>
          <p class="card-sub">Без SMTP-настроек отправка отчётов по почте недоступна.</p>
          <div class="settings-grid">
            <div class="field">
              <label for="smtp-host">Сервер</label>
              <input type="text" id="smtp-host" value="${esc(smtp.host || '')}" placeholder="smtp.example.com">
            </div>
            <div class="field">
              <label for="smtp-port">Порт</label>
              <input type="number" id="smtp-port" value="${esc(smtp.port || 587)}">
            </div>
            <div class="field">
              <label for="smtp-security">Тип защиты</label>
              <select id="smtp-security">
                <option value="starttls" ${smtp.security === 'starttls' ? 'selected' : ''}>STARTTLS (587)</option>
                <option value="ssl" ${smtp.security === 'ssl' ? 'selected' : ''}>SSL/TLS (465)</option>
                <option value="none" ${smtp.security === 'none' ? 'selected' : ''}>Без шифрования</option>
              </select>
            </div>
            <div class="field">
              <label for="smtp-username">Логин</label>
              <input type="text" id="smtp-username" value="${esc(smtp.username || '')}" autocomplete="off">
            </div>
            <div class="field">
              <label for="smtp-password">Пароль</label>
              <input type="password" id="smtp-password" autocomplete="new-password"
                     placeholder="${smtp.password_set ? 'пароль сохранён — оставьте пустым' : 'пароль'}">
            </div>
            <div class="field">
              <label for="smtp-from">Адрес отправителя</label>
              <input type="email" id="smtp-from" value="${esc(smtp.from_email || '')}"
                     placeholder="reports@example.com">
            </div>
            <div class="field">
              <label for="smtp-from-name">Имя отправителя</label>
              <input type="text" id="smtp-from-name" value="${esc(smtp.from_name || '')}">
            </div>
            <div class="field">
              <label for="smtp-subject">Префикс темы письма</label>
              <input type="text" id="smtp-subject" value="${esc(smtp.subject_prefix || '')}">
            </div>
          </div>
          <div class="flex" style="margin-top:6px">
            <button class="btn" id="btn-test-smtp" type="button">${icon('mail', 15)} Отправить тестовое письмо</button>
            <span class="text-muted" style="font-size:12.5px">Укажите получателя в поле «Ответственный по умолчанию».</span>
          </div>
        </div>

        <div class="flex" style="margin-bottom:18px">
          <button class="btn btn-primary" type="submit">${icon('check', 16)} Сохранить настройки</button>
          <span class="text-muted" style="font-size:12.5px">Изменения применяются сразу после сохранения.</span>
        </div>
      </form>

      <div class="card">
        <div class="card-head">
          <h2>Сервер и база данных</h2>
          <div class="spacer"></div>
          <button class="btn btn-sm" id="btn-backup" type="button">${icon('db', 15)} Резервная копия</button>
          <button class="btn btn-sm" id="btn-download-db" type="button">${icon('download', 15)} Скачать базу</button>
          <button class="btn btn-sm" id="btn-audit" type="button">Журнал действий</button>
        </div>
        ${systemInfo ? `
          <dl class="kv">
            <dt>Версия программы</dt><dd>${esc(systemInfo.version)}</dd>
            <dt>Каталог данных</dt><dd class="mono">${esc(systemInfo.data_dir)}</dd>
            <dt>Файл базы данных</dt><dd class="mono">${esc(systemInfo.db_path)}</dd>
            <dt>Размер базы</dt><dd>${(systemInfo.db_size / 1024).toFixed(1)} КБ</dd>
            <dt>Пользователей</dt><dd>${systemInfo.counts.users}</dd>
            <dt>Отчётов</dt><dd>${systemInfo.counts.reports} (отправлено: ${systemInfo.counts.sent})</dd>
            <dt>Резервные копии</dt><dd>${systemInfo.backups.length
              ? systemInfo.backups.map((b) => `${esc(b.name)} (${(b.size / 1024).toFixed(0)} КБ)`).join('<br>')
              : 'нет'}</dd>
          </dl>
          <div class="notice info" style="margin:14px 0 0">
            База данных хранится отдельно от программы, поэтому обновления и переустановка
            не удаляют отчёты. Перед обновлением создаётся резервная копия автоматически.
          </div>` : '<p class="text-muted">Не удалось получить сведения о сервере.</p>'}
      </div>`;

    const form = $('#settings-form');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button[type=submit]');
      setBusy(button, true, 'Сохранение…');
      try {
        const payload = {
          org_name: $('#s-org').value.trim(),
          director_position: $('#s-director-position').value.trim(),
          director_name: $('#s-director-name').value.trim(),
          accountant_position: $('#s-accountant-position').value.trim(),
          accountant_name: $('#s-accountant-name').value.trim(),
          default_recipient: $('#s-default-recipient').value.trim(),
          purposes: $('#s-purposes').value.split('\n').map((line) => line.trim()).filter(Boolean),
          session_hours: Number($('#s-session').value) || 12,
          smtp: {
            host: $('#smtp-host').value.trim(),
            port: Number($('#smtp-port').value) || 587,
            security: $('#smtp-security').value,
            username: $('#smtp-username').value.trim(),
            password: $('#smtp-password').value,
            from_email: $('#smtp-from').value.trim(),
            from_name: $('#smtp-from-name').value.trim(),
            subject_prefix: $('#smtp-subject').value.trim(),
          },
        };
        const data = await api('/api/settings', { method: 'PUT', body: payload });
        state.settings = data.settings;
        $('#smtp-password').value = '';
        toast('Настройки сохранены', 'success');
        renderSettings(++routeSeq);
      } catch (err) {
        toast(err.message, 'error', 7000);
      } finally {
        setBusy(button, false);
      }
    });

    $('#btn-test-smtp').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      const recipient = $('#s-default-recipient').value.trim();
      if (!recipient) {
        toast('Заполните поле «Ответственный по умолчанию»', 'error');
        $('#s-default-recipient').focus();
        return;
      }
      setBusy(button, true, 'Отправка…');
      try {
        await api('/api/settings/smtp/test', {
          method: 'POST',
          body: {
            recipient,
            smtp: {
              host: $('#smtp-host').value.trim(),
              port: Number($('#smtp-port').value) || 587,
              security: $('#smtp-security').value,
              username: $('#smtp-username').value.trim(),
              password: $('#smtp-password').value,
              from_email: $('#smtp-from').value.trim(),
              from_name: $('#smtp-from-name').value.trim(),
              subject_prefix: $('#smtp-subject').value.trim(),
            },
          },
        });
        toast('Тестовое письмо отправлено на ' + recipient, 'success');
      } catch (err) {
        toast(err.message, 'error', 9000);
      } finally {
        setBusy(button, false);
      }
    });

    $('#btn-backup').addEventListener('click', () => safe(async () => {
      const data = await api('/api/system/backup', { method: 'POST' });
      toast('Резервная копия создана: ' + data.file, 'success');
      renderSettings(++routeSeq);
    }));
    $('#btn-download-db').addEventListener('click', () => safe(async () => {
      await downloadFile('/api/system/backup/download');
    }));
    $('#btn-audit').addEventListener('click', openAuditModal);
  }

  async function openAuditModal() {
    const data = await api('/api/audit?limit=200');
    const labels = {
      'setup': 'Первичная настройка',
      'login': 'Вход',
      'logout': 'Выход',
      'password.change': 'Смена пароля',
      'profile.update': 'Изменение профиля',
      'report.create': 'Создание отчёта',
      'report.delete': 'Удаление отчёта',
      'report.email': 'Отправка отчёта',
      'report.email_failed': 'Ошибка отправки',
      'user.create': 'Создание пользователя',
      'user.update': 'Изменение пользователя',
      'user.delete': 'Удаление пользователя',
      'settings.update': 'Изменение настроек',
      'backup.create': 'Резервная копия',
      'update.install': 'Установка обновления',
    };
    openModal({
      title: 'Журнал действий',
      wide: true,
      body: `
        <div class="table-wrap" style="max-height:60vh;overflow-y:auto">
          <table class="data">
            <thead><tr><th>Время</th><th>Пользователь</th><th>Действие</th><th>Объект</th></tr></thead>
            <tbody>
              ${data.items.map((item) => `
                <tr>
                  <td class="nowrap">${fmtDateTime(item.ts)}</td>
                  <td>${esc(item.actor || '—')}</td>
                  <td>${esc(labels[item.action] || item.action)}</td>
                  <td class="mono">${esc(item.entity || '')}${item.entity_id ? ' #' + item.entity_id : ''}</td>
                </tr>`).join('') || '<tr><td colspan="4" class="text-muted">Записей нет</td></tr>'}
            </tbody>
          </table>
        </div>`,
      actions: '<button class="btn" data-act="close">Закрыть</button>',
    }).addEventListener('click', (event) => {
      if (event.target.closest('[data-act=close]')) closeModal();
    });
  }

  // -----------------------------------------------------------------------
  // Профиль
  // -----------------------------------------------------------------------
  async function renderProfile(seq) {
    setTitle('Профиль');
    const user = state.user;
    content().innerHTML = `
      ${user.must_change_password ? `
        <div class="notice warn">
          Вы вошли с паролем, выданным администратором. Смените его на свой.
        </div>` : ''}
      <div class="card">
        <div class="card-head"><h2>Личные данные</h2></div>
        <form id="profile-form">
          <div class="settings-grid">
            <div class="field">
              <label for="p-fullname">ФИО</label>
              <input type="text" id="p-fullname" value="${esc(user.full_name)}">
            </div>
            <div class="field">
              <label for="p-position">Должность</label>
              <input type="text" id="p-position" value="${esc(user.position || '')}">
            </div>
            <div class="field">
              <label for="p-email">E-mail</label>
              <input type="email" id="p-email" value="${esc(user.email || '')}">
            </div>
            <div class="field">
              <label>Логин и роль</label>
              <div style="padding:9px 0">
                <span class="mono">${esc(user.username)}</span> ·
                <span class="badge role-${esc(user.role)}">${esc(user.role_label)}</span>
              </div>
            </div>
          </div>
          <button class="btn btn-primary" type="submit">Сохранить данные</button>
        </form>
      </div>
      <div class="card">
        <div class="card-head"><h2>Смена пароля</h2></div>
        <form id="password-form">
          <div class="settings-grid">
            <div class="field">
              <label for="pw-current">Текущий пароль</label>
              <input type="password" id="pw-current" autocomplete="current-password">
            </div>
            <div class="field">
              <label for="pw-new">Новый пароль</label>
              <input type="password" id="pw-new" autocomplete="new-password">
              <span class="hint">Не менее 8 символов, буквы и цифры.</span>
            </div>
            <div class="field">
              <label for="pw-new2">Повторите новый пароль</label>
              <input type="password" id="pw-new2" autocomplete="new-password">
            </div>
          </div>
          <button class="btn btn-primary" type="submit">Сменить пароль</button>
        </form>
      </div>`;

    $('#profile-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type=submit]');
      setBusy(button, true, 'Сохранение…');
      try {
        const data = await api('/api/auth/profile', {
          method: 'POST',
          body: {
            full_name: $('#p-fullname').value.trim(),
            position: $('#p-position').value.trim(),
            email: $('#p-email').value.trim(),
          },
        });
        state.user = Object.assign({}, state.user, data.user);
        renderShell();
        toast('Данные сохранены', 'success');
      } catch (err) {
        toast(err.message, 'error');
      } finally {
        setBusy(button, false);
      }
    });

    $('#password-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type=submit]');
      const current = $('#pw-current').value;
      const next = $('#pw-new').value;
      if (next !== $('#pw-new2').value) {
        toast('Пароли не совпадают', 'error');
        return;
      }
      setBusy(button, true, 'Сохранение…');
      try {
        await api('/api/auth/change-password', {
          method: 'POST',
          body: { current_password: current, new_password: next },
        });
        state.user.must_change_password = false;
        $('#pw-current').value = '';
        $('#pw-new').value = '';
        $('#pw-new2').value = '';
        toast('Пароль изменён', 'success');
        renderProfile(++routeSeq);
      } catch (err) {
        toast(err.message, 'error');
      } finally {
        setBusy(button, false);
      }
    });
  }

  // -----------------------------------------------------------------------
  // Проверка обновлений
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
    const isAdmin = state.user.role === 'admin';
    const assets = info.assets || {};
    const asset = assets[state.platform + '_installer'] || assets[state.platform + '_archive']
      || assets.windows_installer || null;
    const body = `
      <dl class="kv">
        <dt>Установленная версия</dt><dd><b>${esc(info.current_version)}</b></dd>
        <dt>Последний релиз</dt><dd>${info.latest_version
          ? '<b>' + esc(info.latest_version) + '</b>' : '—'}</dd>
        <dt>Статус</dt><dd>${info.error
          ? '<span class="text-danger">' + esc(info.error) + '</span>'
          : (info.update_available
            ? '<span class="text-ok">Доступно обновление</span>'
            : 'Установлена последняя версия')}</dd>
        ${info.published_at ? `<dt>Опубликован</dt><dd>${fmtDateTime(info.published_at)}</dd>` : ''}
        ${asset ? `<dt>Файл для установки</dt><dd>${esc(asset.name)}
          ${asset.size ? '(' + (asset.size / 1048576).toFixed(1) + ' МБ)' : ''}</dd>` : ''}
      </dl>
      ${info.release_notes ? `
        <div class="section-title">Что нового</div>
        <div class="release-notes">${esc(info.release_notes)}</div>` : ''}
      ${info.update_available && asset ? `
        <div class="notice info" style="margin-top:14px">
          При обновлении база данных сохраняется: она хранится отдельно от программы,
          а перед установкой автоматически создаётся резервная копия.
        </div>` : ''}
      <p class="modal-note" style="margin-top:14px">
        Обновления публикуются в репозитории
        <a href="https://github.com/${esc(state.repo)}/releases" target="_blank" rel="noopener">
          github.com/${esc(state.repo)}</a>.
      </p>`;

    const actions = `
      <button class="btn" data-act="close">Закрыть</button>
      ${info.download_url ? `<a class="btn" href="${esc(info.download_url)}" target="_blank"
          rel="noopener" data-act="download">${icon('download', 15)} Скачать файл</a>` : ''}
      ${isAdmin && info.can_install ? `<button class="btn btn-primary" data-act="install">
          ${icon('refresh', 15)} Установить и перезапустить</button>` : ''}`;
    modal.querySelector('.modal-body').innerHTML = body;
    const head = modal.querySelector('.modal-head');
    head.insertAdjacentHTML('afterend', `<div class="modal-actions" style="margin:0 0 14px;justify-content:flex-start">${actions}</div>`);
    modal.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-act]');
      if (!button) return;
      if (button.dataset.act === 'close') closeModal();
      if (button.dataset.act === 'install') {
        const box = modal.querySelector('.modal-actions');
        if (box) {
          box.innerHTML = `
            <span class="text-muted" style="font-size:13px;margin-right:auto">
              Установить версию ${esc(info.latest_version)}? Перед установкой будет создана
              резервная копия базы данных.
            </span>
            <button class="btn" data-act="cancel-install">Отмена</button>
            <button class="btn btn-primary" data-act="confirm-install">Да, установить</button>`;
        }
        return;
      }
      if (button.dataset.act === 'cancel-install') { closeModal(); return; }
      if (button.dataset.act === 'confirm-install') {
        setBusy(button, true, 'Установка…');
        try {
          const result = await api('/api/update/install', { method: 'POST' });
          closeModal();
          toast(result.message || 'Установщик запущен', 'success', 9000);
          const banner = document.createElement('div');
          banner.className = 'notice info';
          banner.style.cssText = 'position:fixed;left:50%;top:20px;transform:translateX(-50%);' +
            'z-index:300;background:#fff;box-shadow:0 10px 30px rgba(0,0,0,.2)';
          banner.textContent = 'Устанавливается обновление. После перезапуска обновите страницу.';
          document.body.appendChild(banner);
        } catch (err) {
          setBusy(button, false);
          toast(err.message, 'error', 9000);
        }
      }
    });
  }

  // -----------------------------------------------------------------------
  // Обёртка для обработки ошибок
  // -----------------------------------------------------------------------
  async function safe(fn) {
    try {
      await fn();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      toast(err.message || String(err), 'error', 7000);
    }
  }

  // -----------------------------------------------------------------------
  // Запуск
  // -----------------------------------------------------------------------
  async function boot() {
    try {
      state.publicInfo = await api('/api/public/info');
    } catch (err) {
      state.publicInfo = { needs_setup: false, version: '' };
    }
    if (state.publicInfo.version) state.version = state.publicInfo.version;
    if (!state.token) {
      renderAuth(state.publicInfo.needs_setup ? 'setup' : 'login');
      return;
    }
    try {
      const data = await api('/api/auth/me');
      applySession(data);
      renderShell();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      renderAuth('login', err.message);
    }
  }

  window.addEventListener('hashchange', () => {
    if (!state.user) return;
    if (state.editor) {
      state.editor = null;
      document.removeEventListener('keydown', editorKeydown);
    }
    route();
  });

  let booted = false;
  function start() {
    if (booted) return;
    booted = true;
    boot();
  }
  document.addEventListener('DOMContentLoaded', start);
  if (document.readyState !== 'loading') start();
})();
