// Baseline shell: path router, shared demo-session bootstrap and API health check.
// Page bodies for /unit, /resident/:id and /check land with BL-18, BL-19 and BL-17.
const state = {session: null};

async function api(path, options = {}) {
  const headers = {...(state.session ? {Authorization: `Bearer ${state.session.token}`} : {}),
                   ...options.headers};
  const response = await fetch(path, {...options, headers});
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

async function bootstrap() {
  state.session = await api('/demo/session', {headers: {'X-PM-Demo': '1'}});
}

function route() {
  const path = location.pathname;
  const resident = path.match(/^\/resident\/([^/]+)$/);
  if (path === '/unit') return {name: 'unit', title: 'Unit watch list', ticket: 'BL-18'};
  if (path === '/check') return {name: 'check', title: 'Voice check', ticket: 'BL-17'};
  if (resident) return {name: 'resident', title: 'Resident', ticket: 'BL-19', id: resident[1]};
  return {name: 'unknown', title: 'Page not found', ticket: ''};
}

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  node.textContent = text;
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

async function render() {
  const current = route();
  document.querySelectorAll('[data-route]').forEach((a) => {
    if (a.dataset.route === current.name) a.setAttribute('aria-current', 'page');
  });
  const main = document.getElementById('bl-main');
  const status = el('div', 'Checking API connection…', {class: 'bl-status', 'data-state': 'pending'});
  main.replaceChildren(el('h1', current.title),
    el('p', current.ticket ? `Coming with ${current.ticket}.` : 'This page does not exist.'), status);
  try {
    await bootstrap();
    await api('/v1/health/ready');
    status.textContent = 'API reachable with the demo token.';
    status.dataset.state = 'ok';
  } catch (error) {
    status.textContent = `API not reachable: ${error.message}`;
    status.dataset.state = 'error';
  }
}

render();
