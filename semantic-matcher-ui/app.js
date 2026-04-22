document.addEventListener('DOMContentLoaded', () => {
  // Range Input live update
  const topNRange = document.getElementById('topNRange');
  const topNValue = document.getElementById('topNValue');
  topNRange.addEventListener('input', (e) => {
    topNValue.textContent = e.target.value;
  });

  // Tab Routing
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      tabContents.forEach(c => c.classList.add('hidden'));

      btn.classList.add('active');
      const targetId = btn.getAttribute('data-tab') + '-tab';
      document.getElementById(targetId).classList.remove('hidden');
    });
  });

  const analyzeBtn = document.querySelector('.btn-primary');
  const searchInput = document.querySelector('.search-input');
  
  analyzeBtn.addEventListener('click', async () => {
    const query = searchInput.value.trim();
    if (!query) return;
    
    analyzeBtn.innerHTML = '<i class="ph ph-spinner ph-spin"></i> Analyzing...';
    analyzeBtn.disabled = true;
    
    try {
      const response = await fetch(`http://127.0.0.1:8001/api/search?query=${encodeURIComponent(query)}&limit=5`);
      const data = await response.json();
      
      const keywordsContainer = document.querySelector('.keyword-chips');
      keywordsContainer.innerHTML = '';
      data.keywords.forEach(kw => {
        keywordsContainer.innerHTML += `<span class="chip chip-sql"><i class="ph ph-database"></i> ${kw}</span>`;
      });
      
      const metricValues = document.querySelectorAll('.metric-value');
      metricValues[0].textContent = data.sql_results.length;
      metricValues[1].textContent = data.vector_results.length;
      metricValues[2].innerHTML = `${data.sql_time_ms.toFixed(1)} <span class="metric-unit">ms</span>`;
      metricValues[3].innerHTML = `${data.vector_time_ms.toFixed(1)} <span class="metric-unit">ms</span>`;
      
      const sqlBadge = document.querySelector('.col-sql .strategy-badge');
      sqlBadge.textContent = `${data.sql_strategy} Logic`;
      
      renderResults('sql-results', data.sql_results, 'sql');
      renderResults('vector-results', data.vector_results, 'vector');
      
    } catch (err) {
      console.error(err);
      alert('Error connecting to backend API: Make sure FastAPI server is running on port 8001');
    } finally {
      analyzeBtn.innerHTML = '<i class="ph ph-sparkle"></i> Analyze';
      analyzeBtn.disabled = false;
    }
  });

  // Helper to parse scores if needed
  const formatScore = (score) => {
    if(typeof score === 'string' && score.includes('/')) {
      return score + ' Match'; // For SQL: "3/5 Match"
    }
    
    // For Vector Score (e.g. "0.54" or "0.5451")
    const num = parseFloat(score);
    if (!isNaN(num)) {
      // Multiply by 100 to get percentage
      return (num * 100).toFixed(1) + '% Match';
    }
    return score + ' Match';
  };


  const renderResults = (containerId, data, type) => {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    
    data.forEach((item, index) => {
      if (!item) {
        container.innerHTML += `
          <div class="result-card empty-state">
            No semantic match found for Rank #${index + 1}
          </div>
        `;
        return;
      }
      
      container.innerHTML += `
        <div class="result-card">
          <div class="result-header">
            <span class="result-rank">Rank #${item.rank}</span>
            <span class="score-badge">${formatScore(item.score)}</span>
          </div>
          <div class="result-title">${item.title}</div>
          <p class="result-snippet">${item.text}</p>
        </div>
      `;
    });
  };

  // Initially clear results
  renderResults('sql-results', [], 'sql');
  renderResults('vector-results', [], 'vector');

  // Mock Data for CV & JD Management
  const cvData = [
    { id: 'CAND-0891', pos: 'Data Scientist', kws: 'Python, ML, PyTorch', exp: '3', score: '92%' },
    { id: 'CAND-0892', pos: 'Backend Dev', kws: 'Java, Spring Boot', exp: '5', score: '85%' },
    { id: 'CAND-0893', pos: 'Frontend Dev', kws: 'React, Vue, TS', exp: '2', score: '78%' },
    { id: 'CAND-0894', pos: 'DevOps Engineer', kws: 'Docker, K8s, AWS', exp: '6', score: '88%' }
  ];

  const jdData = [
    { id: 'JOB-201', pos: 'Senior Data Engineer', comp: 'TechCorp Inc.', req: 'Spark, Python, Kafka', lvl: 'Senior' },
    { id: 'JOB-202', pos: 'Fullstack Developer', comp: 'StartupX', req: 'Node.js, React, MongoDB', lvl: 'Mid' },
    { id: 'JOB-203', pos: 'AI Researcher', comp: 'OpenAI Lab', req: 'LLM, LangChain, Python', lvl: 'Lead' }
  ];

  const renderTable = (tbodyId, data, columns) => {
    const tbody = document.getElementById(tbodyId);
    tbody.innerHTML = '';
    data.forEach(row => {
      const tr = document.createElement('tr');
      columns.forEach(col => {
        const td = document.createElement('td');
        if (col === 'score') {
          td.innerHTML = `<span class="score-badge">${row[col]}</span>`;
        } else {
          td.textContent = row[col];
        }
        tr.appendChild(td);
      });
      tr.addEventListener('click', () => {
        // Just visual effect for now
      });
      tbody.appendChild(tr);
    });
  };

  renderTable('cv-tbody', cvData, ['id', 'pos', 'kws', 'exp', 'score']);
  renderTable('jd-tbody', jdData, ['id', 'pos', 'comp', 'req', 'lvl']);
});
