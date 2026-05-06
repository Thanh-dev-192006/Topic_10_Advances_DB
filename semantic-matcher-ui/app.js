// When served from FastAPI (http://localhost:8001), use relative URLs.
// When opened as file://, fall back to absolute URL so CORS still works
// (backend has allow_origins=["*"]).
// Best practice: always open via http://localhost:8001 (served by FastAPI).
const API_BASE = window.location.protocol === 'file:'
  ? 'http://127.0.0.1:8001'
  : '';

// ── Session-level analytics state ────────────────────────────────────────────
const sessionStats = {
  searchCount: 0,
  sqlTimes: [],
  vectorTimes: [],
  strategyHistory: { AND: 0, PARTIAL: 0, OR: 0 },
  sessionKeywords: {},
  totalSql: 0,
  totalVec: 0,
  scoreBuckets: {
    sql: { strong: 0, partial: 0, weak: 0 },
    vec: { strong: 0, partial: 0, weak: 0 }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  const controls = [
    { rangeId: 'topNRange', valueId: 'topNValue' },
    { rangeId: 'minScoreRange', valueId: 'minScoreValue' },
    { rangeId: 'vectorThresholdRange', valueId: 'vectorThresholdValue' },
  ];

  controls.forEach(({ rangeId, valueId }) => {
    const range = document.getElementById(rangeId);
    const label = document.getElementById(valueId);
    if (!range || !label) return;

    const syncLabel = () => {
      label.textContent = range.value;
    };

    range.addEventListener('input', syncLabel);
    range.addEventListener('change', syncLabel);
    syncLabel();
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
      const milvusEl = document.getElementById('status-milvus');
      if (cvCountEl) cvCountEl.textContent = data.cv_count.toLocaleString();
      if (milvusEl) milvusEl.textContent = data.milvus_connected ? 'Milvus ✓' : 'Milvus ✗';

      // Dashboard
      const dashCvEl = document.getElementById('dash-cv-count');
      const dashJdEl = document.getElementById('dash-jd-count');
      const dashRatioEl = document.getElementById('dash-ratio');
      const dashModelEl = document.getElementById('dash-model');
      const dashDimEl = document.getElementById('dash-dim');
      if (dashCvEl) dashCvEl.textContent = data.cv_count.toLocaleString();
      if (dashJdEl) dashJdEl.textContent = data.jd_count.toLocaleString();
      if (dashRatioEl) {
        const ratio = data.jd_count > 0 ? (data.cv_count / data.jd_count).toFixed(1) : 0;
        dashRatioEl.textContent = `${ratio} CVs/JD`;
      }
      if (dashModelEl) dashModelEl.textContent = 'MiniLM-L12-v2';
      if (dashDimEl) dashDimEl.textContent = data.vector_dim;

      // Milvus dashboard card
      const dashMilvusEl = document.getElementById('dash-milvus-status');
      if (dashMilvusEl) {
        dashMilvusEl.textContent = data.milvus_connected ? 'Online ✓' : 'Offline ✗';
        dashMilvusEl.style.color = data.milvus_connected ? 'var(--vector-logic)' : 'var(--sql-logic)';
        dashMilvusEl.style.fontWeight = '700';
      }

      // Vector search badge (Search tab)
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
          if (topPosEl && statsData.top_positions) {
            const maxPos = Math.max(...statsData.top_positions.map(p => p.count), 1);
            topPosEl.innerHTML = statsData.top_positions.map(p => `
              <div class="dash-list-item">
                <div class="dash-list-content">
                  <span class="label">${p.position || 'Unknown'}</span>
                  <span class="value">${p.count} CVs</span>
                </div>
                <div class="progress-track">
                  <div class="progress-fill" style="width: ${(p.count / maxPos) * 100}%"></div>
                </div>
              </div>
            `).join('');
          }
          
          const topSkillsEl = document.getElementById('dash-top-skills');
          if (topSkillsEl && statsData.top_skills) {
            const maxSkill = Math.max(...statsData.top_skills.map(s => s.count), 1);
            topSkillsEl.innerHTML = statsData.top_skills.map(s => `
              <div class="dash-list-item">
                <div class="dash-list-content">
                  <span class="label">${s.skill || 'Unknown'}</span>
                  <span class="value">${s.count} CVs</span>
                </div>
                <div class="progress-track">
                  <div class="progress-fill" style="width: ${(s.count / maxSkill) * 100}%"></div>
                </div>
              </div>
            `).join('');
          }

          const expEl = document.getElementById('dash-experience');
          if (expEl && statsData.experience) {
            const expValues = Object.values(statsData.experience);
            const maxExp = Math.max(...expValues, 1);
            expEl.innerHTML = Object.entries(statsData.experience).map(([k, v]) => `
              <div class="dash-list-item">
                <div class="dash-list-content">
                  <span class="label">${k}</span>
                  <span class="value">${v} CVs</span>
                </div>
                <div class="progress-track">
                  <div class="progress-fill" style="width: ${(v / maxExp) * 100}%"></div>
                </div>
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
  const analyzeBtn = document.getElementById('analyzeBtn');
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
      renderResults('sql-results', [], 'sql', '');
      renderResults('vector-results', [], 'vector', '');
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
      } catch (err) { }
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
      const minScore = minScoreRange.value;
      const vectorThreshold = vectorThresholdRange.value;
      const url = `${API_BASE}/api/search?query=${encodeURIComponent(query)}&limit=${limit}` +
        `&min_score=${minScore}&vector_threshold=${vectorThreshold}`;
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

      renderResults('sql-results', data.sql_results, 'sql', data.sql_filtered_reason);
      renderResults('vector-results', data.vector_results, 'vector', data.vector_filtered_reason);
      updateLatencyChart(data.sql_time_ms, data.vector_time_ms);

      // ── Update all session dashboard widgets ──────────────────────────────
      sessionStats.searchCount++;
      sessionStats.sqlTimes.push(data.sql_time_ms);
      sessionStats.vectorTimes.push(data.vector_time_ms);
      sessionStats.totalSql += data.sql_results.length;
      sessionStats.totalVec += data.vector_results.length;
      updateSessionCards();
      updateScoreDistribution(data.sql_results, data.vector_results);
      updateDonutChart();
      updateStrategyHistory(data.sql_strategy);
      updateSessionKeywords(data.keywords);

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

  let latencyHistory = [];
  function updateLatencyChart(sqlTime, vectorTime) {
    if (sqlTime !== undefined && vectorTime !== undefined) {
      latencyHistory.push({ sql: sqlTime, vector: vectorTime });
      if (latencyHistory.length > 5) {
        latencyHistory.shift(); // Keep last 5
      }
    }

    const chartEl = document.getElementById('latency-chart');
    if (!chartEl) return;

    if (latencyHistory.length === 0) {
      chartEl.innerHTML = '<div class="empty-state" style="width:100%; border:none;">No searches performed yet.</div>';
      return;
    }

    let maxTime = 10; // minimum scale
    latencyHistory.forEach(item => {
      if (item.sql > maxTime) maxTime = item.sql;
      if (item.vector > maxTime) maxTime = item.vector;
    });

    chartEl.innerHTML = latencyHistory.map((item, index) => {
      const sqlPct = Math.max((item.sql / maxTime) * 100, 2); // At least 2% height so it's visible
      const vecPct = Math.max((item.vector / maxTime) * 100, 2);
      return `
        <div class="bar-group">
          <div class="bar bar-sql tooltip" data-tip="${item.sql.toFixed(1)}ms" style="height: ${sqlPct}%"></div>
          <div class="bar bar-vector tooltip" data-tip="${item.vector.toFixed(1)}ms" style="height: ${vecPct}%"></div>
          <span>Q${index + 1}</span>
        </div>
      `;
    }).join('');
  }
  updateLatencyChart(); // Initialize empty chart

  // ── Session Dashboard Widgets ─────────────────────────────────────────────

  function updateSessionCards() {
    const $  = (id) => document.getElementById(id);
    if ($('dash-search-count')) $('dash-search-count').textContent = sessionStats.searchCount;
    if ($('dash-total-sql'))    $('dash-total-sql').textContent    = sessionStats.totalSql;
    if ($('dash-total-vec'))    $('dash-total-vec').textContent    = sessionStats.totalVec;
    if (sessionStats.sqlTimes.length > 0) {
      const avg = sessionStats.sqlTimes.reduce((a, b) => a + b, 0) / sessionStats.sqlTimes.length;
      if ($('dash-avg-sql')) $('dash-avg-sql').innerHTML = `${avg.toFixed(1)} <span class="metric-unit">ms</span>`;
    }
    if (sessionStats.vectorTimes.length > 0) {
      const avg = sessionStats.vectorTimes.reduce((a, b) => a + b, 0) / sessionStats.vectorTimes.length;
      if ($('dash-avg-vector')) $('dash-avg-vector').innerHTML = `${avg.toFixed(1)} <span class="metric-unit">ms</span>`;
    }
  }

  function updateScoreDistribution(sqlResults, vectorResults) {
    const tier = (score) => {
      const p = parseInt(score, 10);
      return p >= 60 ? 'strong' : p >= 30 ? 'partial' : 'weak';
    };
    sqlResults.forEach(r  => { sessionStats.scoreBuckets.sql[tier(r.score)]++; });
    vectorResults.forEach(r => { sessionStats.scoreBuckets.vec[tier(r.score)]++; });

    const el = document.getElementById('dash-score-dist');
    if (!el) return;
    const s = sessionStats.scoreBuckets.sql;
    const v = sessionStats.scoreBuckets.vec;
    const maxVal = Math.max(s.strong, s.partial, s.weak, v.strong, v.partial, v.weak, 1);

    const rows = [
      { label: '🟢 Strong 60–100%', key: 'strong' },
      { label: '🟡 Partial 30–60%', key: 'partial' },
      { label: '🔴 Weak   0–30%',  key: 'weak'    },
    ];
    el.innerHTML = rows.map(({ label, key }) => `
      <div class="score-dist-row">
        <span class="score-dist-label">${label}</span>
        <div class="score-dist-bars">
          <div class="score-dist-bar-wrapper">
            <span class="score-dist-bar-label">SQL</span>
            <div class="score-dist-track"><div class="score-dist-bar sql-bar" style="width:${(s[key]/maxVal)*100}%"></div></div>
            <span class="score-dist-count">${s[key]}</span>
          </div>
          <div class="score-dist-bar-wrapper">
            <span class="score-dist-bar-label">Vec</span>
            <div class="score-dist-track"><div class="score-dist-bar vec-bar" style="width:${(v[key]/maxVal)*100}%"></div></div>
            <span class="score-dist-count">${v[key]}</span>
          </div>
        </div>
      </div>
    `).join('');
  }

  function updateDonutChart() {
    const total = sessionStats.totalSql + sessionStats.totalVec;
    const ring  = document.getElementById('donut-ring');
    const label = document.getElementById('donut-label');
    const sqlCnt = document.getElementById('donut-sql-count');
    const vecCnt = document.getElementById('donut-vec-count');
    if (!ring) return;
    if (total === 0) {
      ring.style.background = 'conic-gradient(var(--outline-variant) 0% 100%)';
      if (label) label.textContent = '—';
      return;
    }
    const sqlPct = (sessionStats.totalSql / total) * 100;
    ring.style.background = `conic-gradient(var(--sql-logic) 0% ${sqlPct}%, var(--vector-logic) ${sqlPct}% 100%)`;
    if (label)  label.textContent  = `${Math.round(sqlPct)}%`;
    if (sqlCnt) sqlCnt.textContent = sessionStats.totalSql;
    if (vecCnt) vecCnt.textContent = sessionStats.totalVec;
  }

  function updateStrategyHistory(stratStr) {
    if (!stratStr || stratStr === 'N/A') return;
    const up = stratStr.toUpperCase();
    if (up.includes('AND'))     sessionStats.strategyHistory.AND++;
    if (up.includes('PARTIAL')) sessionStats.strategyHistory.PARTIAL++;
    if (up.includes('OR'))      sessionStats.strategyHistory.OR++;
    const max = Math.max(sessionStats.strategyHistory.AND, sessionStats.strategyHistory.PARTIAL, sessionStats.strategyHistory.OR, 1);
    const set = (cntId, barId, val) => {
      const c = document.getElementById(cntId); if (c) c.textContent = val;
      const b = document.getElementById(barId);  if (b) b.style.width = `${(val / max) * 100}%`;
    };
    set('strat-and-count',     'strat-and-bar',     sessionStats.strategyHistory.AND);
    set('strat-partial-count', 'strat-partial-bar', sessionStats.strategyHistory.PARTIAL);
    set('strat-or-count',      'strat-or-bar',      sessionStats.strategyHistory.OR);
  }

  function updateSessionKeywords(keywords) {
    keywords.forEach(kw => {
      sessionStats.sessionKeywords[kw] = (sessionStats.sessionKeywords[kw] || 0) + 1;
    });
    const el = document.getElementById('dash-session-keywords');
    if (!el) return;
    const sorted = Object.entries(sessionStats.sessionKeywords).sort((a, b) => b[1] - a[1]).slice(0, 20);
    if (sorted.length === 0) {
      el.innerHTML = '<span style="opacity:0.5;font-style:italic;font-size:0.875rem">Search to populate...</span>';
      return;
    }
    const maxKw = sorted[0][1];
    el.innerHTML = sorted.map(([kw, cnt]) => {
      const opacity = 0.55 + Math.min((cnt / maxKw) * 0.45, 0.45);
      const fsize   = cnt > 2 ? '0.9rem' : '0.8rem';
      const badge   = cnt > 1 ? ` <span style="opacity:0.65;font-size:0.7rem">×${cnt}</span>` : '';
      return `<span class="chip chip-sql" style="opacity:${opacity};font-size:${fsize}">${kw}${badge}</span>`;
    }).join('');
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

  const renderResults = (containerId, data, type, filteredReason = '') => {
    const container = document.getElementById(containerId);
    container.innerHTML = '';

    if (data.length === 0) {
      let label = filteredReason;
      if (!label) {
        if (type === 'vector' && vectorThresholdRange && vectorThresholdRange.value > 0) {
          label = `Does not satisfy vector threshold = ${vectorThresholdRange.value}%`;
        } else if (type === 'sql' && minScoreRange && minScoreRange.value > 0) {
          label = `Does not satisfy min match score = ${minScoreRange.value}%`;
        } else {
          label = type === 'vector'
            ? 'No vector results — check Milvus is running and collection is loaded.'
            : 'No PostgreSQL matches found for these keywords.';
        }
      }
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
  renderResults('sql-results', [], 'sql', '');
  renderResults('vector-results', [], 'vector', '');

  const cvSearchInput = document.getElementById('cv-search');
  const jdSearchInput = document.getElementById('jd-search');

  const renderTable = (tbodyId, data, columns) => {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    tbody.innerHTML = '';
    if (data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No records found.</td></tr>';
      return;
    }
    data.forEach(row => {
      const tr = document.createElement('tr');
      columns.forEach(col => {
        const td = document.createElement('td');
        td.innerHTML = row[col] ?? '';
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  };

  async function loadCVs(query = '') {
    try {
      const url = `${API_BASE}/api/cvs?query=${encodeURIComponent(query)}&limit=100`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`CV endpoint returned ${res.status}`);
      const data = await res.json();
      renderTable('cv-tbody', data.cvs, ['id', 'position', 'keyword', 'exp_years', 'looking_for']);
    } catch (err) {
      console.error('Failed to load CVs', err);
      renderTable('cv-tbody', []);
    }
  }

  async function loadJDs(query = '') {
    try {
      const url = `${API_BASE}/api/jds?query=${encodeURIComponent(query)}&limit=100`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`JD endpoint returned ${res.status}`);
      const data = await res.json();
      renderTable('jd-tbody', data.jds, ['id', 'position', 'company', 'keyword', 'exp_years']);
    } catch (err) {
      console.error('Failed to load JDs', err);
      renderTable('jd-tbody', []);
    }
  }

  if (cvSearchInput) {
    cvSearchInput.addEventListener('input', () => {
      clearTimeout(cvSearchInput._debounceId);
      cvSearchInput._debounceId = setTimeout(() => loadCVs(cvSearchInput.value.trim()), 250);
    });
  }

  if (jdSearchInput) {
    jdSearchInput.addEventListener('input', () => {
      clearTimeout(jdSearchInput._debounceId);
      jdSearchInput._debounceId = setTimeout(() => loadJDs(jdSearchInput.value.trim()), 250);
    });
  }

  loadCVs();
  loadJDs();
});
