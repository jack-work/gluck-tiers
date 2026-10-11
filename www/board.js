/* gluck-tiers board. Reasoning and measurements live in doc/board.md.
 *
 * heft supplies the lift and the settle. It has no drop, so the drop is here:
 * rectangle hit test on pointerup, then reparent. */

(function () {
  'use strict';

  var SLACK2 = 64;          /* 8px squared, matching heft's own threshold */
  var EDGE = 64;            /* autoscroll band at the top and bottom */
  var EDGE_STEP = 14;
  var SAVE_WAIT = 500;

  var qs = new URLSearchParams(location.search);
  var boilCards = qs.get('boil') === 'cards';

  /* One template serves every list, so the slug comes from the URL. The path
   * is authoritative; ?list= is kept for the fixture harness. Before the
   * redirect off / resolves there is no slug, and the picker stands in. */
  function slugFromLocation() {
    var m = location.pathname.match(/^\/l\/([^\/?#]+)/);
    if (m) return decodeURIComponent(m[1]);
    return qs.get('list') || null;
  }
  var slug = slugFromLocation();
  var imported = false;

  var board = document.getElementById('board');
  var pool = document.getElementById('pool');
  var tpl = document.getElementById('card-tpl');
  var savedEl = document.getElementById('saved');
  var poolCount = document.getElementById('poolcount');

  var list = null;
  var devMode = false;
  var saveTimer = null;

  /* ── data ──────────────────────────────────────────────────────────── */

  function getList() {
    return fetch('/api/list/' + encodeURIComponent(slug), { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('api ' + r.status); return r.json(); })
      .catch(function () {
        devMode = true;
        return fetch('../examples/' + slug + '.json').then(function (r) {
          if (!r.ok) throw new Error('no fixture for ' + slug);
          return r.json();
        }).then(devShape);
      });
  }

  /* The service resolves images to /img/<sha>. Without the service there is
   * no resolver, so the fixture's original CDN url stands in. Dev only. */
  function devShape(raw) {
    return {
      slug: slug,
      title: raw.title || slug,
      tiers: raw.tiers || ['S', 'A', 'B', 'C', 'D', 'F'],
      items: (raw.items || []).map(function (it, i) {
        return {
          id: it.id || ('i' + i),
          name: it.name || '',
          sub: it.sub || it.artist || it.subtitle || '',
          img: it.img_url || null
        };
      })
    };
  }

  function getSaved() {
    if (imported || !slug) return Promise.resolve({});
    if (devMode) {
      try { return Promise.resolve(JSON.parse(localStorage.getItem('tiers:' + slug) || '{}')); }
      catch (_) { return Promise.resolve({}); }
    }
    return fetch('/api/save/' + encodeURIComponent(slug), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });
  }

  function putSaved(assign) {
    /* An imported list has no slug, so it has nowhere to be saved. That is
     * doc/imports.md, not an oversight: the service's bucket key is read-only
     * and an import stays in the browser. */
    if (imported || !slug) return Promise.resolve('ephemeral');
    var body = JSON.stringify({ assign: assign });
    if (devMode) {
      try { localStorage.setItem('tiers:' + slug, body); } catch (_) {}
      return Promise.resolve(true);
    }
    return fetch('/api/save/' + encodeURIComponent(slug), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: body
    }).then(function (r) { return r.ok; });
  }

  /* ── render ────────────────────────────────────────────────────────── */

  var TIER_BG = {
    S: '#7d2e2e', A: '#a2762a', B: '#7a584a',
    C: '#4f5d52', D: '#44485e', F: '#2b1a15'
  };

  function rowFor(tier) {
    var row = document.createElement('section');
    row.className = 'row';

    var head = document.createElement('div');
    head.className = 'row-head boil-text';
    head.textContent = tier;
    head.style.setProperty('--tier-bg', TIER_BG[tier] || 'var(--muted)');

    var drop = document.createElement('div');
    drop.className = 'drop';
    drop.dataset.tier = tier;

    row.appendChild(head);
    row.appendChild(drop);
    return row;
  }

  function cardFor(item) {
    var node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.id = item.id;
    node.querySelector('.name').textContent = item.name;
    node.querySelector('.sub').textContent = item.sub || '';
    node.title = item.sub ? item.name + ' — ' + item.sub : item.name;

    var img = node.querySelector('.thumb');
    if (item.img) {
      img.src = item.img;
      /* A key that resolves to nothing becomes a visible chip, not a broken
       * image icon. */
      img.addEventListener('error', function () { toChip(node, item); }, { once: true });
    } else {
      toChip(node, item);
    }
    if (boilCards) node.classList.add('boil-text', 'boil-fine');
    return node;
  }

  function toChip(node, item) {
    node.classList.add('no-img');
    node.querySelector('.chip').textContent = (item.name || '?').trim().charAt(0).toUpperCase();
  }

  function render(l, assign) {
    list = l;
    document.getElementById('title').textContent = l.title;
    document.title = l.title + ' · tiers';

    board.textContent = '';
    var zones = {};
    l.tiers.forEach(function (t) {
      var row = rowFor(t);
      board.appendChild(row);
      zones[t] = row.querySelector('.drop');
    });

    l.items.forEach(function (it) {
      var where = assign[it.id];
      (zones[where] || pool).appendChild(cardFor(it));
    });
    recount();
  }

  function recount() {
    poolCount.textContent = '(' + pool.children.length + ')';
  }

  function currentAssign() {
    var out = {};
    board.querySelectorAll('.drop').forEach(function (z) {
      var tier = z.dataset.tier;
      z.querySelectorAll('.card').forEach(function (c) { out[c.dataset.id] = tier; });
    });
    return out;
  }

  function scheduleSave() {
    savedEl.textContent = '...';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      putSaved(currentAssign()).then(function (ok) {
        savedEl.textContent = ok === 'ephemeral' ? 'not saved'
                            : ok ? (devMode ? 'local' : 'saved') : 'failed';
      });
    }, SAVE_WAIT);
  }

  /* ── the drop ──────────────────────────────────────────────────────── */

  function zones() {
    return Array.prototype.slice.call(document.querySelectorAll('.drop'));
  }

  /* Rectangles, not elementFromPoint: the dragged card is under the finger,
   * so hit testing by paint order finds the card and resolves to the row it
   * is leaving. */
  function zoneAt(x, y) {
    var zs = zones();
    for (var i = 0; i < zs.length; i++) {
      var r = zs[i].getBoundingClientRect();
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return zs[i];
    }
    return null;
  }

  function insertionPoint(zone, card, x, y) {
    var kids = Array.prototype.filter.call(zone.children, function (k) { return k !== card; });
    var best = null, bestD = Infinity, bestAfter = false;
    kids.forEach(function (k) {
      var r = k.getBoundingClientRect();
      var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      var d = Math.abs(cy - y) * 2 + Math.abs(cx - x);
      if (d < bestD) { bestD = d; best = k; bestAfter = x > cx; }
    });
    if (!best) return null;
    return bestAfter ? best.nextSibling : best;
  }

  var pending = null;
  var dragging = false;
  var lastZone = null;

  document.addEventListener('pointerdown', function (e) {
    var card = e.target.closest ? e.target.closest('.card.heft') : null;
    if (!card || e.button !== 0) return;
    pending = { card: card, sx: e.clientX, sy: e.clientY };
    dragging = false;
  }, true);

  window.addEventListener('pointermove', function (e) {
    if (!pending) return;
    var dx = e.clientX - pending.sx, dy = e.clientY - pending.sy;
    if (!dragging) {
      if (dx * dx + dy * dy < SLACK2) return;
      dragging = true;
    }
    var z = zoneAt(e.clientX, e.clientY);
    if (z !== lastZone) {
      if (lastZone) lastZone.classList.remove('over');
      if (z) z.classList.add('over');
      lastZone = z;
    }
    if (e.clientY < EDGE) window.scrollBy(0, -EDGE_STEP);
    else if (e.clientY > window.innerHeight - EDGE) window.scrollBy(0, EDGE_STEP);
  }, { passive: true });

  function finish(e) {
    if (!pending) return;
    var card = pending.card, wasDragging = dragging;
    pending = null; dragging = false;
    if (lastZone) { lastZone.classList.remove('over'); lastZone = null; }
    if (!wasDragging) return;

    var z = zoneAt(e.clientX, e.clientY);
    if (!z) return;                              /* heft's snap-back takes it home */

    var before = insertionPoint(z, card, e.clientX, e.clientY);
    if (z === card.parentNode && before === card.nextSibling) return;

    /* heft has already set translate to 0 and armed .settling. Clearing both
     * means the card appears in its new slot instead of springing toward it
     * from the delta of a drag that is over. */
    card.classList.remove('settling');
    card.style.translate = '0px 0px';

    z.insertBefore(card, before);
    recount();
    scheduleSave();
  }

  window.addEventListener('pointerup', finish);
  window.addEventListener('pointercancel', function () {
    pending = null; dragging = false;
    if (lastZone) { lastZone.classList.remove('over'); lastZone = null; }
  });

  document.getElementById('reset').addEventListener('click', function () {
    if (!list) return;
    board.querySelectorAll('.card').forEach(function (c) { pool.appendChild(c); });
    recount();
    scheduleSave();
  });

  /* ── the picker ────────────────────────────────────────────────────── */

  function loadPicker() {
    return fetch('/api/lists', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { lists: [] }; })
      .catch(function () { return { lists: [] }; })
      .then(function (d) {
        var ul = document.getElementById('pickerlist');
        ul.textContent = '';
        (d.lists || []).forEach(function (l) {
          var li = document.createElement('li');
          var a = document.createElement('a');
          a.href = '/l/' + encodeURIComponent(l.slug);
          if (l.slug === slug) a.setAttribute('aria-current', 'page');
          var t = document.createElement('span');
          t.textContent = l.title || l.slug;
          var m = document.createElement('span');
          m.className = 'meta';
          m.textContent = (l.items == null ? '' : l.items + ' cards');
          a.appendChild(t); a.appendChild(m); li.appendChild(a); ul.appendChild(li);
        });
        return (d.lists || []).length;
      });
  }

  var pickerEl = document.getElementById('picker');
  document.getElementById('lists').addEventListener('click', function () {
    var show = pickerEl.hidden;
    pickerEl.hidden = !show;
    this.setAttribute('aria-expanded', String(show));
    if (show) loadPicker();
  });

  /* ── import, which never leaves the browser ────────────────────────── */

  document.getElementById('importfile').addEventListener('change', function (e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;
    savedEl.textContent = 'parsing';
    file.text().then(function (text) {
      return fetch('/api/parse', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'text/plain; charset=utf-8', 'X-Filename': file.name },
        body: text
      });
    }).then(function (r) {
      if (r.status === 404) throw new Error('this service has no /api/parse yet');
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || ('parse ' + r.status)); });
      return r.json();
    }).then(function (l) {
      imported = true;
      slug = null;
      document.body.classList.add('imported');
      history.replaceState(null, '', location.pathname);
      render(l, {});
      savedEl.textContent = 'not saved';
    }).catch(function (err) {
      savedEl.textContent = 'failed';
      board.textContent = 'could not import ' + file.name + ': ' + err.message;
    });
    e.target.value = '';
  });

  /* ── start ─────────────────────────────────────────────────────────── */

  if (!slug) {
    /* No slug in the path: either / before its redirect resolves, or a direct
     * visit. Show the picker rather than guessing at a list. */
    pickerEl.hidden = false;
    document.getElementById('lists').setAttribute('aria-expanded', 'true');
    loadPicker().then(function (n) {
      if (!n) board.textContent = 'no lists found';
    });
  } else {
    getList().then(function (l) {
      return getSaved().then(function (s) { render(l, (s && s.assign) || {}); });
    }).then(function () {
      if (devMode) savedEl.textContent = 'fixture';
      loadPicker();
    }).catch(function (err) {
      board.textContent = 'could not load ' + slug + ': ' + err.message;
    });
  }

  window.__tiers = {
    assign: currentAssign,
    zoneAt: zoneAt,
    count: function () { return document.querySelectorAll('.card').length; }
  };
})();
