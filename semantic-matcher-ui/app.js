// When served from FastAPI (http://localhost:8001), use relative URLs.
// When opened as file://, fall back to absolute URL so CORS still works
// (backend has allow_origins=["*"]).
// Best practice: always open via http://localhost:8001 (served by FastAPI).
const API_BASE = window.location.protocol === 'file:'
  ? 'http://127.0.0.1:8001'
  : '';

document.addEventListener('DOMContentLoaded', () => {
  const topNRange = document.getElementById('topNRange');
  const topNValue = document.getElementById('topNValue');
  topNRange.addEventListener('input', (e) => {
    topNValue.textContent = e.target.value;
  });

  // Tab routing
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      tabContents.forEach(c => c.classList.add('hidden'));
      btn.classList.add('active');
      document.getElementById(btn.getAttribute('data-tab') + '-tab').classList.remove('hidden');
    });
  });

  // ── Status / health check on load ─────────────────────────────────────────
  loadStatus();

  async function loadStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/status`);
      if (!res.ok) return;
      const data = await res.json();

      // Sidebar
      const cvCountEl = document.getElementById('status-cv-count');
      const milvusEl  = document.getElementById('status-milvus');
      if (cvCountEl) cvCountEl.textContent = data.cv_count.toLocaleString();
      if (milvusEl)  milvusEl.textContent  = data.milvus_connected ? 'Milvus ✓' : 'Milvus ✗';

      // Dashboard
      const dashCvEl    = document.getElementById('dash-cv-count');
      const dashModelEl = document.getElementById('dash-model');
      const dashDimEl   = document.getElementById('dash-dim');
      if (dashCvEl)    dashCvEl.textContent    = data.cv_count.toLocaleString();
      if (dashModelEl) dashModelEl.textContent = 'MiniLM-L12-v2';
      if (dashDimEl)   dashDimEl.textContent   = data.vector_dim;

      // Vector search badge
      const vecBadge = document.querySelector('.col-vector .strategy-badge');
      if (vecBadge && !data.milvus_connected) {
        vecBadge.textContent = 'Milvus offline';
        vecBadge.style.color = 'var(--sql-logic)';
      }
      
      // Fetch Dashboard Stats
      try {
        const statsRes = await fetch(`${API_BASE}/api/stats`);
        if (statsRes.ok) {
          const statsData = await statsRes.json();
          const topPosEl = document.getElementById('dash-top-positions');
          if (topPosEl) {
            topPosEl.innerHTML = statsData.top_positions.map(p => `
              <div class="dash-list-item">
                <span class="label">${p.position || 'Unknown'}</span>
                <span class="value">${p.count} CVs</span>
              </div>
            `).join('');
          }
          const expEl = document.getElementById('dash-experience');
          if (expEl) {
            expEl.innerHTML = Object.entries(statsData.experience).map(([k, v]) => `
              <div class="dash-list-item">
                <span class="label">${k}</span>
                <span class="value">${v} CVs</span>
              </div>
            `).join('');
          }
        }
      } catch (e) {
        console.error("Stats fetch failed", e);
      }
      
    } catch (_) {
      // Backend not yet reachable — silently skip, user will see API error on search
    }
  }

  // ── Search ────────────────────────────────────────────────────────────────
  const analyzeBtn  = document.getElementById('analyzeBtn');
  const searchInput = document.getElementById('searchInput');
  const errorBanner = document.getElementById('errorBanner');

  const runSearch = () => {
    const query = searchInput.value.trim();
    document.getElementById('searchSuggest')?.classList.add('hidden');
    if (query) doSearch(query);
  };

  analyzeBtn.addEventListener('click', runSearch);
  
  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      searchInput.value = '';
      searchInput.focus();
      renderResults('sql-results', [], 'sql');
      renderResults('vector-results', [], 'vector');
      const chipsEl = document.getElementById('keywordChips');
      if (chipsEl) chipsEl.innerHTML = '<span class="chip chip-sql" style="opacity:0.4; font-style:italic">keywords appear after search...</span>';
      document.getElementById('m-sql-count').textContent = '—';
      document.getElementById('m-vec-count').textContent = '—';
      document.getElementById('m-sql-time').innerHTML = '—';
      document.getElementById('m-vec-time').innerHTML = '—';
      
      const sqlBadge = document.querySelector('.col-sql .strategy-badge');
      if (sqlBadge) sqlBadge.textContent = 'Exact Match';
      const vecBadge = document.querySelector('.col-vector .strategy-badge');
      if (vecBadge) vecBadge.textContent = 'Dense Vector';
      
      clearError();
    });
  }
  
  // ── Auto-suggest ──────────────────────────────────────────────────────────
  const searchSuggest = document.getElementById('searchSuggest');
  let suggestTimeout;
  let inactivityTimeout;
  let currentSuggestIndex = -1;
  let originalQuery = '';

  searchInput.addEventListener('input', (e) => {
    const q = e.target.value;
    originalQuery = q;
    clearTimeout(suggestTimeout);
    clearTimeout(inactivityTimeout);
    
    if (!q.trim()) {
      searchSuggest.classList.add('hidden');
      return;
    }
    
    suggestTimeout = setTimeout(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/suggest?q=${encodeURIComponent(q)}`);
        if (res.ok) {
          if (searchInput.value.trim() !== q.trim()) return; // Fix race condition
          const data = await res.json();
          if (data.suggestions.length > 0) {
            currentSuggestIndex = -1;
            searchSuggest.innerHTML = data.suggestions.map(s => `<li>${s}</li>`).join('');
            searchSuggest.classList.remove('hidden');
            
            searchSuggest.querySelectorAll('li').forEach(li => {
              li.addEventListener('click', () => {
                searchInput.value = li.textContent;
                searchSuggest.classList.add('hidden');
                runSearch();
              });
            });
            
            inactivityTimeout = setTimeout(() => {
              searchSuggest.classList.add('hidden');
            }, 10000);
          } else {
            searchSuggest.classList.add('hidden');
          }
        }
      } catch (err) {}
    }, 300);
  });

  searchInput.addEventListener('keydown', (e) => {
    const isHidden = searchSuggest.classList.contains('hidden');
    const items = searchSuggest.querySelectorAll('li');

    if (e.key === 'ArrowDown' && !isHidden) {
      e.preventDefault();
      if (items.length > 0) {
        if (currentSuggestIndex >= 0) items[currentSuggestIndex].classList.remove('active');
        currentSuggestIndex = (currentSuggestIndex + 1) % items.length;
        items[currentSuggestIndex].classList.add('active');
        searchInput.value = items[currentSuggestIndex].textContent;
        items[currentSuggestIndex].scrollIntoView({ block: 'nearest' });
      }
    } else if (e.key === 'ArrowUp' && !isHidden) {
      e.preventDefault();
      if (items.length > 0) {
        if (currentSuggestIndex >= 0) items[currentSuggestIndex].classList.remove('active');
        if (currentSuggestIndex <= 0) {
          currentSuggestIndex = -1;
          searchInput.value = originalQuery;
        } else {
          currentSuggestIndex--;
          items[currentSuggestIndex].classList.add('active');
          searchInput.value = items[currentSuggestIndex].textContent;
          items[currentSuggestIndex].scrollIntoView({ block: 'nearest' });
        }
      }
    } else if (e.key === 'Enter') {
      searchSuggest.classList.add('hidden');
      runSearch();
    } else if (e.key === 'Tab' && !isHidden) {
      const activeItem = currentSuggestIndex >= 0 ? items[currentSuggestIndex] : items[0];
      if (activeItem) {
        e.preventDefault();
        searchInput.value = activeItem.textContent;
        searchSuggest.classList.add('hidden');
      }
    } else if (e.key === 'Escape') {
      searchSuggest.classList.add('hidden');
      searchInput.value = originalQuery;
    }
  });

  function showError(msg) {
    if (!errorBanner) return;
    errorBanner.textContent = msg;
    errorBanner.style.display = 'block';
  }
  function clearError() {
    if (!errorBanner) return;
    errorBanner.style.display = 'none';
    errorBanner.textContent = '';
  }

  async function doSearch(query) {
    clearError();
    analyzeBtn.innerHTML = '<i class="ph ph-spinner ph-spin"></i> Analyzing...';
    analyzeBtn.disabled = true;

    try {
      const limit = topNRange.value;
      const url = `${API_BASE}/api/search?query=${encodeURIComponent(query)}&limit=${limit}`;
      const res = await fetch(url);

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`Server error ${res.status}: ${errText.slice(0, 200)}`);
      }

      const data = await res.json();

      // Keywords
      const chipsEl = document.getElementById('keywordChips');
      chipsEl.innerHTML = '';
      if (data.keywords.length === 0) {
        chipsEl.innerHTML = '<span class="chip chip-sql" style="opacity:0.4;font-style:italic">no keywords extracted</span>';
      } else {
        data.keywords.forEach(kw => {
          chipsEl.innerHTML += `<span class="chip chip-sql"><i class="ph ph-database"></i> ${kw}</span>`;
        });
      }

      // Metrics via IDs
      document.getElementById('m-sql-count').textContent = data.sql_results.length;
      document.getElementById('m-vec-count').textContent = data.vector_results.length;
      document.getElementById('m-sql-time').innerHTML = `${data.sql_time_ms.toFixed(1)} <span class="metric-unit">ms</span>`;
      document.getElementById('m-vec-time').innerHTML = `${data.vector_time_ms.toFixed(1)} <span class="metric-unit">ms</span>`;

      // Strategy badge
      const sqlBadge = document.querySelector('.col-sql .strategy-badge');
      if (sqlBadge) sqlBadge.textContent = `${data.sql_strategy} Logic`;

      // Vector badge — show offline warning if no results
      const vecBadge = document.querySelector('.col-vector .strategy-badge');
      if (vecBadge) {
        if (data.vector_results.length === 0) {
          vecBadge.textContent = 'Milvus offline or no results';
          vecBadge.style.color = 'var(--sql-logic)';
        } else {
          vecBadge.textContent = 'Milvus HNSW';
          vecBadge.style.color = '';
        }
      }

      renderResults('sql-results', data.sql_results, 'sql');
      renderResults('vector-results', data.vector_results, 'vector');

    } catch (err) {
      const isFileProtocol = window.location.protocol === 'file:';
      const hint = isFileProtocol
        ? ' Tip: open via http://localhost:8001 (served by FastAPI) instead of opening the HTML file directly.'
        : ' Make sure FastAPI is running: cd backend && uvicorn main:app --port 8001 --reload';
      showError(`Connection failed — ${err.message}.${hint}`);
    } finally {
      analyzeBtn.innerHTML = '<i class="ph ph-sparkle"></i> Analyze';
      analyzeBtn.disabled = false;
    }
  }

  // ── Render helpers ────────────────────────────────────────────────────────

  // Smooth color transition based on percentage
  const getScoreColor = (pct) => {
    // 0% -> Hue 0 (Red)
    // 50% -> Hue 60 (Yellow)
    // 100% -> Hue 120 (Green)
    const hue = Math.max(0, Math.min(120, pct * 1.2));
    return `hsl(${hue}, 80%, 40%)`;
  };
  const getScoreBg = (pct) => {
    const hue = Math.max(0, Math.min(120, pct * 1.2));
    return `hsl(${hue}, 80%, 90%)`;
  };

  const scoreTierLabel = (pct) => {
    if (pct >= 60) return 'Strong Match';
    if (pct >= 30) return 'Partial Match';
    return 'Weak Match';
  };

  const renderResults = (containerId, data, type) => {
    const container = document.getElementById(containerId);
    container.innerHTML = '';

    if (data.length === 0) {
      const label = type === 'vector'
        ? 'No vector results — check Milvus is running and collection is loaded.'
        : 'No PostgreSQL matches found for these keywords.';
      container.innerHTML = `<div class="result-card empty-state">${label}</div>`;
      return;
    }

    data.forEach((item, index) => {
      if (!item) {
        container.innerHTML += `<div class="result-card empty-state">No match for Rank #${index + 1}</div>`;
        return;
      }

      const pct = parseInt(item.score, 10);
      const isNum = !isNaN(pct);
      const tierLabel = isNum ? `${pct}% — ${scoreTierLabel(pct)}` : item.score;
      const colorStyle = isNum ? `background-color: ${getScoreBg(pct)}; color: ${getScoreColor(pct)}; box-shadow: inset 0 0 0 2px ${getScoreColor(pct)};` : '';

      const rawLabel = item.raw_score
        ? `<span class="raw-score">${type === 'vector' ? '' : 'kw '}${item.raw_score}</span>`
        : '';

      const card = document.createElement('div');
      card.className = 'result-card';
      card.innerHTML = `
          <div class="result-header">
            <span class="result-rank">Rank #${item.rank}</span>
            <div class="score-group">
              <span class="score-badge" style="${colorStyle}">${tierLabel}</span>
              ${rawLabel}
            </div>
          </div>
          <div class="result-title">${item.title}</div>
          <p class="result-snippet">${item.text}</p>
      `;
      
      card.addEventListener('click', () => openModal(item, pct, tierLabel, colorStyle, type));
      container.appendChild(card);
    });
  };

  // ── Modal Logic ──────────────────────────────────────────────────────────
  const cvModal = document.getElementById('cvModal');
  const closeModalBtn = document.getElementById('closeModalBtn');
  
  if (closeModalBtn) {
    closeModalBtn.addEventListener('click', () => cvModal.classList.add('hidden'));
    cvModal.addEventListener('click', (e) => {
      if (e.target === cvModal) cvModal.classList.add('hidden');
    });
  }

  function openModal(item, pct, tierLabel, colorStyle, type) {
    document.getElementById('modalTitle').textContent = item.title || 'Unknown Position';
    
    const scoreBadge = document.getElementById('modalScore');
    scoreBadge.textContent = tierLabel;
    scoreBadge.style = colorStyle;
    
    const rawBadge = document.getElementById('modalRawScore');
    if (item.raw_score) {
      rawBadge.textContent = (type === 'vector' ? '' : 'kw ') + item.raw_score;
    } else {
      rawBadge.textContent = '';
    }
    
    document.getElementById('modalExp').textContent = `Exp: ${item.exp_years || 'Not specified'} years`;
    document.getElementById('modalHighlights').textContent = item.highlights || 'No highlights available.';
    document.getElementById('modalFullText').textContent = item.full_text || item.text;
    
    const kwsEl = document.getElementById('modalKws');
    kwsEl.innerHTML = '';
    if (item.kws) {
      item.kws.split(',').forEach(k => {
        k = k.trim();
        if (k) kwsEl.innerHTML += `<span class="chip chip-sql">${k}</span>`;
      });
    } else {
      kwsEl.innerHTML = '<span class="chip" style="opacity:0.5">No keywords</span>';
    }
    
    cvModal.classList.remove('hidden');
  }

  // Clear results on load
  renderResults('sql-results', [], 'sql');
  renderResults('vector-results', [], 'vector');

  // ── CV Management — sample data (no /api/cvs endpoint yet) ───────────────
  const cvData = [
    { id: 'CAND-001', pos: 'Data Scientist',    kws: 'Python, ML, PyTorch',  exp: '3', score: '—' },
    { id: 'CAND-002', pos: 'Backend Developer', kws: 'Java, Spring Boot',    exp: '5', score: '—' },
    { id: 'CAND-003', pos: 'Frontend Developer', kws: 'React, Vue, TS',      exp: '2', score: '—' },
    { id: 'CAND-004', pos: 'DevOps Engineer',   kws: 'Docker, K8s, AWS',    exp: '6', score: '—' },
  ];

  const renderTable = (tbodyId, data, columns) => {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    tbody.innerHTML = '';
    data.forEach(row => {
      const tr = document.createElement('tr');
      columns.forEach(col => {
        const td = document.createElement('td');
        td.innerHTML = col === 'score' ? `<span class="score-badge">${row[col]}</span>` : row[col];
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  };

  renderTable('cv-tbody', cvData, ['id', 'pos', 'kws', 'exp', 'score']);
});
