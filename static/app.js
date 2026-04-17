/* MTG Purchase Optimizer — frontend app */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  step: 1,
  parsedCards: [],       // [{card_name, quantity, set_hint, original_text}]
  currentIndex: 0,       // which card we're reviewing
  // Per-card data loaded from API
  printingsCache: {},    // card_name -> [{printing, store_prices}]
  // User selections: card_name -> Set of scryfall_ids that are EXCLUDED
  excluded: {},
  // Final selections for optimization: [{card_name, quantity, accepted_printings}]
  finalSelections: [],
};

const SAMPLE_LIST = `4 Lightning Bolt
2 Counterspell
1 Sol Ring
3 Birds of Paradise
2 Wrath of God`;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const $ = id => document.getElementById(id);
const sections = {
  input:   $('step-input'),
  review:  $('step-review'),
  results: $('step-results'),
};

// ---------------------------------------------------------------------------
// Step navigation
// ---------------------------------------------------------------------------
function goToStep(n) {
  state.step = n;
  Object.values(sections).forEach(s => s.classList.add('hidden'));
  const names = ['input', 'review', 'results'];
  sections[names[n - 1]].classList.remove('hidden');

  for (let i = 1; i <= 3; i++) {
    const dot = $(`dot-${i}`);
    dot.classList.toggle('active', i === n);
    dot.classList.toggle('done', i < n);
  }
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function toast(msg, type = '') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ---------------------------------------------------------------------------
// Step 1: parse card list
// ---------------------------------------------------------------------------
$('btn-sample').addEventListener('click', () => {
  $('card-list-input').value = SAMPLE_LIST;
});

$('btn-parse').addEventListener('click', async () => {
  const text = $('card-list-input').value.trim();
  if (!text) { toast('Paste a card list first.', 'error'); return; }

  const btn = $('btn-parse');
  btn.disabled = true;
  btn.textContent = 'Parsing…';

  try {
    const res = await api('/api/parse-list', 'POST', { text });
    if (!res.cards.length) { toast('No cards found — check your formatting.', 'error'); return; }
    state.parsedCards = res.cards;
    state.currentIndex = 0;
    state.excluded = {};
    state.finalSelections = [];
    state.printingsCache = {};
    goToStep(2);
    loadCurrentCard();
  } catch (e) {
    toast('Failed to parse list: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Analyze Cards →';
  }
});

// ---------------------------------------------------------------------------
// Step 2: card-by-card review
// ---------------------------------------------------------------------------
function updateProgress() {
  const total = state.parsedCards.length;
  const idx   = state.currentIndex;
  const pct   = total ? Math.round((idx / total) * 100) : 0;
  $('progress-text').textContent = `Card ${idx + 1} of ${total}`;
  $('progress-pct').textContent  = `${pct}%`;
  $('progress-fill').style.width = `${pct}%`;
  $('btn-prev').disabled = idx === 0;
}

async function loadCurrentCard() {
  const card = state.parsedCards[state.currentIndex];
  if (!card) return;

  updateProgress();

  $('card-name-display').textContent = card.card_name;
  $('card-qty-display').textContent  = `Need: ${card.quantity}`;

  $('printings-tbody').innerHTML = '<tr><td colspan="9" style="text-align:center;padding:24px;color:var(--text2)"><div class="loading-spinner"></div> Loading printings…</td></tr>';
  $('printing-count').textContent = '…';

  let printings;
  try {
    const data = await api(`/api/card/printings?name=${encodeURIComponent(card.card_name)}`);
    printings = data.printings;
  } catch (e) {
    $('printings-tbody').innerHTML = `<tr><td colspan="8" class="error-text" style="padding:16px">Failed to load printings: ${e.message}</td></tr>`;
    return;
  }

  if (!printings.length) {
    $('printings-tbody').innerHTML = `<tr><td colspan="8" style="padding:16px;color:var(--text2)">No printings found.</td></tr>`;
    return;
  }

  $('printing-count').textContent = `${printings.length} printing${printings.length !== 1 ? 's' : ''}`;

  // Store in cache with empty store prices; we'll fill them lazily
  state.printingsCache[card.card_name] = printings.map(p => ({
    printing: p,
    store_prices: null, // null = not yet fetched
  }));

  if (!state.excluded[card.card_name]) state.excluded[card.card_name] = new Set();

  renderPrintingsTable(card.card_name);

  // Kick off price fetching for all printings (in small batches to be polite)
  fetchAllPrices(card.card_name);
}

function renderPrintingsTable(cardName) {
  const rows = state.printingsCache[cardName] || [];
  const excluded = state.excluded[cardName] || new Set();
  const tbody = $('printings-tbody');

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="padding:16px;color:var(--text2)">No printings found.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map((row, i) => {
    const p = row.printing;
    const isExcluded = excluded.has(p.scryfall_id);
    const year = p.released_at ? p.released_at.slice(0, 4) : '—';
    const rarityClass = { common: 'c', uncommon: 'u', rare: 'r', mythic: 'm' }[p.rarity] || 'c';
    const foilBadge = p.foil ? '<span class="foil-badge">FOIL</span>' : '';

    const thumbCell = p.image_uri
      ? `<td class="card-thumb-cell">
           <img class="card-thumb" src="${escHtml(p.image_uri)}" alt="${escHtml(p.set_name)}" loading="lazy">
           <img class="card-thumb-hover" src="${escHtml(p.image_uri)}" alt="" loading="lazy">
         </td>`
      : '<td></td>';

    const ckCell   = priceCell(row.store_prices, 'card_kingdom');
    const scgCell  = priceCell(row.store_prices, 'star_city_games');
    const cfbCell  = priceCell(row.store_prices, 'channel_fireball');
    const tcgCell  = p.tcg_price != null ? `<span class="price-cell">$${p.tcg_price.toFixed(2)}</span>` : '<span class="price-cell unavail">—</span>';

    return `
      <tr class="${isExcluded ? 'excluded' : ''}" data-idx="${i}" data-id="${p.scryfall_id}">
        <td>
          <input type="checkbox" class="printing-check"
            data-card="${escHtml(cardName)}" data-id="${p.scryfall_id}"
            ${isExcluded ? '' : 'checked'} title="Include this printing" />
        </td>
        ${thumbCell}
        <td>
          <span class="rarity-badge rarity-${rarityClass}" title="${p.rarity}"></span>
          ${escHtml(p.set_name)}${foilBadge}
        </td>
        <td>${year}</td>
        <td>${p.foil ? '✦' : ''}</td>
        <td>${ckCell}</td>
        <td>${scgCell}</td>
        <td>${cfbCell}</td>
        <td>${tcgCell}</td>
      </tr>`;
  }).join('');

  // Attach checkbox listeners
  tbody.querySelectorAll('.printing-check').forEach(cb => {
    cb.addEventListener('change', e => {
      const { card, id } = e.target.dataset;
      const excl = state.excluded[card] || (state.excluded[card] = new Set());
      if (e.target.checked) excl.delete(id);
      else                   excl.add(id);
      const row = e.target.closest('tr');
      row.classList.toggle('excluded', !e.target.checked);
    });
  });
}

function priceCell(storePrices, storeId) {
  if (storePrices === null) {
    return '<span class="loading-spinner"></span>';
  }
  const sp = (storePrices || []).find(s => s.store_id === storeId);
  if (!sp) return '<span class="price-cell unavail">—</span>';
  if (sp.error && !sp.price) {
    const linkText = sp.url ? `<a class="store-link" href="${escHtml(sp.url)}" target="_blank" rel="noopener">Search ↗</a>` : '';
    return `<span class="price-cell unavail">—${linkText}</span>`;
  }
  if (sp.price == null) return '<span class="price-cell unavail">—</span>';
  const qty = sp.quantity != null ? `<span class="qty-cell">(${sp.quantity})</span>` : '';
  const link = sp.url ? `<a class="store-link" href="${escHtml(sp.url)}" target="_blank" rel="noopener">↗</a>` : '';
  return `<span class="price-cell">$${sp.price.toFixed(2)}</span> ${qty}${link}`;
}

async function fetchAllPrices(cardName) {
  const rows = state.printingsCache[cardName];
  if (!rows) return;

  const CONCURRENCY = 3;
  for (let i = 0; i < rows.length; i += CONCURRENCY) {
    const batch = rows.slice(i, i + CONCURRENCY);
    await Promise.all(batch.map(async row => {
      const p = row.printing;
      try {
        const data = await api('/api/prices', 'POST', {
          card_name: p.card_name,
          set_code: p.set_code,
          set_name: p.set_name,
          collector_number: p.collector_number,
          foil: p.foil,
        });
        row.store_prices = [
          { ...data.card_kingdom,     store_id: 'card_kingdom',     store_name: 'Card Kingdom' },
          { ...data.star_city_games,  store_id: 'star_city_games',  store_name: 'Star City Games' },
          { ...data.channel_fireball, store_id: 'channel_fireball', store_name: 'Channel Fireball' },
        ];
      } catch {
        row.store_prices = [];
      }
    }));

    // Re-render after each batch so cells update incrementally
    if (state.step === 2 && state.parsedCards[state.currentIndex]?.card_name === cardName) {
      renderPrintingsTable(cardName);
    }
  }

  // After all prices loaded: sort by cheapest price, then highlight
  if (state.step === 2 && state.parsedCards[state.currentIndex]?.card_name === cardName) {
    const rows = state.printingsCache[cardName];
    if (rows) rows.sort((a, b) => cheapestRowPrice(a) - cheapestRowPrice(b));
    renderPrintingsTable(cardName);
    highlightBestPrices(cardName);
  }
}

function cheapestRowPrice(row) {
  if (!row.store_prices) return Infinity;
  const prices = row.store_prices.filter(sp => sp.price != null).map(sp => sp.price);
  return prices.length ? Math.min(...prices) : Infinity;
}

function highlightBestPrices(cardName) {
  const rows = state.printingsCache[cardName] || [];
  const stores = ['card_kingdom', 'star_city_games', 'channel_fireball'];

  stores.forEach(storeId => {
    let best = Infinity;
    rows.forEach(row => {
      const sp = (row.store_prices || []).find(s => s.store_id === storeId);
      if (sp?.price != null && sp.price < best) best = sp.price;
    });
    if (best === Infinity) return;

    // Apply to table cells (columns 4,5,6 = indexes 4,5,6)
    const colIdx = { card_kingdom: 5, star_city_games: 6, channel_fireball: 7 }[storeId];
    const trs = $('printings-tbody').querySelectorAll('tr');
    trs.forEach((tr, rowIdx) => {
      const row = rows[rowIdx];
      if (!row) return;
      const sp = (row.store_prices || []).find(s => s.store_id === storeId);
      if (sp?.price === best) {
        const td = tr.querySelectorAll('td')[colIdx];
        if (td) td.querySelector('.price-cell')?.classList.add('best');
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Review navigation buttons
// ---------------------------------------------------------------------------
$('btn-next').addEventListener('click', () => {
  const card = state.parsedCards[state.currentIndex];
  const rows = card ? (state.printingsCache[card.card_name] || []) : [];
  const stillLoading = rows.some(r => r.store_prices === null);
  if (stillLoading) {
    toast('Some prices are still loading — included printings with no price yet won\'t appear in the cart.', '');
  }
  acceptCurrentCard();
  advanceCard(1);
});

$('btn-skip').addEventListener('click', () => {
  advanceCard(1);
});

$('btn-prev').addEventListener('click', () => {
  if (state.currentIndex > 0) {
    state.currentIndex--;
    loadCurrentCard();
  }
});

$('btn-back-input').addEventListener('click', () => goToStep(1));

function acceptCurrentCard() {
  const card = state.parsedCards[state.currentIndex];
  if (!card) return;

  const rows = state.printingsCache[card.card_name] || [];
  const excluded = state.excluded[card.card_name] || new Set();

  const acceptedPrintings = rows
    .filter(row => !excluded.has(row.printing.scryfall_id))
    .map(row => ({
      printing: row.printing,
      store_prices: (row.store_prices || []).map(sp => ({
        store_id:   sp.store_id,
        store_name: sp.store_name,
        price:      sp.price ?? null,
        quantity:   sp.quantity ?? null,
        url:        sp.url ?? null,
        condition:  sp.condition ?? null,
      })),
    }));

  // Replace or push
  const existing = state.finalSelections.findIndex(s => s.card_name === card.card_name);
  const entry = { card_name: card.card_name, quantity: card.quantity, accepted_printings: acceptedPrintings };
  if (existing >= 0) state.finalSelections[existing] = entry;
  else state.finalSelections.push(entry);
}

function advanceCard(delta) {
  state.currentIndex += delta;
  if (state.currentIndex >= state.parsedCards.length) {
    // All cards reviewed — optimize and show results
    runOptimization();
    return;
  }
  loadCurrentCard();
}

// ---------------------------------------------------------------------------
// Step 3: optimization & results
// ---------------------------------------------------------------------------
async function runOptimization() {
  // Make sure last card is accepted if user didn't explicitly click Next
  acceptCurrentCard();

  goToStep(3);

  const btn = document.createElement('div');
  btn.style.cssText = 'text-align:center;padding:40px;color:var(--text2)';
  btn.innerHTML = '<div class="loading-spinner"></div> Optimising cart…';
  $('carts-container').innerHTML = '';
  $('missing-container').innerHTML = '';
  $('results-summary').innerHTML = '';
  $('carts-container').appendChild(btn);

  try {
    const result = await api('/api/optimize', 'POST', { cards: state.finalSelections });
    renderResults(result);
  } catch (e) {
    $('carts-container').innerHTML = `<div class="error-text" style="padding:20px">Optimization failed: ${e.message}</div>`;
  }
}

function renderResults(result) {
  const { carts, cart_totals, store_names, missing_cards } = result;

  // Summary cards
  const summaryEl = $('results-summary');
  summaryEl.innerHTML = Object.entries(store_names).map(([id, name]) => {
    const total = cart_totals[id] || 0;
    const count = (carts[id] || []).length;
    const totalHtml = total > 0
      ? `<div class="total">$${total.toFixed(2)}</div><div class="item-count">${count} line item${count !== 1 ? 's' : ''}</div>`
      : `<div class="empty-total">No items</div>`;
    return `
      <div class="summary-card">
        <div class="store-name">${escHtml(name)}</div>
        ${totalHtml}
      </div>`;
  }).join('');

  // Per-store carts
  const cartsEl = $('carts-container');
  cartsEl.innerHTML = '';

  Object.entries(store_names).forEach(([storeId, storeName]) => {
    const items = carts[storeId] || [];
    if (!items.length) return;

    const total = cart_totals[storeId] || 0;
    const section = document.createElement('div');
    section.className = 'cart-section';
    section.innerHTML = `
      <div class="cart-section-header">
        <h3>${escHtml(storeName)}</h3>
        <span class="store-total">Total: $${total.toFixed(2)}</span>
      </div>
      <div class="cart-table">
        <table>
          <thead>
            <tr>
              <th>Card</th>
              <th>Printing</th>
              <th>Foil</th>
              <th>Qty</th>
              <th>Price each</th>
              <th>Line total</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            ${items.map(item => `
              <tr>
                <td>${escHtml(item.card_name)}</td>
                <td>${escHtml(item.set_name)} <span class="tag">${item.set_code}</span></td>
                <td>${item.foil ? '<span class="foil-badge">FOIL</span>' : ''}</td>
                <td>${item.quantity}</td>
                <td>$${item.price_each.toFixed(2)}</td>
                <td><strong>$${item.total_price.toFixed(2)}</strong></td>
                <td>${item.url ? `<a href="${escHtml(item.url)}" target="_blank" rel="noopener">Shop ↗</a>` : '—'}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    cartsEl.appendChild(section);
  });

  // Missing cards
  if (missing_cards.length) {
    $('missing-container').innerHTML = `
      <div class="missing-section">
        <h3>Cards not found at any accepted price (${missing_cards.length})</h3>
        <ul>${missing_cards.map(c => `<li>${escHtml(c)}</li>`).join('')}</ul>
      </div>`;
  } else {
    $('missing-container').innerHTML = '';
  }
}

$('btn-back-review').addEventListener('click', () => {
  goToStep(2);
  loadCurrentCard();
});

$('btn-start-over').addEventListener('click', () => {
  Object.assign(state, {
    step: 1, parsedCards: [], currentIndex: 0,
    printingsCache: {}, excluded: {}, finalSelections: [],
  });
  goToStep(1);
});

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------
async function api(path, method = 'GET', body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
