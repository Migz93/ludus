/* Ludus management UI. GPL-3.0-or-later.
   Vanilla JavaScript, no build step and no external dependencies.  All dynamic
   text is written with textContent, so system paths and command output can
   never be interpreted as markup. */
'use strict';
(function () {

/* ------------------------------------------------------------------ *
 * DOM helpers
 * ------------------------------------------------------------------ */

const SVG_NS = 'http://www.w3.org/2000/svg';

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  add(node, children);
  return node;
}

function add(parent, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) add(parent, child);
    else parent.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
}

function frag(...children) {
  const container = document.createDocumentFragment();
  add(container, children);
  return container;
}

function icon(name, className) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', className || 'icon');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', '#i-' + name);
  svg.appendChild(use);
  return svg;
}

const SEVERITY_ICON = { ok: 'ok', warn: 'warn', err: 'error', info: 'info' };

/* ------------------------------------------------------------------ *
 * Formatting
 * ------------------------------------------------------------------ */

function initials(name) {
  const cleaned = String(name || '').replace(/[^A-Za-z0-9]+/g, ' ').trim();
  if (!cleaned) return '?';
  const words = cleaned.split(/\s+/);
  if (words.length > 1) return (words[0][0] + words[1][0]).toUpperCase();
  return cleaned.slice(0, 2).toUpperCase();
}

function displayName(user) {
  const name = String(user || '');
  return name ? name.charAt(0).toUpperCase() + name.slice(1) : name;
}

