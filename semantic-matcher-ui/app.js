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
    if (query) doSearch(query);
  };

  analyzeBtn.addEventListener('click', runSearch);
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') runSearch();
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

  // Score tiers: ≥60% = high (green), 30-59% = medium (yellow), <30% = low (red)
  const scoreTierClass = (pct) => {
    if (pct >= 60) return 'score-high';
    if (pct >= 30) return 'score-medium';
    return 'score-low';
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
        : 'No SQL matches found for these keywords.';
      container.innerHTML = `<div class="result-card empty-state">${label}</div>`;
      return;
    }

    data.forEach((item, index) => {
      if (!item) {
        container.innerHTML += `<div class="result-card empty-state">No match for Rank #${index + 1}</div>`;
        return;
      }

      const pct = parseInt(item.score, 10);
      const tierClass = isNaN(pct) ? '' : scoreTierClass(pct);
      const tierLabel = isNaN(pct) ? item.score : `${pct}% — ${scoreTierLabel(pct)}`;

      const rawLabel = item.raw_score
        ? `<span class="raw-score">${type === 'vector' ? 'cosine ' : 'kw '}${item.raw_score}</span>`
        : '';

      container.innerHTML += `
        <div class="result-card">
          <div class="result-header">
            <span class="result-rank">Rank #${item.rank}</span>
            <div class="score-group">
              <span class="score-badge ${tierClass}">${tierLabel}</span>
              ${rawLabel}
            </div>
          </div>
          <div class="result-title">${item.title}</div>
          <p class="result-snippet">${item.text}</p>
        </div>`;
    });
  };

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
