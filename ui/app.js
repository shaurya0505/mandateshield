// MandateShield Command Center Application Logic

document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
  loadDashboardStats();
});

function switchTab(tabId) {
  const tabs = ['overview', 'hero-demo', 'safety-demo', 'webhook-demo', 'eval-demo'];
  tabs.forEach(t => {
    const view = document.getElementById(`view-${t}`);
    const tabBtn = document.getElementById(`tab-${t}`);
    if (view && tabBtn) {
      if (t === tabId) {
        view.classList.remove('hidden');
        tabBtn.classList.add('bg-slate-700', 'text-slate-200');
        tabBtn.classList.remove('text-slate-400');
      } else {
        view.classList.add('hidden');
        tabBtn.classList.remove('bg-slate-700', 'text-slate-200');
        tabBtn.classList.add('text-slate-400');
      }
    }
  });

  if (window.lucide) {
    window.lucide.createIcons();
  }
}

async function loadDashboardStats() {
  try {
    const res = await fetch('/api/dashboard/stats');
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById('stat-at-risk').innerText = data.total_revenue_at_risk_formatted;
    document.getElementById('stat-recovered').innerText = data.total_recovered_revenue_formatted;
    document.getElementById('stat-rate').innerText = `${data.recovery_rate_percent}%`;

    const tbody = document.getElementById('cases-table-body');
    if (tbody && data.cases) {
      tbody.innerHTML = data.cases.map(c => {
        let statusBadge = 'bg-slate-800 text-slate-400';
        if (c.status === 'RECOVERED') statusBadge = 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
        else if (c.status === 'PAYMENT_FAILED') statusBadge = 'bg-rose-500/10 text-rose-400 border border-rose-500/20';
        else if (c.status === 'RECOVERY_SCHEDULED') statusBadge = 'bg-purple-500/10 text-purple-400 border border-purple-500/20';
        else if (c.status === 'ESCALATED') statusBadge = 'bg-amber-500/10 text-amber-400 border border-amber-500/20';

        return `
          <tr class="hover:bg-slate-900/50 transition">
            <td class="py-3 px-4 text-white font-medium">${c.case_id}</td>
            <td class="py-3 px-4 text-slate-300">${c.customer_id}</td>
            <td class="py-3 px-4 text-slate-200 font-bold">${c.revenue_at_risk_formatted}</td>
            <td class="py-3 px-4"><span class="badge ${statusBadge}">${c.status}</span></td>
            <td class="py-3 px-4 text-slate-400">${c.total_attempts}</td>
            <td class="py-3 px-4 text-emerald-400 font-bold">${c.recovered_amount_formatted}</td>
            <td class="py-3 px-4 text-right">
              <button onclick="switchTab('hero-demo')" class="text-blue-400 hover:text-blue-300 underline text-xs">Simulate</button>
            </td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    console.error('Failed to load dashboard stats:', err);
  }
}

async function runHeroScenario() {
  const btn = document.getElementById('btn-run-hero');
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="h-4 w-4 animate-spin"></i><span>Executing Recovery...</span>`;
  if (window.lucide) window.lucide.createIcons();

  try {
    const res = await fetch('/api/demo/hero-scenario', { method: 'POST' });
    const data = await res.json();

    // Update status badge
    const badge = document.getElementById('hero-status-badge');
    badge.innerText = data.final_case_state;
    badge.className = 'badge bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';

    // Render timeline
    const container = document.getElementById('hero-timeline-container');
    container.innerHTML = data.timeline.map((evt, idx) => `
      <div class="p-3.5 bg-slate-950 rounded-lg border border-slate-800 flex items-start space-x-3 transition hover:border-slate-700">
        <div class="w-6 h-6 rounded-full bg-blue-600/20 text-blue-400 flex items-center justify-center font-mono font-bold text-xs shrink-0 mt-0.5">
          ${idx + 1}
        </div>
        <div class="space-y-1 flex-1">
          <div class="flex items-center justify-between">
            <span class="font-bold text-slate-200 text-xs">${evt.title}</span>
            <span class="text-[10px] text-slate-400 font-mono">${evt.timestamp}</span>
          </div>
          <p class="text-slate-300 text-xs">${evt.description}</p>
          <div class="pt-1 flex flex-wrap gap-2 text-[11px] font-mono text-slate-400">
            ${Object.entries(evt.details).map(([k, v]) => `<span class="bg-slate-900 px-2 py-0.5 rounded border border-slate-800">${k}: <strong class="text-slate-200">${v}</strong></span>`).join('')}
          </div>
        </div>
      </div>
    `).join('');

    loadDashboardStats();
  } catch (err) {
    console.error('Error running hero scenario:', err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="play" class="h-4 w-4"></i><span>Run Recovery Simulation</span>`;
    if (window.lucide) window.lucide.createIcons();
  }
}

async function runSafetyDemo() {
  const btn = document.getElementById('btn-run-safety');
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="h-4 w-4 animate-spin"></i><span>Evaluating Safety...</span>`;
  if (window.lucide) window.lucide.createIcons();

  try {
    const res = await fetch('/api/demo/safety-block', { method: 'POST' });
    const data = await res.json();

    const container = document.getElementById('safety-timeline-container');
    container.innerHTML = data.timeline.map((evt, idx) => `
      <div class="p-3 bg-slate-950 rounded border border-slate-800 flex items-start space-x-3">
        <div class="w-5 h-5 rounded-full bg-rose-600/20 text-rose-400 flex items-center justify-center font-mono font-bold text-xs shrink-0 mt-0.5">
          ${idx + 1}
        </div>
        <div class="flex-1 space-y-1">
          <div class="flex items-center justify-between">
            <span class="font-bold text-slate-200">${evt.title}</span>
            <span class="text-[10px] text-slate-400 font-mono">${evt.timestamp}</span>
          </div>
          <p class="text-slate-300">${evt.description}</p>
        </div>
      </div>
    `).join('');

    loadDashboardStats();
  } catch (err) {
    console.error('Error running safety demo:', err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="shield-alert" class="h-4 w-4"></i><span>Execute Safety Interception</span>`;
    if (window.lucide) window.lucide.createIcons();
  }
}

async function runWebhookDemo() {
  const btn = document.getElementById('btn-run-webhook');
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="h-4 w-4 animate-spin"></i><span>Reconciling Webhooks...</span>`;
  if (window.lucide) window.lucide.createIcons();

  try {
    const res = await fetch('/api/demo/webhook-resilience', { method: 'POST' });
    const data = await res.json();

    const container = document.getElementById('webhook-timeline-container');
    container.innerHTML = data.timeline.map((evt, idx) => `
      <div class="p-3 bg-slate-950 rounded border border-slate-800 flex items-start space-x-3">
        <div class="w-5 h-5 rounded-full bg-indigo-600/20 text-indigo-400 flex items-center justify-center font-mono font-bold text-xs shrink-0 mt-0.5">
          ${idx + 1}
        </div>
        <div class="flex-1 space-y-1">
          <div class="flex items-center justify-between">
            <span class="font-bold text-slate-200">${evt.title}</span>
            <span class="text-[10px] text-slate-400 font-mono">${evt.timestamp}</span>
          </div>
          <p class="text-slate-300">${evt.description}</p>
          <div class="pt-1 flex flex-wrap gap-2 text-[11px] font-mono text-slate-400">
            ${Object.entries(evt.details).map(([k, v]) => `<span class="bg-slate-900 px-2 py-0.5 rounded border border-slate-800">${k}: <strong class="text-slate-200">${v}</strong></span>`).join('')}
          </div>
        </div>
      </div>
    `).join('');

    loadDashboardStats();
  } catch (err) {
    console.error('Error running webhook resilience demo:', err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="refresh-cw" class="h-4 w-4"></i><span>Simulate Webhook & Replay</span>`;
    if (window.lucide) window.lucide.createIcons();
  }
}

async function runBatchEvaluation() {
  const btn = document.getElementById('btn-run-eval');
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="h-4 w-4 animate-spin"></i><span>Running Benchmark (20 Scenarios)...</span>`;
  if (window.lucide) window.lucide.createIcons();

  try {
    const res = await fetch('/api/evaluation/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed: 42, scenario_count: 20 }),
    });
    const data = await res.json();

    const noRec = data.policy_summaries.NO_RECOVERY;
    const fixed = data.policy_summaries.FIXED_RETRY;
    const ms = data.policy_summaries.MANDATESHIELD;
    const lift = data.lift_metrics;

    // Policy A
    document.getElementById('eval-no-gross').innerText = `₹${(noRec.gross_recovered_amount_in_paisa/100).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
    document.getElementById('eval-no-net').innerText = `₹${(noRec.net_recovered_amount_in_paisa/100).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
    document.getElementById('eval-no-rate').innerText = `${(noRec.recovery_rate * 100).toFixed(1)}%`;
    document.getElementById('eval-no-retries').innerText = noRec.total_retries;
    document.getElementById('eval-no-contact').innerText = noRec.customer_contact_index.toFixed(1);

    // Policy B
    document.getElementById('eval-fixed-gross').innerText = `₹${(fixed.gross_recovered_amount_in_paisa/100).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
    document.getElementById('eval-fixed-net').innerText = `₹${(fixed.net_recovered_amount_in_paisa/100).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
    document.getElementById('eval-fixed-rate').innerText = `${(fixed.recovery_rate * 100).toFixed(1)}%`;
    document.getElementById('eval-fixed-retries').innerText = `${fixed.total_retries} (${fixed.unnecessary_retries_count} unnecessary)`;
    document.getElementById('eval-fixed-contact').innerText = fixed.customer_contact_index.toFixed(1);

    // Policy C
    document.getElementById('eval-ms-gross').innerText = `₹${(ms.gross_recovered_amount_in_paisa/100).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
    document.getElementById('eval-ms-net').innerText = `₹${(ms.net_recovered_amount_in_paisa/100).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
    document.getElementById('eval-ms-rate').innerText = `${(ms.recovery_rate * 100).toFixed(1)}%`;
    document.getElementById('eval-ms-retries').innerText = `${ms.total_retries} (${ms.unnecessary_retries_count} unnecessary)`;
    document.getElementById('eval-ms-contact').innerText = ms.customer_contact_index.toFixed(1);

    // Lift Container
    const liftContainer = document.getElementById('eval-lift-container');
    liftContainer.innerHTML = `
      <div class="p-3 bg-slate-950 rounded border border-slate-800 space-y-1.5">
        <div class="flex justify-between"><span class="text-slate-400">Net Recovery Lift vs Fixed Retry:</span> <strong class="text-emerald-400 font-mono">₹${(lift.net_recovery_lift_vs_fixed_retry_in_paisa/100).toLocaleString('en-IN', {minimumFractionDigits: 2})}</strong></div>
        <div class="flex justify-between"><span class="text-slate-400">Recovery Rate Delta:</span> <strong class="text-blue-400 font-mono">${lift.recovery_rate_lift_vs_fixed_retry >= 0 ? '+' : ''}${lift.recovery_rate_lift_vs_fixed_retry}%</strong></div>
        <div class="flex justify-between"><span class="text-slate-400">Unnecessary Retries Avoided:</span> <strong class="text-emerald-400 font-mono">${lift.retries_avoided_vs_fixed_retry}</strong></div>
        <div class="flex justify-between"><span class="text-slate-400">Customer Harassment Reduction:</span> <strong class="text-emerald-400 font-mono">${lift.contact_reduction_vs_fixed_retry} index pts</strong></div>
      </div>
    `;

    // Action Distribution Container
    const actionsContainer = document.getElementById('eval-actions-container');
    actionsContainer.innerHTML = `
      <div class="p-3 bg-slate-950 rounded border border-slate-800 space-y-2">
        ${Object.entries(ms.action_distribution).map(([act, cnt]) => `
          <div class="flex items-center justify-between">
            <span class="text-slate-300 font-mono">${act}:</span>
            <span class="badge bg-blue-500/10 text-blue-400 font-mono">${cnt} times</span>
          </div>
        `).join('')}
      </div>
    `;

  } catch (err) {
    console.error('Error running batch evaluation:', err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="bar-chart-3" class="h-4 w-4"></i><span>Run Batch Evaluation (20 Scenarios)</span>`;
    if (window.lucide) window.lucide.createIcons();
  }
}

async function resetDemoState() {
  try {
    await fetch('/api/demo/reset', { method: 'POST' });
    loadDashboardStats();
    alert('Demo environment successfully reset to initial clean baseline.');
  } catch (err) {
    console.error('Error resetting demo:', err);
  }
}