function humanise(text) {
  const words = String(text || '').replace(/[-_]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return '';
  return words.map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

function formatBytes(bytes) {
  // Distinguish "not reported" from a genuine zero.
  if (bytes === null || bytes === undefined || bytes === '') return null;
  const value = Number(bytes);
  if (!isFinite(value) || value < 0) return null;
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let index = 0;
  let scaled = value;
  while (scaled >= 1000 && index < units.length - 1) { scaled /= 1000; index += 1; }
  const digits = scaled < 10 && index > 0 ? 1 : 0;
  return scaled.toFixed(digits) + ' ' + units[index];
}

function timeOfDay(date) {
  try {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (error) {
    return date.toTimeString().slice(0, 5);
  }
}

function plural(count, one, many) {
  return count === 1 ? one : (many || one + 's');
}

/* Turn a command-line error into one plain sentence, keeping the raw text for
   the technical disclosure. */
function friendlyError(raw) {
  const lines = String(raw || '').split('\n').map(line => line.trim()).filter(Boolean);
  if (!lines.length) return 'The change could not be completed.';
  let message = lines[lines.length - 1];
  message = message.replace(/^(ludusctl|ludus-disks|ludus-steam-user-libraries|ludus-steam-register-libraries):\s*/, '');
  message = message.charAt(0).toUpperCase() + message.slice(1);
  if (!/[.!?]$/.test(message)) message += '.';
  return message;
}

function firstNote(raw) {
  const lines = String(raw || '').split('\n').map(line => line.trim()).filter(Boolean);
  if (!lines.length) return '';
  return lines[0].replace(/^ludusctl:\s*/, '');
}

/* ------------------------------------------------------------------ *
 * API
 * ------------------------------------------------------------------ */

class ApiError extends Error {
  constructor(message, raw) {
    super(message);
    this.raw = raw || '';
  }
}

async function api(path, body) {
  let response;
  try {
    response = await fetch(path, {
      method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store'
    });
  } catch (error) {
    throw new ApiError('This machine could not be reached. Check that it is switched on and on the same network.', String(error));
  }
  if (response.status === 401) {
    throw new ApiError('Your administrator sign-in was not accepted. Reload the page to try again.');
  }
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    throw new ApiError('The Ludus machine sent a reply this page could not read.');
  }
  if (!response.ok) {
    throw new ApiError(friendlyError(data && data.error), (data && data.error) || '');
  }
  return data;
}

/* Read endpoints return {ok, output, error}; a failing command still returns
   HTTP 200, so the payload flag is what matters. */
function outputOf(result) {
  return String((result && result.output) || '');
}

function requireOk(result, fallback) {
  if (result && result.ok) return result;
  const raw = [outputOf(result), (result && result.error) || ''].filter(Boolean).join('\n');
  throw new ApiError(raw ? friendlyError(raw) : fallback, raw);
}

function tsvRows(text) {
  return String(text || '').split('\n').map(line => line.replace(/\r$/, '')).filter(line => line.length > 0).map(line => line.split('\t'));
}

function parseJsonOutput(result) {
  try {
    return JSON.parse(outputOf(result) || '[]');
  } catch (error) {
    return [];
  }
}

/* ------------------------------------------------------------------ *
 * Toasts
 * ------------------------------------------------------------------ */

const toastHost = document.getElementById('toasts');

function toast(tone, title, message) {
  // The container is already an aria-live region; a nested one would announce twice.
  const node = el('div', { class: 'toast', dataset: { tone } },
    el('span', { class: 'toast-icon' }, icon(SEVERITY_ICON[tone] || 'info')),
    el('div', { class: 'toast-body' },
      el('strong', { text: title }),
      message ? el('p', { text: message }) : null
    ),
    el('button', {
      class: 'icon-btn', type: 'button', 'aria-label': 'Dismiss notification',
      onClick: () => node.remove()
    }, icon('close', 'icon icon-sm'))
  );
  toastHost.appendChild(node);
  const life = tone === 'err' ? 12000 : 6000;
  setTimeout(() => node.remove(), life);
}

/* ------------------------------------------------------------------ *
 * Modal dialog
 * ------------------------------------------------------------------ */

const modal = document.getElementById('modal');
const modalIcon = document.getElementById('modal-icon');
const modalTitle = document.getElementById('modal-title');
const modalBody = document.getElementById('modal-body');
const modalConfirm = document.getElementById('modal-confirm');
const modalCancel = document.getElementById('modal-cancel');
const modalClose = document.getElementById('modal-close');

modalClose.addEventListener('click', () => modal.close('cancel'));
modalCancel.addEventListener('click', () => modal.close('cancel'));
modalConfirm.addEventListener('click', () => modal.close('confirm'));

function ask(options) {
  if (modal.open) return Promise.resolve(false);
  const tone = options.tone || 'accent';
  modalIcon.dataset.tone = tone;
  modalIcon.replaceChildren(icon(options.icon || 'info'));
  modalTitle.textContent = options.title;
  modalBody.replaceChildren();
  add(modalBody, [options.body]);
  modalConfirm.textContent = options.confirmLabel || 'Confirm';
  modalConfirm.className = 'btn ' + (options.destructive ? 'btn-danger' : 'btn-primary');
  modalCancel.textContent = options.cancelLabel || 'Cancel';
  // Escape closes without changing returnValue, so clear it before opening.
  modal.returnValue = '';
  modal.showModal();
  modalCancel.focus();
  return new Promise(resolve => {
    modal.addEventListener('close', () => resolve(modal.returnValue === 'confirm'), { once: true });
  });
}

function assurances(...points) {
  return el('ul', { class: 'assurances' }, points.map(point =>
    el('li', { class: 'assurance' }, icon('ok', 'icon icon-sm'), el('span', { text: point }))
  ));
}

function reviewList(pairs) {
  return el('dl', { class: 'review' }, pairs.filter(Boolean).map(([term, value]) =>
    el('div', { class: 'review-row' }, el('dt', { text: term }), el('dd', { text: value }))
  ));
}

/* ------------------------------------------------------------------ *
 * Busy state and mutations
 * ------------------------------------------------------------------ */

function setBusy(button, busy, label) {
  if (!(button instanceof HTMLButtonElement)) {
    button.disabled = busy;
    return;
  }
  if (busy) {
    if (!button._restore) button._restore = Array.from(button.childNodes);
    button.dataset.busy = '1';
    button.disabled = true;
    button.replaceChildren(icon('spinner', 'icon icon-spin'), el('span', { text: label || 'Working…' }));
  } else {
    delete button.dataset.busy;
    button.disabled = false;
    if (button._restore) { button.replaceChildren(...button._restore); button._restore = null; }
  }
}

/* Run a write operation, then reload every cached read so the whole page
   reflects the new state. */
async function mutate(button, options) {
  setBusy(button, true, options.busyLabel);
  try {
    const result = await api(options.path, options.body || {});
    if (!result.ok) {
      const raw = [outputOf(result), result.error || ''].filter(Boolean).join('\n').trim();
      throw new ApiError(friendlyError(raw), raw);
    }
    toast('ok', options.success, options.detail || firstNote(outputOf(result)));
    invalidate();
    await navigate({ keepFlash: false });
    return true;
  } catch (error) {
    setBusy(button, false);
    state.flash = {
      tone: 'err',
      title: options.failure || 'That change could not be completed',
      message: error.message,
      raw: error.raw || ''
    };
    toast('err', options.failure || 'That change could not be completed', error.message);
    invalidate();
    await navigate({ keepFlash: true });
    return false;
  }
}

/* ------------------------------------------------------------------ *
 * Cached reads
 * ------------------------------------------------------------------ */

const cache = new Map();

function cached(key, loader) {
  if (!cache.has(key)) {
    const promise = loader();
    promise.catch(() => cache.delete(key));
    cache.set(key, promise);
  }
  return cache.get(key);
}

function invalidate() {
  cache.clear();
}

const load = {
  /* Prefer the structured self-check. An install whose ludusctl predates it
     answers 404, so fall back to parsing the text form. */
  doctor: () => cached('doctor', async () => {
    try {
      const result = await api('/api/checks');
      const doctor = buildDoctor(recordsFromJson(result), result.error, result.ok);
      state.checkedAt = new Date();
      return doctor;
    } catch (error) {
      const result = await api('/api/doctor');
      const doctor = buildDoctor(recordsFromText(result), result.error, result.ok);
      state.checkedAt = new Date();
      return doctor;
    }
  }),
  users: () => cached('users', async () => {
    const result = requireOk(await api('/api/users'), 'The list of accounts could not be read.');
    return tsvRows(outputOf(result)).map(([status, user, home, steam]) => ({
      user, home: home || '',
      enrolled: status === 'enrolled',
      steamReady: steam === 'steam-ready',
      steamState: steam || '-'
    })).filter(entry => entry.user);
  }),
  libraries: () => cached('libraries', async () => {
    const result = requireOk(await api('/api/libraries'), 'The shared library list could not be read.');
    return tsvRows(outputOf(result)).map(([id, path, label]) => ({ id, path, label: label || '' })).filter(entry => entry.path);
  }),
  defaultLibrary: () => cached('default', async () => outputOf(await api('/api/libraries/default')).trim()),
  candidates: () => cached('candidates', async () => {
    const result = await api('/api/libraries/candidates');
    return tsvRows(outputOf(result)).map(([mount, device, fstype, suggested]) => ({ mount, device, fstype, suggested }))
      .filter(entry => entry.mount && entry.suggested);
  }),
  disks: () => cached('disks', async () => parseJsonOutput(requireOk(await api('/api/disks'), 'The list of disks could not be read.'))),
  personal: () => cached('personal', async () => parseJsonOutput(await api('/api/users/personal-libraries'))),
  settings: () => cached('settings', async () => {
    const result = await api('/api/settings');
    return {
      authMode: result.auth_mode || 'none',
      // `vscode` is the live policy state; requested records the saved choice.
      // Older Ludus backends expose only the former, so retain that fallback.
      vscode: Boolean(result.vscode_ssh_forwarding),
      vscodeRequested: 'vscode_ssh_forwarding_requested' in result
        ? Boolean(result.vscode_ssh_forwarding_requested)
        : Boolean(result.vscode_ssh_forwarding),
      username: String(result.username || '')
    };
  }),
  /* Optional structured storage figures.  The UI degrades quietly when the
     backend does not expose them. */
  storage: () => cached('storage', async () => {
    try {
      const result = await api('/api/storage');
      if (!result || !result.ok) return null;
      const rows = JSON.parse(outputOf(result) || '[]');
      return Array.isArray(rows) ? rows : null;
    } catch (error) {
      return null;
    }
  })
};

/* ------------------------------------------------------------------ *
 * Doctor output -> structured checks
 * ------------------------------------------------------------------ */

const CHECK_GROUPS = [
  { id: 'services', icon: 'server', title: 'Core services', blurb: 'The background pieces Ludus needs in order to run.' },
  { id: 'storage', icon: 'storage', title: 'Storage and mounts', blurb: 'Where shared games live, and whether those disks are attached.' },
  { id: 'private', icon: 'lock', title: 'Private player data', blurb: 'Each player keeps their own Proton and shader files, hidden from everyone else.' },
  { id: 'steam', icon: 'steam', title: 'Steam configuration', blurb: 'Whether each player’s Steam knows about the shared libraries.' },
  { id: 'network', icon: 'network', title: 'Network and control panel', blurb: 'How this page is reachable from the rest of your home network.' },
  { id: 'security', icon: 'shield', title: 'Security', blurb: 'The SELinux protections around the Ludus components.' }
];

const SERVICES = {
  'ludus.service': { name: 'Controller support', what: 'Lets a game controller navigate the sign-in screen and menus, standing in for a keyboard.' },
  'ludus-mount.service': { name: 'Private data service', what: 'Keeps each player’s Proton and shader files separate from other players.' },
  'ludus-backend.service': { name: 'Management service', what: 'Carries out the changes you make on this page.' },
  'ludus-web.service': { name: 'Control panel', what: 'Serves this page to your browser.' },
  'ludus-web-firewall.service': { name: 'Control panel firewall rule', what: 'Opens only the control panel port on your home network.' }
};

function serviceInfo(unit) {
  return SERVICES[unit] || { name: unit, what: 'A Ludus background service.' };
}

/* Every check carries a stable code from `ludusctl doctor --json`.  The copy
   below is keyed by that code, so rewording a diagnostic message on the
   machine cannot silently change what this page tells the reader. */
const CHECK_COPY = {
  /* ---- core services ---- */
  'group.present': { g: 'services',
    t: () => 'Player group is present',
    x: r => `The “${r.subject}” group exists, so enrolled players can share the same installed games.` },
  'group.missing': { g: 'services',
    t: () => 'Player group is missing',
    x: r => `The “${r.subject}” group no longer exists. Shared games cannot work until it is recreated.` },
  'steam-launcher.present': { g: 'services',
    t: () => 'Steam launcher is installed',
    x: () => 'Ludus can start Steam Big Picture through Bazzite’s own launcher.' },
  'steam-launcher.missing': { g: 'services',
    t: () => 'Steam launcher is missing',
    x: () => 'Ludus starts games through Bazzite’s Steam launcher, which is not installed. Nobody can launch games from the living-room session.' },
  'library-config.present': { g: 'services',
    t: () => 'Library list is readable',
    x: () => 'Ludus can read the list of shared game libraries.' },
  'library-config.absent': { g: 'services',
    t: () => 'No shared libraries yet',
    x: () => 'Nobody is sharing games yet. Add a shared library so every player sees the same installed games.' },
  'service.active': { g: 'services',
    t: r => `${serviceInfo(r.subject).name} is running`,
    x: r => serviceInfo(r.subject).what },
  'service.inactive': { g: 'services',
    t: r => `${serviceInfo(r.subject).name} is not running`,
    x: r => `${serviceInfo(r.subject).what} It is set to start automatically, but it is stopped right now.` },
  'service.disabled': { g: 'services',
    t: r => `${serviceInfo(r.subject).name} is switched off`,
    x: r => `${serviceInfo(r.subject).what} It will not start on its own after a restart.` },
  'mount-socket.present': { g: 'services',
    t: () => 'Private data service is reachable',
    x: () => 'Ludus can ask the private data service to prepare a player’s session.' },
  'mount-socket.absent': { g: 'services',
    t: () => 'Private data service is unreachable',
    x: () => 'Ludus cannot prepare a player’s private Proton and shader folders. Players may not be able to start a session.' },
  'backend-socket.present': { g: 'services',
    t: () => 'Management service is reachable',
    x: () => 'This page can carry out the changes you make.' },
  'backend-socket.absent': { g: 'services',
    t: () => 'Management service is unreachable',
    x: () => 'This page can still show information, but changes you make here will fail until the management service is running.' },
  'webui-config.present': { g: 'services',
    t: () => 'Control panel settings are readable',
    x: () => 'The sign-in settings for this page were loaded successfully.' },
  'webui-config.absent': { g: 'services',
    t: () => 'Control panel settings are unreadable',
    x: () => 'The sign-in settings for this page could not be read, so changes on the Settings page may not stick.' },

  /* ---- network ---- */
  'firewall.open': { g: 'network',
    t: () => 'Control panel is reachable on your network',
    x: r => `The firewall allows this page through on port ${port(r)} in the “${r.subject}” zone. Only that one port is opened.` },
  'firewall.closed': { g: 'network',
    t: () => 'Control panel port is closed',
    x: r => `The firewall is not letting port ${port(r)} through in the “${r.subject}” zone, so other devices on your network cannot open this page.` },
  'firewall.zone-unrecorded': { g: 'network',
    t: () => 'Firewall setup is incomplete',
    x: () => 'Ludus has not recorded which firewall zone it opened the control panel port in, so it cannot confirm or tidy up that rule later.' },
  'firewall.unavailable': { g: 'network',
    t: () => 'Firewall is not running',
    x: () => 'The system firewall is not available, so Ludus cannot limit which port is reachable. This page still refuses connections from outside your home network.' },

  /* ---- private player data ---- */
  'session.idle': { g: 'private',
    t: () => 'No player session is active',
    x: () => 'Nobody is signed into a Ludus session, so every player’s private game data is locked away.' },
  'session.active': { g: 'private',
    t: r => `${displayName(r.subject)} has an active session`,
    x: r => `${displayName(r.subject)}’s private Proton and shader files are in use. Changes to players and libraries are paused until they sign out.` },
  'session.reconciled': { g: 'private',
    t: r => `Cleared a leftover session for ${displayName(r.subject)}`,
    x: r => `${displayName(r.subject)}’s session ended without properly signing out, so this page kept showing them as active. No Steam process for them was found, so their private folders have been unlocked again automatically. Nothing was lost.` },
  'bind.correct': { g: 'private',
    t: () => 'Private data is correctly connected',
    x: () => 'The active player’s own Proton and shader folder is in use for this library, so other players cannot see it.' },
  'bind.wrong-target': { g: 'private',
    t: () => 'Private data points at the wrong folder',
    x: () => 'A library is using the wrong player’s private folder. Ask everyone to sign out; the correct folder is chosen again at the next sign-in.' },
  'bind.unclaimed': { g: 'private',
    t: () => 'Private data is in use but unclaimed',
    x: () => 'Private folders are still connected even though Ludus does not know which player is signed in. This normally clears after everyone signs out.' },
  'bind.locked': { g: 'private',
    t: () => 'Private data is locked while idle',
    x: () => 'While nobody is playing, this library’s private folder is sealed so no player can read another player’s files.' },
  'bind.unlocked': { g: 'private',
    t: () => 'Private data is not sealed',
    x: () => 'A private folder is not locked while idle, so another player could reach it. Run Repair to reseal it.' },
  'bind.missing': { g: 'private',
    t: () => 'A private data folder is missing',
    x: () => 'A library is missing the folder Ludus uses to keep Proton and shader files private. Run Repair to recreate it.' },
  'bind.mounted': { g: 'private',
    t: () => 'Private data is in use',
    x: () => 'This private folder is connected to a player right now, so its permissions cannot be checked.' },
  'bind.permissions': { g: 'private',
    t: () => 'Private data folder is not sealed',
    x: () => 'A private folder does not have the locked-down permissions Ludus expects. Run Repair to correct it.' },

  /* ---- storage ---- */
  'library.mounted': { g: 'storage',
    t: () => 'Shared library disk is attached',
    x: r => `This shared library sits on ${r.data.device || 'its disk'}${r.data.fstype ? `, formatted as ${r.data.fstype}` : ''}.` },
  'library.unresolved': { g: 'storage',
    t: () => 'Shared library disk is missing',
    x: () => 'Ludus cannot tell which disk this shared library is on. The disk is probably disconnected or failed to mount at start-up.' },
  'library.missing': { g: 'storage',
    t: () => 'Shared library folder is missing',
    x: () => 'The folder for this shared library no longer exists. If its disk is unplugged, reconnect it; otherwise remove the library from Ludus.' },
  'library.permissions': { g: 'storage',
    t: () => 'Shared library permissions have drifted',
    x: () => 'This library’s permissions are not the shared settings Ludus expects, so some players may not be able to install or update games here. Run Repair to correct it.' },
  'library.user-access': { g: 'storage',
    t: r => `${displayName(r.data.user)} can use a shared library`,
    x: () => 'This player can traverse the library path and write shared Steam metadata.' },
  'library.user-inaccessible': { g: 'storage',
    t: r => `${displayName(r.data.user)} cannot use a shared library`,
    x: r => `A parent folder prevents ${displayName(r.data.user)} from reaching this shared library. Check that every directory in its path is accessible to the ludus group.` },
  'library.access-unverified': { g: 'storage',
    t: () => 'Player access has not been verified',
    x: () => 'This check needs the privileged Ludus backend to test each enrolled player’s actual access to the shared library.' },
  'library.folder-missing': { g: 'storage',
    t: r => `Library folder “${String(r.subject).split('/').pop()}” is missing`,
    x: () => 'A standard Steam folder is missing from this library. Run Repair to recreate it.' },

  /* ---- Steam ---- */
  'player.ineligible': { g: 'steam',
    t: r => `${displayName(r.subject)} is no longer a usable account`,
    x: r => `${displayName(r.subject)} is enrolled as a player, but their Linux account or home folder is no longer suitable. Remove them from Ludus, or restore the account.` },
  'steam.running': { g: 'steam',
    t: r => `${displayName(r.subject)} has Steam open`,
    x: () => 'Ludus will not change players or libraries while Steam is open, so nothing is altered underneath a running game.' },
  'steam.stopped': { g: 'steam',
    t: r => `${displayName(r.subject)} is not playing`,
    x: () => 'Steam is closed for this player, so library and player changes are safe to make.' },
  'steam.deferred': { g: 'steam',
    t: r => `${displayName(r.subject)} has not signed into Steam yet`,
    x: r => `Ludus waits until ${displayName(r.subject)} signs into Steam once on this machine. The shared libraries are added to their Steam automatically after that.` },
  'steam-registration.complete': { g: 'steam',
    t: r => `${displayName(r.subject)} can see the shared libraries`,
    x: r => r.data.default
      ? `Every shared library appears in this player’s Steam, and new games install into ${r.data.default} by default.`
      : 'Every shared library appears in this player’s Steam.' },
  'steam-registration.missing-paths': { g: 'steam',
    t: r => `${displayName(r.subject)} is missing a shared library`,
    x: r => {
      const count = String(r.data.missing || '').split(', ').filter(Boolean).length || 1;
      return `Steam does not list ${count} shared ${plural(count, 'library', 'libraries')} for this player yet. Ludus adds them the next time they start a Ludus session.`;
    } },
  'steam-registration.wrong-default': { g: 'steam',
    t: r => `${displayName(r.subject)} has a different default library`,
    x: r => `New games would install into ${r.data.actual || 'another folder'} for this player instead of the chosen shared default. Ludus corrects this at their next Ludus session.` },
  'steam-registration.absent': { g: 'steam',
    t: r => `${displayName(r.subject)}’s Steam is not set up yet`,
    x: () => 'Steam has not written its library list for this player. It appears after their first Steam sign-in.' },
  'steam-registration.unreadable': { g: 'steam',
    t: r => `${displayName(r.subject)}’s Steam settings could not be read`,
    x: () => 'Ludus could not understand one of this player’s Steam configuration files, so it will not modify it. Their Steam may need to be repaired or reinstalled.' },

  /* ---- security ---- */
  'selinux.enforcing': { g: 'security',
    t: () => 'SELinux protection is on',
    x: () => 'The system’s strongest access protection is active and limiting what each Ludus component can do.' },
  'selinux.permissive': { g: 'security',
    t: () => 'SELinux is only watching',
    x: () => 'SELinux is recording policy violations instead of blocking them. Protection is reduced until it is set back to enforcing.' },
  'selinux.disabled': { g: 'security',
    t: () => 'SELinux protection is off',
    x: () => 'SELinux is switched off, so the extra confinement around Ludus components is not applied.' },
  'selinux.controller-ok': { g: 'security',
    t: () => 'Controller support is confined',
    x: () => 'The gamepad helper is restricted to reading controllers and moving the on-screen selection, and nothing else.' },
  'selinux.controller-mislabelled': { g: 'security',
    t: () => 'Controller helper is mislabelled',
    x: () => 'The gamepad helper does not carry its security label, so it may not be confined or may fail to read controllers. Reinstalling Ludus restores it.' },
  'selinux.controller-missing': { g: 'security',
    t: () => 'Controller security policy is missing',
    x: () => 'The security rules for the gamepad helper are not loaded, so controller navigation at the login screen may not work.' },
  'selinux.vscode-ok': { g: 'security',
    t: () => 'VS Code forwarding is ready',
    x: () => 'The optional SELinux rule that VS Code Remote SSH needs is installed.' },
  'selinux.vscode-missing': { g: 'security',
    t: () => 'VS Code forwarding needs repair',
    x: () => 'Ludus is configured to allow VS Code Remote SSH forwarding, but the SELinux rule is missing. Open Settings and choose Repair VS Code forwarding.' },
  'selinux.unavailable': { g: 'security',
    t: () => 'SELinux could not be checked',
    x: () => 'The SELinux tools are not present, so Ludus cannot confirm its security policy is in place.' }
};

function port(record) {
  return String(record.data.port || '9876/tcp').split('/')[0];
}

/* An install whose ludusctl predates `doctor --json` still returns the text
   form.  These patterns recover the same records from it so the interface is
   identical either way; order matters, most specific first. */
const LEGACY_RULES = [
  { re: /^group (\S+) exists$/, code: 'group.present', s: m => m[1] },
  { re: /^group (\S+) is missing$/, code: 'group.missing', s: m => m[1] },
  { re: /^Bazzite Steam launcher found$/, code: 'steam-launcher.present' },
  { re: /^\/usr\/bin\/bazzite-steam is missing$/, code: 'steam-launcher.missing' },
  { re: /^library configuration found$/, code: 'library-config.present' },
  { re: /^no shared libraries configured$/, code: 'library-config.absent' },
  { re: /^(\S+\.service) is active$/, code: 'service.active', s: m => m[1] },
  { re: /^(\S+\.service) is enabled but inactive$/, code: 'service.inactive', s: m => m[1] },
  { re: /^(\S+\.service) is not enabled$/, code: 'service.disabled', s: m => m[1] },
  { re: /^mount control socket exists$/, code: 'mount-socket.present' },
  { re: /^mount control socket is unavailable$/, code: 'mount-socket.absent' },
  { re: /^WebUI backend socket exists$/, code: 'backend-socket.present' },
  { re: /^WebUI backend socket is unavailable$/, code: 'backend-socket.absent' },
  { re: /^WebUI credential configuration found$/, code: 'webui-config.present' },
  { re: /^WebUI credential configuration is unavailable$/, code: 'webui-config.absent' },

  { re: /^WebUI port (\S+) is open in active zone (\S+)$/, code: 'firewall.open', s: m => m[2], d: m => ({ port: m[1] }) },
  { re: /^WebUI port (\S+) is not open in recorded zone (\S+)$/, code: 'firewall.closed', s: m => m[2], d: m => ({ port: m[1] }) },
  { re: /^WebUI firewall zone has not been recorded$/, code: 'firewall.zone-unrecorded' },
  { re: /^firewalld is unavailable; WebUI LAN access could not be constrained$/, code: 'firewall.unavailable' },

  { re: /^no Ludus player session has private binds active$/, code: 'session.idle' },
  { re: /^private binds are active for (\S+)$/, code: 'session.active', s: m => m[1] },
  { re: /^cleared a stale session marker for (\S+); no matching Steam process was found$/, code: 'session.reconciled', s: m => m[1] },
  { re: /^private bind (\S+) -> (\S+)$/, code: 'bind.correct', s: m => m[1], d: m => ({ source: m[2] }) },
  { re: /^private bind (\S+) points to (\S+); expected (\S+)$/, code: 'bind.wrong-target', s: m => m[1], d: m => ({ source: m[2], expected: m[3] }) },
  { re: /^private bind (\S+) is active \((\S+)\), but no valid active player is recorded$/, code: 'bind.unclaimed', s: m => m[1], d: m => ({ source: m[2] }) },
  { re: /^private bind target (\S+) is locked while idle$/, code: 'bind.locked', s: m => m[1] },
  { re: /^private bind target (\S+) is not locked \((.+)\)$/, code: 'bind.unlocked', s: m => m[1], d: m => ({ actual: m[2] }) },
  { re: /^missing private bind target (\S+)$/, code: 'bind.missing', s: m => m[1] },
  { re: /^(\S+) has an active (?:private )?bind mount(?: for \S+)?$/, code: 'bind.mounted', s: m => m[1] },
  { re: /^(\S+) permissions are (.+); expected root:root 0$/, code: 'bind.permissions', s: m => m[1], d: m => ({ actual: m[2] }) },

  { re: /^library mount (.+): (\S+) \(([^)]+)\)$/, code: 'library.mounted', s: m => m[1], d: m => ({ device: m[2], fstype: m[3] }) },
  { re: /^library mount cannot be resolved: (.+)$/, code: 'library.unresolved', s: m => m[1] },
  { re: /^library missing: (.+)$/, code: 'library.missing', s: m => m[1] },
  { re: /^(.+) permissions are (.+); expected root:(\S+) 2775$/, code: 'library.permissions', s: m => m[1], d: m => ({ actual: m[2] }) },
  { re: /^(\S+) can access the shared Steam library (.+)$/, code: 'library.user-access', s: m => m[2], d: m => ({ user: m[1] }) },
  { re: /^(\S+) cannot access the shared Steam library (.+); check parent-directory ownership and permissions$/, code: 'library.user-inaccessible', s: m => m[2], d: m => ({ user: m[1] }) },
  { re: /^cannot verify every enrolled player's access to (.+) without root privileges$/, code: 'library.access-unverified', s: m => m[1] },
  { re: /^missing (.+\/steamapps\/(?:common|workshop))$/, code: 'library.folder-missing', s: m => m[1] },

  { re: /^enrolled user is no longer eligible: (\S+)$/, code: 'player.ineligible', s: m => m[1] },
  { re: /^Steam is running for (?:active player )?(\S+)(?: outside the active Ludus session)?$/, code: 'steam.running', s: m => m[1] },
  { re: /^Steam is stopped for (\S+)$/, code: 'steam.stopped', s: m => m[1] },
  { re: /^Steam registration deferred for (\S+) until their first Steam login$/, code: 'steam.deferred', s: m => m[1] },
  { re: /^Steam registration (\S+): (.+) has all shared libraries(?:; default (.+))?$/, code: 'steam-registration.complete', s: m => m[1], d: m => ({ file: m[2], default: m[3] || '' }) },
  { re: /^Steam registration (\S+): (.+) is missing shared path\(s\): (.+)$/, code: 'steam-registration.missing-paths', s: m => m[1], d: m => ({ file: m[2], missing: m[3] }) },
  { re: /^Steam registration (\S+): (.+) default is (.+); expected (.+)$/, code: 'steam-registration.wrong-default', s: m => m[1], d: m => ({ file: m[2], actual: m[3], expected: m[4] }) },
  { re: /^Steam registration (\S+): VDF not created yet: (.+)$/, code: 'steam-registration.absent', s: m => m[1], d: m => ({ file: m[2] }) },
  { re: /^Steam registration (\S+): cannot read (.+): (.+)$/, code: 'steam-registration.unreadable', s: m => m[1], d: m => ({ file: m[2] }) },

  { re: /^SELinux is enforcing$/, code: 'selinux.enforcing' },
  { re: /^SELinux is permissive$/, code: 'selinux.permissive' },
  { re: /^SELinux is disabled$/, code: 'selinux.disabled' },
  { re: /^controller SELinux policy and executable label are installed$/, code: 'selinux.controller-ok' },
  { re: /^controller executable SELinux label is (.+)$/, code: 'selinux.controller-mislabelled', d: m => ({ label: m[1] }) },
  { re: /^controller SELinux policy is not installed$/, code: 'selinux.controller-missing' },
  { re: /^VS Code Remote SSH forwarding policy is installed$/, code: 'selinux.vscode-ok' },
  { re: /^VS Code Remote SSH forwarding is enabled in Ludus, but its SELinux policy is not installed$/, code: 'selinux.vscode-missing' },
  { re: /^SELinux tools are unavailable; controller policy could not be checked$/, code: 'selinux.unavailable' }
];

/* Anything neither the code table nor the patterns recognise still has to land
   in a sensible group rather than disappearing. */
const FALLBACK_GROUPS = [
  [/selinux|policy|label/i, 'security'],
  [/firewall|zone|port/i, 'network'],
  [/steam|registration|vdf/i, 'steam'],
  [/bind|compatdata|shadercache|private/i, 'private'],
  [/library|mount|disk|permissions/i, 'storage']
];

function classify(text) {
  for (const [pattern, group] of FALLBACK_GROUPS) if (pattern.test(text)) return group;
  return 'services';
}

const SEVERITY_OF = { HEALTHY: 'ok', WARNING: 'warn', ERROR: 'err' };

/* --- record sources --- */

function recordsFromText(result) {
  const records = [];
  for (const line of outputOf(result).split('\n')) {
    const trimmed = line.replace(/\r$/, '').trim();
    if (!trimmed) continue;
    const marker = /^(HEALTHY|WARNING|ERROR)\s+(.*)$/.exec(trimmed);
    if (!marker) continue;
    const severity = SEVERITY_OF[marker[1]];
    const message = marker[2];
    let matched = null;
    for (const rule of LEGACY_RULES) {
      const match = rule.re.exec(message);
      if (!match) continue;
      matched = {
        severity, code: rule.code, group: (CHECK_COPY[rule.code] || {}).g || 'services',
        subject: rule.s ? rule.s(match) : '', data: rule.d ? rule.d(match) : {}, message
      };
      break;
    }
    records.push(matched || { severity, code: '', group: classify(message), subject: '', data: {}, message });
  }
  return records;
}

function recordsFromJson(result) {
  const parsed = JSON.parse(outputOf(result));
  if (!Array.isArray(parsed)) throw new Error('unexpected structured check output');
  return parsed.map(entry => ({
    severity: SEVERITY_OF[entry.severity] || 'warn',
    code: String(entry.code || ''),
    group: String(entry.group || '') || classify(String(entry.message || '')),
    subject: String(entry.subject || ''),
    data: (entry.data && typeof entry.data === 'object') ? entry.data : {},
    message: String(entry.message || '')
  }));
}

/* --- records -> what the page renders --- */

const BIND_ORDER = { locked: 0, active: 1, problem: 2 };
const BIND_STATE = {
  'bind.locked': 'locked',
  'bind.correct': 'active', 'bind.unclaimed': 'active', 'bind.mounted': 'active',
  'bind.unlocked': 'problem', 'bind.missing': 'problem',
  'bind.permissions': 'problem', 'bind.wrong-target': 'problem'
};

function setBind(facts, record, statusValue) {
  const owner = record.data.library
    || String(record.subject).replace(/\/steamapps\/(compatdata|shadercache)$/, '');
  const existing = facts.bindStates.get(owner);
  if (!existing || BIND_ORDER[statusValue] > BIND_ORDER[existing]) facts.bindStates.set(owner, statusValue);
}

function collectFacts(facts, record) {
  if (record.code === 'session.active') facts.activePlayer = record.subject;
  else if (record.code === 'library.mounted') facts.mounts.set(record.subject, { device: record.data.device || '', fstype: record.data.fstype || '' });
  else if (record.code === 'steam.running') facts.steamRunning.add(record.subject);
  else if (record.code.startsWith('selinux.') && record.code !== 'selinux.unavailable' && !record.code.startsWith('selinux.controller')) {
    facts.selinux = record.code.slice('selinux.'.length);
  }
  if (BIND_STATE[record.code]) setBind(facts, record, BIND_STATE[record.code]);
}

function describe(record) {
  const copy = CHECK_COPY[record.code];
  if (copy) return { group: copy.g, title: copy.t(record), explanation: copy.x(record) };
  const sentence = record.message.charAt(0).toUpperCase() + record.message.slice(1);
  return { group: record.group, title: sentence, explanation: '' };
}

function buildDoctor(records, stderr, ok) {
  const facts = {
    activePlayer: null,
    selinux: null,
    mounts: new Map(),      // library path -> {device, fstype}
    bindStates: new Map(),  // library path -> 'locked' | 'active' | 'problem'
    steamRunning: new Set()
  };
  const checks = records.map(record => {
    collectFacts(facts, record);
    const copy = describe(record);
    return {
      severity: record.severity, group: copy.group, title: copy.title,
      explanation: copy.explanation,
      detail: `${record.severity === 'ok' ? 'HEALTHY' : (record.severity === 'warn' ? 'WARNING' : 'ERROR')} ${record.message}`
    };
  });
  const counts = { ok: 0, warn: 0, err: 0 };
  for (const check of checks) counts[check.severity] += 1;
  return {
    ok: Boolean(ok),
    // Reconstructed rather than echoed, so both sources show the same thing.
    raw: [checks.map(check => check.detail).join('\n'), String(stderr || '').trimEnd()].filter(Boolean).join('\n'),
    checks, counts, facts,
    tone: counts.err ? 'err' : (counts.warn ? 'warn' : 'ok')
  };
}

/* ------------------------------------------------------------------ *
 * Shared building blocks
 * ------------------------------------------------------------------ */

function card(...children) {
  return el('section', { class: 'card' }, children);
}

function cardHead(title, description, aside) {
  return el('div', { class: 'card-head' },
    el('div', null, el('h2', { text: title }), description ? el('p', { text: description }) : null),
    aside || null
  );
}

function badge(tone, label, iconName) {
  return el('span', { class: 'badge', dataset: tone ? { tone } : {} },
    iconName ? icon(iconName, 'icon icon-sm') : null,
    el('span', { text: label })
  );
}

function notice(tone, title, message, actions) {
  return el('div', { class: 'alert', dataset: { tone } },
    el('span', { class: 'alert-icon' }, icon(SEVERITY_ICON[tone] || 'info')),
    el('div', { class: 'alert-body' },
      el('strong', { text: title }),
      message ? el('p', { text: message }) : null,
      actions ? el('div', { class: 'actions' }, actions) : null
    )
  );
}

function empty(iconName, title, message, action) {
  return el('div', { class: 'empty' },
    icon(iconName),
    el('strong', { text: title }),
    message ? el('p', { text: message }) : null,
    action || null
  );
}

function disclosure(label, body, className) {
  return el('details', { class: 'disclosure ' + (className || '') },
    el('summary', null, icon('chevron', 'icon icon-sm'), el('span', { text: label })),
    el('div', { class: 'disclosure-body' }, body)
  );
}

function factList(rows) {
  return el('dl', { class: 'facts' }, rows.filter(Boolean).map(([term, value]) =>
    el('div', { class: 'fact' },
      el('dt', { text: term }),
      el('dd', null, typeof value === 'string' ? document.createTextNode(value) : value)
    )
  ));
}

function link(label, route, iconName) {
  return el('a', { class: 'btn btn-sm', href: '#/' + route },
    iconName ? icon(iconName) : null, el('span', { text: label })
  );
}

function healthHero(doctor, options) {
  const hideLink = Boolean((options || {}).hideLink);
  const titles = {
    ok: 'Ludus is ready',
    warn: 'Ludus needs a little attention',
    err: 'Ludus has a problem to fix'
  };
  return el('div', { class: 'hero', dataset: { tone: doctor.tone } },
    el('span', { class: 'hero-icon' }, icon(SEVERITY_ICON[doctor.tone], 'icon')),
    el('div', { class: 'hero-text' },
      el('h2', { text: titles[doctor.tone] })
    ),
    el('div', { class: 'hero-counts' },
      el('span', { class: 'count', dataset: { tone: 'ok' } }, icon('ok', 'icon icon-sm'), el('span', { text: `${doctor.counts.ok} passing` })),
      doctor.counts.warn ? el('span', { class: 'count', dataset: { tone: 'warn' } }, icon('warn', 'icon icon-sm'), el('span', { text: `${doctor.counts.warn} to review` })) : null,
      doctor.counts.err ? el('span', { class: 'count', dataset: { tone: 'err' } }, icon('error', 'icon icon-sm'), el('span', { text: `${doctor.counts.err} ${plural(doctor.counts.err, 'problem')}` })) : null,
      hideLink ? null : link('Health', 'health', 'health')
    )
  );
}

function statCard(options) {
  return el('section', { class: 'card stat' },
    el('div', { class: 'stat-head' }, icon(options.icon, 'icon icon-sm'), el('span', { text: options.label })),
    el('div', { class: 'stat-value', text: options.value }),
    options.meter || null,
    options.note ? el('div', { class: 'stat-note', text: options.note }) : null,
    options.foot ? el('div', { class: 'stat-foot actions' }, options.foot) : null
  );
}

function meter(fraction, tone) {
  const percent = Math.max(0, Math.min(100, Math.round(fraction * 100)));
  const bar = el('div', { class: 'meter', dataset: tone ? { tone } : {} }, el('span'));
  bar.style.setProperty('--fill', percent + '%');
  return bar;
}

/* Give a mount point and a shared library a name a non-technical reader
   recognises, using the mount Ludus generated the path from where possible. */
function mountName(mount) {
  if (mount === '/var' || mount === '/') return 'Main system disk';
  const name = humanise(String(mount).split('/').filter(Boolean).pop() || '');
  return name ? name + ' disk' : String(mount);
}

function libraryTitle(path, candidates) {
  const match = candidates.find(entry => entry.suggested === path);
  if (match) return mountName(match.mount);
  const parts = String(path).split('/').filter(Boolean);
  const last = parts[parts.length - 1] || path;
  if (last === 'steam-library' && parts.length > 1) return humanise(parts[parts.length - 2]) + ' disk';
  return humanise(last) || path;
}

/* Btrfs reports its source as "/dev/sda3[/var]". The subvolume belongs in the
   technical details, not in the headline fact. */
function deviceName(device) {
  return String(device || '').replace(/\[[^\]]*\]$/, '');
}

function storageFor(path, storage) {
  if (!storage) return null;
  return storage.find(entry => entry && entry.path === path) || null;
}

/* ------------------------------------------------------------------ *
 * View: Dashboard
 * ------------------------------------------------------------------ */

async function viewDashboard() {
  const [doctor, users, libraries, settings, storage] = await Promise.all([
    load.doctor(), load.users(), load.libraries(), load.settings(), load.storage()
  ]);

  const players = users.filter(entry => entry.enrolled);
  const awaiting = players.filter(entry => !entry.steamReady);
  const active = doctor.facts.activePlayer;

  /* --- actionable alerts --- */
  const alerts = [];
  if (doctor.counts.err) {
    alerts.push(notice('err', `${doctor.counts.err} ${plural(doctor.counts.err, 'check')} reported a problem`,
      'These need attention before Ludus works properly for everyone.',
      [link('See what is wrong', 'health', 'arrow')]));
  }
  if (!players.length) {
    alerts.push(notice('info', 'No players are enrolled yet',
      'Enrol the people who will use this machine so they appear on the living-room sign-in screen.',
      [link('Add players', 'players', 'user-plus')]));
  }
  if (!libraries.length) {
    alerts.push(notice('info', 'No shared game library yet',
      'Add a shared library so everyone installs into the same place and games are only downloaded once.',
      [link('Add a shared library', 'libraries', 'plus')]));
  }
  for (const person of awaiting) {
    alerts.push(notice('warn', `${displayName(person.user)} needs to sign into Steam once`,
      `Ask ${displayName(person.user)} to start a Ludus session and sign into Steam. Until then, Ludus cannot add the shared libraries to their Steam.`,
      [link('View player', 'players', 'players')]));
  }
  if (settings.authMode === 'none') {
    alerts.push(notice('warn', 'This control panel has no password',
      'Anyone on your home network can open this page and change how the machine is set up.',
      [link('Set up a sign-in', 'settings', 'key')]));
  }

  /* --- storage summary --- */
  const libraryStorage = libraries.map(library => storageFor(library.path, storage)).filter(Boolean);
  const devices = new Set();
  for (const library of libraries) {
    const mount = doctor.facts.mounts.get(library.path);
    if (mount) devices.add(deviceName(mount.device));
  }
  let storageValue = libraries.length ? `${devices.size || libraries.length} ${plural(devices.size || libraries.length, 'disk')}` : 'None yet';
  let storageMeter = null;
  if (libraryStorage.length) {
    const free = libraryStorage.reduce((total, entry) => total + Number(entry.free || 0), 0);
    const size = libraryStorage.reduce((total, entry) => total + Number(entry.total || 0), 0);
    if (size > 0) {
      const used = 1 - free / size;
      storageValue = `${formatBytes(free)} free`;
      storageMeter = meter(used, used > 0.95 ? 'err' : (used > 0.85 ? 'warn' : null));
    }
  }

  return frag(
    healthHero(doctor),
    alerts.length ? el('div', { class: 'stack-sm' }, alerts) : null,
    el('div', { class: 'grid grid-3' },
      statCard({
        icon: 'players', label: 'Players',
        value: players.length ? String(players.length) : 'None yet',
        foot: [link('Manage players', 'players')]
      }),
      statCard({
        icon: 'libraries', label: 'Libraries',
        value: libraries.length ? String(libraries.length) : 'None yet',
        foot: [link('Manage libraries', 'libraries')]
      }),
      statCard({
        icon: 'storage', label: 'Disk space',
        value: storageValue,
        meter: storageMeter,
        foot: [link('Disk tools', 'disks')]
      }),
      statCard({
        icon: 'session', label: 'Active session',
        value: active ? displayName(active) : 'Nobody playing'
      })
    )
  );
}

/* ------------------------------------------------------------------ *
 * View: Players
 * ------------------------------------------------------------------ */

async function viewPlayers() {
  const [users, doctor] = await Promise.all([load.users(), load.doctor()]);
  const players = users.filter(entry => entry.enrolled);
  const available = users.filter(entry => !entry.enrolled);
  const active = doctor.facts.activePlayer;

  return frag(
    card(
      cardHead('Players on this machine',
        'Enrolled players appear on the living-room sign-in screen and share the same installed games.'),
      el('div', { class: 'alert', dataset: { tone: 'info' } },
        el('span', { class: 'alert-icon' }, icon('info')),
        el('div', { class: 'alert-body' },
          el('strong', { text: 'Removing a player is always safe' }),
          el('p', { text: 'It only removes them from the Ludus player group. Their account, home folder, saves and games are never touched, and you can re-enrol them anytime.' })
        )
      )
    ),

    players.length
      ? el('div', { class: 'grid grid-2' }, players.map(person => playerCard(person, doctor, active)))
      : empty('players', 'No players enrolled yet',
        'Choose an existing account below to add the first player.'),

    card(
      cardHead('Add a player', 'Only existing accounts on this computer can be enrolled. Ludus never creates or deletes accounts.'),
      available.length ? enrollForm(available) : el('p', { class: 'stat-note', text: 'Every eligible account on this computer is already enrolled.' })
    )
  );
}

function playerCard(person, doctor, active) {
  const isPlaying = doctor.facts.steamRunning.has(person.user);
  const isActive = active === person.user;
  const tone = person.steamReady ? (isActive ? 'accent' : 'ok') : 'warn';

  let nextAction;
  let nextTone = null;
  if (!person.steamReady) {
    nextTone = 'warn';
    nextAction = `Ask ${displayName(person.user)} to start a Ludus session and sign into Steam once. Ludus adds the shared libraries to their Steam straight afterwards.`;
  } else if (isActive || isPlaying) {
    nextAction = `${displayName(person.user)} is playing right now. Player and library changes are paused until they sign out.`;
  } else {
    nextAction = 'Nothing to do. They can start playing from the Ludus sign-in screen.';
  }

  const removeButton = el('button', { class: 'btn btn-sm btn-danger', type: 'button' },
    icon('trash'), el('span', { text: 'Remove from Ludus' }));
  removeButton.addEventListener('click', () => confirmRemovePlayer(person, removeButton));

  return el('section', { class: 'card person' },
    el('div', { class: 'person-top' },
      el('span', { class: 'avatar', dataset: { tone }, 'aria-hidden': 'true', text: initials(person.user) }),
      el('div', null,
        el('div', { class: 'person-name', text: displayName(person.user) }),
        el('div', { class: 'person-sub', text: person.user })
      )
    ),
    el('div', { class: 'tags' },
      badge('ok', 'Enrolled', 'ok'),
      person.steamReady ? badge('ok', 'Steam ready', 'steam') : badge('warn', 'Awaiting first Steam sign-in', 'warn'),
      isActive ? badge('accent', 'Session active', 'session') : null,
      !isActive && isPlaying ? badge('accent', 'Steam open', 'steam') : null
    ),
    el('div', { class: 'next-action', dataset: nextTone ? { tone: nextTone } : {} },
      icon(nextTone ? 'warn' : 'info'),
      el('span', { text: nextAction })
    ),
    el('div', { class: 'actions' }, removeButton),
    disclosure('Technical details', factList([
      ['Linux account', el('span', { class: 'path', text: person.user })],
      ['Home directory', el('span', { class: 'path', text: person.home || 'unknown' })],
      ['Steam state', person.steamState === 'steam-ready' ? 'steam-ready' : person.steamState],
      ['Steam processes', isPlaying ? 'running' : 'stopped']
    ]), 'card-disclosure')
  );
}

function enrollForm(available) {
  const select = el('select', { name: 'user', required: true, id: 'enroll-user' },
    available.map(entry => el('option', { value: entry.user, text: `${displayName(entry.user)} (${entry.user})` }))
  );
  const button = el('button', { class: 'btn btn-primary', type: 'submit' },
    icon('user-plus'), el('span', { text: 'Enrol player' }));

  return el('form', {
    class: 'form-row',
    onSubmit: event => {
      event.preventDefault();
      confirmEnroll(select.value, button);
    }
  },
    el('div', { class: 'field' },
      el('label', { for: 'enroll-user', text: 'Account to enrol' }),
      select,
      el('span', { class: 'help', text: 'They will need to sign out and back in before shared games become available.' })
    ),
    button
  );
}

async function confirmEnroll(user, button) {
  const confirmed = await ask({
    title: `Enrol ${displayName(user)} as a player?`,
    icon: 'user-plus', tone: 'accent',
    confirmLabel: 'Enrol player',
    body: frag(
      el('p', { text: `${displayName(user)} will be added to the Ludus player group and will appear on the living-room sign-in screen.` }),
      assurances(
        'No account is created, changed or deleted.',
        'Their existing games, saves and home folder are untouched.',
        'Shared libraries are added to their Steam after their first Steam sign-in.'
      ),
      el('p', { text: 'They must sign out and sign back in before shared games become available to them.' })
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/users/enroll', body: { user },
    busyLabel: 'Enrolling…',
    success: `${displayName(user)} is now a Ludus player`,
    failure: `${displayName(user)} could not be enrolled`
  });
}

async function confirmRemovePlayer(person, button) {
  const confirmed = await ask({
    title: `Remove ${displayName(person.user)} from Ludus?`,
    icon: 'warn', tone: 'warn', destructive: true,
    confirmLabel: 'Remove from Ludus',
    body: frag(
      el('p', { text: `${displayName(person.user)} will no longer appear on the living-room sign-in screen and will lose access to the shared game libraries.` }),
      assurances(
        'Their Linux account is not deleted.',
        'Their home folder, saves and settings are not touched.',
        'No installed games are removed from any library.',
        'You can enrol them again at any time.'
      )
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/users/remove', body: { user: person.user },
    busyLabel: 'Removing…',
    success: `${displayName(person.user)} was removed from Ludus`,
    detail: 'No account, home folder or game data was deleted.',
    failure: `${displayName(person.user)} could not be removed`
  });
}

/* ------------------------------------------------------------------ *
 * View: Shared libraries
 * ------------------------------------------------------------------ */

async function viewLibraries() {
  const [libraries, defaultLibrary, candidates, personal, doctor, storage] = await Promise.all([
    load.libraries(), load.defaultLibrary(), load.candidates(), load.personal(), load.doctor(), load.storage()
  ]);

  const configured = new Set(libraries.map(entry => entry.path));
  const openCandidates = candidates.filter(entry => !configured.has(entry.suggested));

  return frag(
    card(
      cardHead('Shared game libraries',
        'A shared library is one folder every player installs into, so a game is only downloaded and stored once.'),
      el('div', { class: 'alert', dataset: { tone: 'info' } },
        el('span', { class: 'alert-icon' }, icon('lock')),
        el('div', { class: 'alert-body' },
          el('strong', { text: 'Shared games, private settings' }),
          el('p', { text: 'Game files are shared. Each player’s Proton compatibility data and shader cache stay private in their own home folder, so save games and settings never mix.' })
        )
      )
    ),

    libraries.length
      ? el('div', { class: 'grid grid-2' },
        libraries.map(library => libraryCard(library, { defaultLibrary, candidates, doctor, storage })))
      : empty('libraries', 'No shared libraries yet',
        'Choose a disk below and Ludus will create a shared game folder on it.'),

    card(
      cardHead('Add a shared library', 'Ludus creates a standard shared game folder on the disk you choose.'),
      openCandidates.length
        ? addLibraryForm(openCandidates)
        : el('p', { class: 'stat-note', text: 'Every suitable mounted disk already has a shared library. Attach another disk in Disk tools, or use the advanced option below.' }),
      disclosure('Advanced: use an exact folder', advancedLibraryForm(), 'card-disclosure')
    ),

    personalLibrariesCard(personal)
  );
}

function libraryCard(library, context) {
  const { defaultLibrary, candidates, doctor, storage } = context;
  const isDefault = library.path === defaultLibrary;
  const mount = doctor.facts.mounts.get(library.path);
  const bind = doctor.facts.bindStates.get(library.path);
  const space = storageFor(library.path, storage);

  const bindLabels = {
    locked: ['ok', 'Private data locked while idle'],
    active: ['accent', 'Private data in use by the active player'],
    problem: ['err', 'Private data needs repair']
  };
  const bindInfo = bindLabels[bind] || ['warn', 'Private data state unknown'];

  const buttons = [];
  const labelButton = el('button', { class: 'btn btn-sm', type: 'button' },
    icon('settings'), el('span', { text: 'Set label' }));
  labelButton.addEventListener('click', () => confirmSetLibraryLabel(library, labelButton));
  buttons.push(labelButton);
  if (!isDefault) {
    const defaultButton = el('button', { class: 'btn btn-sm', type: 'button' },
      icon('star'), el('span', { text: 'Make default' }));
    defaultButton.addEventListener('click', () => confirmSetDefault(library, candidates, defaultButton));
    buttons.push(defaultButton);
  }
  const removeButton = el('button', { class: 'btn btn-sm btn-danger', type: 'button' },
    icon('trash'), el('span', { text: 'Stop managing' }));
  removeButton.addEventListener('click', () => confirmRemoveLibrary(library, candidates, removeButton));
  buttons.push(removeButton);

  let spaceNode = null;
  if (space && Number(space.total) > 0) {
    const used = 1 - Number(space.free) / Number(space.total);
    spaceNode = el('div', { class: 'stack-sm' },
      el('span', { text: `${formatBytes(space.free)} free of ${formatBytes(space.total)}` }),
      meter(used, used > 0.95 ? 'err' : (used > 0.85 ? 'warn' : null))
    );
  }

  return el('section', { class: 'card tile' },
    el('div', { class: 'tile-top' },
      el('span', { class: 'tile-mark' }, icon('libraries')),
      el('div', null,
        el('div', { class: 'tile-title' },
          el('span', { text: libraryTitle(library.path, candidates) }),
          isDefault ? badge('accent', 'Default', 'star') : null
        ),
        el('div', { class: 'path', text: library.path })
      )
    ),
    factList([
      ['Disk', mount ? `${deviceName(mount.device)} · ${mount.fstype}` : 'Not currently attached'],
      ['Label', library.label || 'No label'],
      spaceNode ? ['Free space', spaceNode] : null,
      ['Private data', badge(bindInfo[0], bindInfo[1], SEVERITY_ICON[bindInfo[0]] || 'lock')]
    ]),
    el('div', { class: 'actions' }, buttons),
    disclosure('Technical details', factList([
      ['Exact path', el('span', { class: 'path', text: library.path })],
      ['Ludus library id', el('span', { class: 'path', text: library.id })],
      ['Shared games', el('span', { class: 'path', text: library.path + '/steamapps/common' })],
      ['Private Proton data', el('span', { class: 'path', text: library.path + '/steamapps/compatdata' })],
      ['Private shader cache', el('span', { class: 'path', text: library.path + '/steamapps/shadercache' })],
      ['Backing mount', mount ? `${mount.device} (${mount.fstype})` : 'unresolved']
    ]), 'card-disclosure')
  );
}

async function confirmSetLibraryLabel(library, button) {
  const input = el('input', {
    type: 'text', value: library.label || '', maxlength: '64',
    placeholder: 'e.g. Fast NVMe', autocomplete: 'off'
  });
  const confirmed = await ask({
    title: 'Set shared library label',
    icon: 'settings', tone: 'accent', confirmLabel: 'Save label',
    body: frag(
      el('p', { text: 'This label is written to the shared library and every Steam-ready player’s Steam library list.' }),
      el('div', { class: 'field' },
        el('label', { text: 'Library label' }), input,
        el('span', { class: 'help', text: 'Up to 64 characters. Leave blank to clear it.' })
      ),
      reviewList([['Library', library.path]]),
      assurances('Steam must be closed for every player before the label can be changed.', 'No games, saves or install locations are changed.')
    )
  });
  if (!confirmed) return;
  const label = input.value.trim();
  if (label.length > 64 || /["\\\r\n]/.test(label)) {
    toast('err', 'Invalid label', 'Use at most 64 characters and omit quotes, backslashes and line breaks.');
    return;
  }
  await mutate(button, {
    path: '/api/libraries/label', body: { path: library.path, label },
    busyLabel: 'Saving…', success: 'Shared library label updated',
    detail: label ? `Steam will show “${label}” for this library.` : 'The shared library label was cleared.',
    failure: 'The shared library label could not be updated'
  });
}

function addLibraryForm(candidates) {
  const select = el('select', { name: 'mount', required: true, id: 'library-mount' },
    candidates.map(entry => el('option', {
      value: entry.mount,
      text: `${mountName(entry.mount)} — ${entry.device} (${entry.fstype}) at ${entry.mount}`
    }))
  );
  const button = el('button', { class: 'btn btn-primary', type: 'submit' },
    icon('plus'), el('span', { text: 'Add shared library' }));

  return el('form', {
    class: 'form-row',
    onSubmit: event => {
      event.preventDefault();
      const chosen = candidates.find(entry => entry.mount === select.value);
      if (chosen) confirmAddLibrary(chosen, button);
    }
  },
    el('div', { class: 'field' },
      el('label', { for: 'library-mount', text: 'Disk to use' }),
      select,
      el('span', { class: 'help', text: 'Only writable, already-mounted disks are listed. Nothing is formatted or erased.' })
    ),
    button
  );
}

function advancedLibraryForm() {
  const input = el('input', { type: 'text', name: 'path', required: true, id: 'library-path', placeholder: '/absolute/path/to/an/existing/folder', spellcheck: 'false' });
  const button = el('button', { class: 'btn', type: 'submit' }, el('span', { text: 'Add exact folder' }));

  return frag(
    el('p', { class: 'stat-note', text: 'Use this only if you already have a folder you want Ludus to manage. It must already exist and be reachable by every player.' }),
    el('form', {
      class: 'form-row',
      onSubmit: event => {
        event.preventDefault();
        const path = input.value.trim();
        if (path) confirmAddExact(path, button);
      }
    },
      el('div', { class: 'field' },
        el('label', { for: 'library-path', text: 'Existing folder' }),
        input
      ),
      button
    )
  );
}

function personalLibrariesCard(personal) {
  const rows = [];
  for (const person of personal || []) {
    for (const path of (person.paths || [])) rows.push({ user: person.user, path });
  }
  return card(
    cardHead('Personal Steam libraries',
      'Extra library folders a player added in Steam themselves. Ludus does not manage these.'),
    rows.length
      ? el('div', { class: 'stack-sm' }, rows.map(row => {
        const button = el('button', { class: 'btn btn-sm btn-danger', type: 'button' },
          icon('trash'), el('span', { text: 'Unregister' }));
        button.addEventListener('click', () => confirmRemovePersonal(row, button));
        return el('div', { class: 'alert' },
          el('span', { class: 'alert-icon' }, icon('players')),
          el('div', { class: 'alert-body' },
            el('strong', { text: `${displayName(row.user)}’s own library` }),
            el('p', { class: 'path', text: row.path }),
            el('div', { class: 'actions' }, button)
          )
        );
      }))
      : el('p', { class: 'stat-note', text: 'No personal Steam libraries are registered. Players appear here only after their first Steam sign-in.' })
  );
}

async function confirmAddLibrary(candidate, button) {
  const confirmed = await ask({
    title: 'Create a shared library on this disk?',
    icon: 'libraries', tone: 'accent',
    confirmLabel: 'Create shared library',
    body: frag(
      el('p', { text: 'Ludus will create one shared game folder on this disk and start managing it.' }),
      reviewList([
        ['Disk', `${candidate.device} (${candidate.fstype})`],
        ['Mounted at', candidate.mount],
        ['Folder created', candidate.suggested]
      ]),
      assurances(
        'Nothing is formatted and no existing files are erased.',
        'Only the new shared folder is created.',
        'Each player’s Proton and shader files stay private in their own home folder.'
      )
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/libraries/add-default', body: { mount: candidate.mount },
    busyLabel: 'Creating…',
    success: 'Shared library created',
    detail: 'Each player’s Steam is updated at their next Ludus session.',
    failure: 'The shared library could not be created'
  });
}

async function confirmAddExact(path, button) {
  const confirmed = await ask({
    title: 'Manage this folder as a shared library?',
    icon: 'libraries', tone: 'accent',
    confirmLabel: 'Add shared library',
    body: frag(
      el('p', { text: 'Ludus will apply shared group permissions to this folder and register it with every player’s Steam.' }),
      reviewList([['Folder', path]]),
      assurances(
        'The folder must already exist. Nothing is formatted or erased.',
        'Existing files stay where they are; only ownership and permissions are adjusted for sharing.',
        'Ludus refuses if any player currently has Steam open.'
      )
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/libraries/add', body: { path },
    busyLabel: 'Adding…',
    success: 'Shared library added',
    failure: 'That folder could not be added'
  });
}

async function confirmSetDefault(library, candidates, button) {
  const confirmed = await ask({
    title: 'Install new games here by default?',
    icon: 'star', tone: 'accent',
    confirmLabel: 'Make it the default',
    body: frag(
      el('p', { text: `Steam will offer ${libraryTitle(library.path, candidates)} first when any player installs a new game.` }),
      reviewList([['Library', library.path]]),
      assurances(
        'No games are moved or deleted.',
        'Players can still choose a different library in Steam.',
        'Players who have not signed into Steam yet inherit this choice automatically.'
      )
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/libraries/default', body: { path: library.path },
    busyLabel: 'Updating…',
    success: 'Default library updated',
    failure: 'The default library could not be changed'
  });
}

async function confirmRemoveLibrary(library, candidates, button) {
  const confirmed = await ask({
    title: `Stop managing ${libraryTitle(library.path, candidates)}?`,
    icon: 'warn', tone: 'warn', destructive: true,
    confirmLabel: 'Stop managing it',
    body: frag(
      el('p', { text: 'Ludus will stop keeping this folder’s shared permissions in order and will stop registering it with each player’s Steam.' }),
      reviewList([['Folder', library.path]]),
      assurances(
        'No games or files are deleted.',
        'The folder and everything in it stays exactly where it is.',
        'You can add it back at any time.'
      )
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/libraries/remove', body: { path: library.path },
    busyLabel: 'Removing…',
    success: 'Ludus no longer manages that library',
    detail: 'No games or private data were deleted.',
    failure: 'That library could not be removed'
  });
}

async function confirmRemovePersonal(row, button) {
  const confirmed = await ask({
    title: `Unregister this folder from ${displayName(row.user)}’s Steam?`,
    icon: 'warn', tone: 'warn', destructive: true,
    confirmLabel: 'Unregister folder',
    body: frag(
      el('p', { text: 'Steam will stop listing this folder as one of their library locations.' }),
      reviewList([['Player', row.user], ['Folder', row.path]]),
      assurances(
        'No games or files are deleted.',
        'Only Steam’s library list is edited, and a backup of each file is kept.',
        'They can add the folder back from inside Steam at any time.'
      )
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/users/personal-libraries/remove', body: { user: row.user, path: row.path },
    busyLabel: 'Unregistering…',
    success: 'Steam library entry removed',
    detail: 'No files were deleted.',
    failure: 'That Steam entry could not be removed'
  });
}

/* ------------------------------------------------------------------ *
 * View: Disk tools
 * ------------------------------------------------------------------ */

async function viewDisks() {
  const disks = await load.disks();

  return frag(
    card(
      cardHead('Attach another disk',
        'Use this to make an existing drive available to Ludus so you can put a shared game library on it.'),
      el('div', { class: 'alert', dataset: { tone: 'info' } },
        el('span', { class: 'alert-icon' }, icon('shield')),
        el('div', { class: 'alert-body' },
          el('strong', { text: 'Nothing is formatted and nothing is erased' }),
          el('p', { text: 'Ludus only attaches drives that already contain a supported Linux filesystem (ext4, XFS or Btrfs). Existing files are left untouched and stay exactly as they are.' })
        )
      ),
      el('div', { class: 'steps' },
        step(1, 'Choose a drive', 'Only drives that are already formatted and not currently in use are listed.'),
        step(2, 'Pick a folder to reach it through', 'The default is /mnt/games. Ludus creates that folder for you.'),
        step(3, 'Review and confirm', 'You will see exactly what will happen before anything changes.')
      )
    ),

    disks.length
      ? el('div', { class: 'grid grid-2' }, disks.map(disk => diskCard(disk)))
      : empty('disks', 'No drives available to attach',
        'Every supported drive is already in use, or no extra drive is connected. Connect a drive that is already formatted as ext4, XFS or Btrfs and refresh this page.')
  );
}

function step(number, title, description) {
  return el('div', { class: 'step' },
    el('span', { class: 'step-num', 'aria-hidden': 'true', text: String(number) }),
    el('div', { class: 'step-body' },
      el('strong', { text: title }),
      el('p', { text: description })
    )
  );
}

function diskCard(disk) {
  const inputId = 'mount-' + String(disk.path).replace(/[^A-Za-z0-9]+/g, '-');
  const input = el('input', {
    type: 'text', id: inputId, value: disk.mountpoint || '/mnt/games',
    required: true, spellcheck: 'false'
  });
  const button = el('button', { class: 'btn btn-primary', type: 'submit' },
    icon('arrow'), el('span', { text: 'Review and attach' }));

  return el('section', { class: 'card tile' },
    el('div', { class: 'tile-top' },
      el('span', { class: 'tile-mark' }, icon('disks')),
      el('div', null,
        el('div', { class: 'tile-title' },
          el('span', { text: disk.label ? disk.label : 'Unnamed drive' }),
          badge(null, String(disk.fstype).toUpperCase()),
          formatBytes(disk.size) ? badge(null, formatBytes(disk.size)) : null
        ),
        el('div', { class: 'path', text: disk.path })
      )
    ),
    factList([
      formatBytes(disk.size) ? ['Capacity', formatBytes(disk.size)] : null,
      ['Filesystem', `${disk.fstype} — already formatted, supported by Ludus`],
      ['Currently', 'Not in use by this computer'],
      ['Contents', 'Left exactly as they are']
    ]),
    el('form', {
      class: 'form-row',
      onSubmit: event => {
        event.preventDefault();
        const target = input.value.trim();
        if (target) confirmMount(disk, target, button);
      }
    },
      el('div', { class: 'field' },
        el('label', { for: inputId, text: 'Reach this drive through' }),
        input,
        el('span', { class: 'help', text: 'An absolute path whose parent folder already exists, for example /mnt/games.' })
      ),
      button
    ),
    disclosure('Technical details', factList([
      ['Partition', el('span', { class: 'path', text: disk.path })],
      ['Filesystem type', el('span', { class: 'path', text: disk.fstype })],
      ['Filesystem UUID', el('span', { class: 'path', text: disk.uuid || 'unknown' })],
      ['Filesystem label', el('span', { class: 'path', text: disk.label || 'none' })],
      ['fstab options', el('span', { class: 'path', text: 'defaults,nofail,x-systemd.device-timeout=10' })]
    ]), 'card-disclosure')
  );
}

async function confirmMount(disk, target, button) {
  const confirmed = await ask({
    title: 'Attach this drive to your system?',
    icon: 'disks', tone: 'accent',
    confirmLabel: 'Attach this drive',
    body: frag(
      el('p', { text: 'Please check the details below before continuing.' }),
      reviewList([
        ['Drive', disk.label ? `${disk.label} (${disk.path})` : disk.path],
        ['Filesystem', `${disk.fstype} — existing, will be used as-is`],
        ['Identified by', 'UUID ' + (disk.uuid || 'unknown')],
        ['Reachable at', target]
      ]),
      assurances(
        'The existing filesystem is mounted as it is. It is not formatted.',
        'No files on the drive are erased, moved or changed.',
        `The folder ${target} is created if it does not exist.`,
        'A line is added to /etc/fstab so the drive reattaches automatically after every restart.'
      ),
      el('p', { text: 'You can then create a shared game library on this drive from the Libraries page.' })
    )
  });
  if (!confirmed) return;
  const done = await mutate(button, {
    path: '/api/disks/mount', body: { path: disk.path, mountpoint: target },
    busyLabel: 'Attaching…',
    success: 'Drive attached',
    detail: `It is now reachable at ${target} and will reattach automatically after a restart.`,
    failure: 'That drive could not be attached'
  });
  if (done) toast('info', 'Next step', 'Create a shared game library on this drive from the Libraries page.');
}

/* ------------------------------------------------------------------ *
 * View: Health and repair
 * ------------------------------------------------------------------ */

async function viewHealth() {
  const doctor = await load.doctor();

  const groups = CHECK_GROUPS.map(group => ({
    meta: group,
    checks: doctor.checks.filter(check => check.group === group.id)
  })).filter(group => group.checks.length);

  return frag(
    healthHero(doctor, { hideLink: true }),
    repairCard(),
    el('div', { class: 'stack' }, groups.map(group => checkGroup(group))),
    card(
      cardHead('Advanced diagnostic output',
        'The complete, unedited output of the Ludus self-check. Useful when reporting a problem.'),
      disclosure('Show raw diagnostic output',
        el('pre', { class: 'raw', text: doctor.raw || 'The self-check produced no output.' }),
        'card-disclosure')
    )
  );
}

function checkGroup(group) {
  const counts = { ok: 0, warn: 0, err: 0 };
  for (const check of group.checks) counts[check.severity] += 1;

  return el('section', { class: 'check-group' },
    el('div', { class: 'check-group-head' },
      icon(group.meta.icon),
      el('div', null,
        el('h3', { text: group.meta.title }),
        el('p', { text: group.meta.blurb })
      ),
      el('div', { class: 'hero-counts' },
        counts.err ? el('span', { class: 'count', dataset: { tone: 'err' } }, el('span', { text: `${counts.err} ${plural(counts.err, 'problem')}` })) : null,
        counts.warn ? el('span', { class: 'count', dataset: { tone: 'warn' } }, el('span', { text: `${counts.warn} to review` })) : null,
        !counts.err && !counts.warn ? el('span', { class: 'count', dataset: { tone: 'ok' } }, icon('ok', 'icon icon-sm'), el('span', { text: 'All good' })) : null
      )
    ),
    group.checks.map(check => el('div', { class: 'check', dataset: { sev: check.severity } },
      el('div', { class: 'check-row' },
        el('span', { class: 'check-mark' }, icon(SEVERITY_ICON[check.severity])),
        el('div', { class: 'check-text' },
          el('strong', { text: check.title }),
          check.explanation ? el('p', { text: check.explanation }) : null
        )
      )
    )),
    disclosure('Technical detail', el('pre', { class: 'raw', text: group.checks.map(check => check.detail).join('\n') }))
  );
}

function repairCard() {
  const button = el('button', { class: 'btn btn-primary', type: 'button' },
    icon('wrench'), el('span', { text: 'Run safe repair' }));
  button.addEventListener('click', () => confirmRepair(button));

  return card(
    cardHead('Repair shared libraries',
      'Puts the shared folders and permissions back the way Ludus expects them.'),
    el('div', { class: 'alert', dataset: { tone: 'info' } },
      el('span', { class: 'alert-icon' }, icon('shield')),
      el('div', { class: 'alert-body' },
        el('strong', { text: 'What repair does, and what it will not do' }),
        el('p', { text: 'Repair re-creates missing shared folders, restores group ownership and permissions across each shared library, and reseals every player’s private Proton and shader folders.' })
      )
    ),
    assurances(
      'It never deletes games, save files or home data.',
      'It refuses to run while any player has Steam open.',
      'It does not move games between libraries and does not touch other disks.',
      'It cannot fix a disconnected drive, a stopped service or a firewall problem.'
    ),
    el('div', { class: 'actions' }, button)
  );
}

async function confirmRepair(button) {
  const confirmed = await ask({
    title: 'Run safe repair now?',
    icon: 'wrench', tone: 'accent',
    confirmLabel: 'Run repair',
    body: frag(
      el('p', { text: 'Ludus will go through every shared library and restore the folders and permissions it expects.' }),
      assurances(
        'No games, saves or home data are deleted.',
        'It stops immediately if a player has Steam open.',
        'Only the shared libraries Ludus already manages are touched.'
      ),
      el('p', { text: 'On a large library this can take a little while.' })
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/repair', body: {},
    busyLabel: 'Repairing…',
    success: 'Repair finished',
    detail: 'Shared folders and permissions were restored. No game or home data was deleted.',
    failure: 'Repair could not be completed'
  });
}

/* ------------------------------------------------------------------ *
 * View: Settings
 * ------------------------------------------------------------------ */

/* The backend accepts exactly these four mode strings. The selector below
   builds one from a require-sign-in toggle plus two independent method
   checkboxes, rather than a four-way radio choice where the combined option
   ("either of the above") reads as ambiguous next to three plain ones. */
const MODE_SUMMARY = {
  none: 'Nobody will be asked to sign in.',
  pam: 'Only a computer administrator account will be accepted.',
  local: 'Only the separate Ludus account will be accepted.',
  'pam+local': 'A computer administrator account or the separate Ludus account will be accepted.'
};

function modeFor(requireSignIn, allowPam, allowLocal) {
  if (!requireSignIn) return 'none';
  if (allowPam && allowLocal) return 'pam+local';
  if (allowPam) return 'pam';
  if (allowLocal) return 'local';
  return null; // no method chosen; the caller must ask for one
}

async function viewSettings() {
  const [settings, doctor] = await Promise.all([load.settings(), load.doctor()]);
  const networkChecks = doctor.checks.filter(check => check.group === 'network');

  return frag(
    authCard(settings),
    compatibilityCard(settings),
    card(
      cardHead('How this page is reached',
        'These limits are always applied and cannot be turned off from here.'),
      assurances(
        'This page only answers requests from this computer and from directly connected private home networks.',
        'Only the one control panel port is opened on the firewall; no other service is exposed.',
        'Every change you make here is carried out by a separate service that accepts only a fixed list of operations.'
      ),
      networkChecks.length
        ? disclosure('Technical details', el('pre', { class: 'raw', text: networkChecks.map(check => check.detail).join('\n') }), 'card-disclosure')
        : null
    )
  );
}

function subHead(title, description) {
  return el('div', { class: 'card-head' },
    el('div', null, el('h3', { text: title }), description ? el('p', { text: description }) : null)
  );
}

function authCard(settings) {
  const mode = settings.authMode || 'none';
  const requireSignIn = el('input', { type: 'checkbox', checked: mode !== 'none' ? true : null });
  const allowPam = el('input', { type: 'checkbox', checked: (mode === 'pam' || mode === 'pam+local') ? true : null });
  const allowLocal = el('input', { type: 'checkbox', checked: (mode === 'local' || mode === 'pam+local') ? true : null });

  const methodsHint = el('p', { class: 'stat-note', text: 'At least one method must stay selected — untick one to free up the other.' });
  const methods = el('div', { class: 'choices' },
    el('label', { class: 'choice' },
      allowPam,
      el('div', { class: 'choice-text' },
        el('strong', { text: 'Computer administrator account' }),
        el('span', { text: 'Accept sign-in from an existing administrator account on this computer.' })
      )
    ),
    el('label', { class: 'choice' },
      allowLocal,
      el('div', { class: 'choice-text' },
        el('strong', { text: 'Separate Ludus account' }),
        el('span', { text: 'Accept a username and password used only for this page, set up below.' })
      )
    ),
    methodsHint
  );

  const hasPassword = Boolean(settings.username);
  const username = el('input', { type: 'text', id: 'ludus-user', name: 'username', required: true, maxlength: '64', autocomplete: 'username', spellcheck: 'false', value: settings.username || '' });
  const password = el('input', { type: 'password', id: 'ludus-pass', name: 'password', required: true, autocomplete: 'new-password', placeholder: hasPassword ? '••••••••••' : null });
  const repeat = el('input', { type: 'password', id: 'ludus-pass2', name: 'confirm', required: true, autocomplete: 'new-password' });
  const saveButton = el('button', { class: 'btn btn-primary', type: 'submit' }, el('span', { text: 'Save this account' }));

  const credentials = el('div', { class: 'stack-sm' },
    subHead('Separate Ludus account details',
      hasPassword
        ? 'A username and password are already saved. Enter a new password to replace it.'
        : 'This does not need to match any account on this computer.'),
    el('form', {
      onSubmit: event => {
        event.preventDefault();
        if (password.value !== repeat.value) {
          toast('err', 'The two passwords do not match', 'Type the same password in both boxes and try again.');
          repeat.focus();
          return;
        }
        confirmCredentials(username.value, password.value, saveButton);
      }
    },
      el('div', { class: 'form-row form-row-top' },
        el('div', { class: 'field' },
          el('label', { for: 'ludus-user', text: 'Username' }),
          username,
          el('span', { class: 'help', text: 'Any name you like. It is not a computer account.' })
        ),
        el('div', { class: 'field' },
          el('label', { for: 'ludus-pass', text: 'Password' }),
          password
        ),
        el('div', { class: 'field' },
          el('label', { for: 'ludus-pass2', text: 'Repeat password' }),
          repeat
        )
      ),
      el('div', { class: 'actions actions-top' }, saveButton)
    ),
    el('p', { class: 'stat-note', text: 'The password itself is never stored. Only a one-way fingerprint of it is kept on this machine, and only the management service can read it.' })
  );

  // Enforce the constraint by disabling whichever checkbox is the sole
  // remaining method, rather than allowing an invalid state and validating
  // only on submit — a locked checkbox is unambiguous about why it won't budge.
  const syncUI = () => {
    methods.hidden = !requireSignIn.checked;
    if (requireSignIn.checked && !allowPam.checked && !allowLocal.checked) allowPam.checked = true;
    const onlyPam = allowPam.checked && !allowLocal.checked;
    const onlyLocal = allowLocal.checked && !allowPam.checked;
    allowPam.disabled = requireSignIn.checked && onlyPam;
    allowLocal.disabled = requireSignIn.checked && onlyLocal;
    methodsHint.hidden = !(allowPam.disabled || allowLocal.disabled);
    // allowLocal.checked persists even while sign-in is off (methods box
    // hidden, checkbox untouched) — both conditions must hold, not just this one.
    credentials.hidden = !(requireSignIn.checked && allowLocal.checked);
  };
  requireSignIn.addEventListener('change', syncUI);
  allowPam.addEventListener('change', syncUI);
  allowLocal.addEventListener('change', syncUI);
  syncUI();

  const applyButton = el('button', { class: 'btn btn-primary', type: 'submit' },
    icon('key'), el('span', { text: 'Apply sign-in setting' }));

  return card(
    cardHead('Who can open this control panel',
      'Choose whether a sign-in is required, and which accounts are accepted.'),
    el('form', {
      onSubmit: event => {
        event.preventDefault();
        const next = modeFor(requireSignIn.checked, allowPam.checked, allowLocal.checked);
        if (next === null) {
          toast('err', 'Choose at least one sign-in method',
            'Turn on the computer administrator account, the separate Ludus account, or both — or turn off “Require a sign-in”.');
          return;
        }
        if (next === mode) {
          toast('info', 'Nothing to change', 'That sign-in setting is already in use.');
          return;
        }
        confirmAuthMode(next, applyButton);
      }
    },
      el('label', { class: 'switch-row' },
        requireSignIn,
        el('div', { class: 'choice-text' },
          el('strong', { text: 'Require a sign-in' }),
          el('span', { text: 'When off, anyone on your home network can open this page and change how the machine is set up.' })
        )
      ),
      methods,
      el('div', { class: 'actions actions-top' }, applyButton)
    ),
    credentials
  );
}

function compatibilityCard(settings) {
  const toggle = el('input', { type: 'checkbox', checked: settings.vscode ? true : null });
  toggle.addEventListener('change', () => {
    const wanted = toggle.checked;
    toggle.checked = settings.vscode;
    confirmVscode(wanted, toggle);
  });

  return card(
    cardHead('Compatibility', 'Optional adjustments for specific development tools. Leave these off unless you need them.'),
    settings.vscodeRequested && !settings.vscode
      ? el('div', { class: 'alert', dataset: { tone: 'err' } },
        el('span', { class: 'alert-icon' }, icon('warn')),
        el('div', { class: 'alert-body' },
          el('strong', { text: 'VS Code forwarding needs repair' }),
          el('p', { text: 'It is enabled in Ludus, but its SELinux rule is not currently installed. VS Code Remote SSH will not work until that rule is restored.' }),
          el('div', { class: 'actions actions-top' }, vscodeRepairButton())
        )
      )
      : null,
    el('label', { class: 'switch-row' },
      toggle,
      el('div', { class: 'choice-text' },
        el('strong', { text: 'Allow VS Code Remote SSH port forwarding' }),
        el('span', { text: 'Off by default. Turn this on only if VS Code Remote SSH cannot forward ports to this machine. It loads a small extra security rule that permits that one specific case, and nothing more.' })
      )
    ),
    disclosure('Technical details',
      el('pre', { class: 'raw', text: 'Loads or removes the SELinux policy module ludus_vscode_ssh\n(/usr/local/lib/ludus/ludus_vscode_ssh.pp) and records the choice in\n/etc/ludus/webui.json as vscode_ssh_forwarding.' }),
      'card-disclosure')
  );
}

function vscodeRepairButton() {
  const button = el('button', { class: 'btn btn-sm btn-primary', type: 'button' },
    icon('wrench'), el('span', { text: 'Repair VS Code forwarding' }));
  button.addEventListener('click', () => mutate(button, {
    path: '/api/settings/vscode-forwarding/repair',
    busyLabel: 'Repairing…',
    success: 'VS Code forwarding repaired',
    detail: 'The selected SELinux compatibility rule has been restored.',
    failure: 'VS Code forwarding could not be repaired'
  }));
  return button;
}

async function confirmAuthMode(mode, button) {
  const risky = mode === 'none';
  const confirmed = await ask({
    title: risky ? 'Turn off sign-in for this page?' : 'Change how this page is signed into?',
    icon: risky ? 'warn' : 'key',
    tone: risky ? 'warn' : 'accent',
    destructive: risky,
    confirmLabel: risky ? 'Turn off sign-in' : 'Apply setting',
    body: frag(
      el('p', { text: MODE_SUMMARY[mode] }),
      risky
        ? assurances(
          'Anyone who can reach your home network can open this page.',
          'They would be able to enrol or remove players and change shared libraries.',
          'This page still refuses connections from outside your home network.'
        )
        : assurances(
          'Existing players, libraries and games are not affected.',
          'You will be asked to sign in again the next time you load this page.'
        )
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/settings/auth-mode', body: { mode },
    busyLabel: 'Applying…',
    success: 'Sign-in setting updated',
    detail: mode === 'none' ? 'This page no longer asks for a password.' : 'Reload this page to sign in with the new setting.',
    failure: 'The sign-in setting could not be changed'
  });
}

async function confirmCredentials(username, password, button) {
  const confirmed = await ask({
    title: 'Save this Ludus account?',
    icon: 'key', tone: 'accent',
    confirmLabel: 'Save account',
    body: frag(
      el('p', { text: `The control panel account will be saved as “${username}”. Any previous Ludus account details are replaced.` }),
      assurances(
        'This is not a computer login. It only opens this page.',
        'Only a one-way fingerprint of the password is stored.',
        'Your browser will ask for the new details the next time you load this page.'
      )
    )
  });
  if (!confirmed) return;
  await mutate(button, {
    path: '/api/credentials', body: { username, password },
    busyLabel: 'Saving…',
    success: 'Ludus account saved',
    detail: 'Reload this page to sign in with the new details.',
    failure: 'That account could not be saved'
  });
}

async function confirmVscode(enabled, toggle) {
  const confirmed = await ask({
    title: enabled ? 'Allow VS Code Remote SSH port forwarding?' : 'Remove the VS Code compatibility rule?',
    icon: 'shield', tone: enabled ? 'warn' : 'accent',
    confirmLabel: enabled ? 'Turn it on' : 'Turn it off',
    body: enabled
      ? frag(
        el('p', { text: 'This loads a small extra security rule so VS Code Remote SSH can forward network ports to this machine.' }),
        assurances(
          'It permits that one specific case only.',
          'It changes nothing about players, games or shared libraries.',
          'You can turn it off again here at any time.'
        )
      )
      : frag(
        el('p', { text: 'The extra rule is removed and the system returns to its default protection.' }),
        assurances('VS Code Remote SSH port forwarding may stop working after this.')
      )
  });
  if (!confirmed) return;   // the caller already restored the checkbox
  await mutate(toggle, {
    path: '/api/settings/vscode-forwarding', body: { enabled },
    busyLabel: 'Applying…',
    success: enabled ? 'VS Code compatibility turned on' : 'VS Code compatibility turned off',
    failure: 'That compatibility setting could not be changed'
  });
}

/* ------------------------------------------------------------------ *
 * Router
 * ------------------------------------------------------------------ */

const ROUTES = {
  dashboard: { title: 'Dashboard', subtitle: 'An overview of this Ludus machine.', render: viewDashboard },
  players: { title: 'Players', subtitle: 'Who can sign in and play on this machine.', render: viewPlayers },
  libraries: { title: 'Libraries', subtitle: 'Where shared games are installed and kept.', render: viewLibraries },
  disks: { title: 'Disk tools', subtitle: 'Attach another drive so Ludus can use it.', render: viewDisks },
  health: { title: 'Health', subtitle: 'What is working, what needs attention, and how to fix it.', render: viewHealth },
  settings: { title: 'Settings', subtitle: 'Sign-in and compatibility options for this control panel.', render: viewSettings }
};

const state = { checkedAt: null, flash: null, token: 0 };

const view = document.getElementById('view');
const pageTitle = document.getElementById('page-title');
const pageSubtitle = document.getElementById('page-subtitle');
const checkedAt = document.getElementById('checked-at');
const refreshButton = document.getElementById('refresh');
const sidebarDot = document.getElementById('sidebar-dot');
const sidebarState = document.getElementById('sidebar-state');

function currentRoute() {
  const name = location.hash.replace(/^#\/?/, '');
  return ROUTES[name] ? name : 'dashboard';
}

function skeleton() {
  const block = height => {
    const node = el('div', { class: 'skeleton skeleton-block' });
    node.style.height = height;
    return node;
  };
  return frag(
    block('96px'),
    el('div', { class: 'grid grid-3' }, block('148px'), block('148px'), block('148px'))
  );
}

function renderFlash() {
  if (!state.flash) return null;
  const flash = state.flash;
  return el('div', { class: 'alert', dataset: { tone: flash.tone } },
    el('span', { class: 'alert-icon' }, icon(SEVERITY_ICON[flash.tone] || 'info')),
    el('div', { class: 'alert-body' },
      el('strong', { text: flash.title }),
      el('p', { text: flash.message }),
      flash.raw ? disclosure('Technical detail', el('pre', { class: 'raw', text: flash.raw }), 'card-disclosure') : null
    )
  );
}

function updateSidebar() {
  load.doctor().then(data => {
    const labels = { ok: 'All systems ready', warn: 'Needs attention', err: 'Problem found' };
    sidebarDot.dataset.tone = data.tone;
    sidebarState.textContent = labels[data.tone];
    if (state.checkedAt) checkedAt.textContent = 'Checked at ' + timeOfDay(state.checkedAt);
  }).catch(() => {
    sidebarDot.dataset.tone = 'err';
    sidebarState.textContent = 'Cannot reach machine';
    checkedAt.textContent = '';
  });
}

async function navigate(options) {
  const settings = options || {};
  if (!settings.keepFlash) state.flash = null;

  const name = currentRoute();
  const route = ROUTES[name];
  const token = ++state.token;

  for (const item of document.querySelectorAll('.nav-item')) {
    if (item.dataset.route === name) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  }
  pageTitle.textContent = route.title;
  pageSubtitle.textContent = route.subtitle;
  document.title = 'Ludus — ' + route.title;

  view.setAttribute('aria-busy', 'true');
  view.replaceChildren(skeleton());

  let content;
  try {
    content = await route.render();
  } catch (error) {
    if (token !== state.token) return;
    content = el('div', { class: 'stack' },
      notice('err', 'This page could not be loaded', error.message || 'Something went wrong.',
        [el('button', {
          class: 'btn btn-sm', type: 'button',
          onClick: () => { invalidate(); navigate(); }
        }, icon('refresh'), el('span', { text: 'Try again' }))]),
      error.raw ? disclosure('Technical detail', el('pre', { class: 'raw', text: error.raw }), 'card-disclosure') : null
    );
  }
  if (token !== state.token) return;

  const flash = renderFlash();
  state.flash = null;
  view.replaceChildren(el('div', { class: 'stack' }, flash, content));
  view.removeAttribute('aria-busy');
  checkedAt.textContent = state.checkedAt ? 'Checked at ' + timeOfDay(state.checkedAt) : '';
  // Moving focus to the new page is what a full page load would have done.
  if (settings.focus) view.focus();
  updateSidebar();
}

refreshButton.addEventListener('click', async () => {
  setBusy(refreshButton, true, 'Checking…');
  invalidate();
  await navigate();
  setBusy(refreshButton, false);
});

window.addEventListener('hashchange', () => navigate({ focus: true }));

if (!location.hash) location.replace('#/dashboard');
navigate();

})();
