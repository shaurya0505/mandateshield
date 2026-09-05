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

    // Populate Decision Intelligence Panel (Why this Action?)
    if (data.decision_context) {
      const dc = data.decision_context;
      const elFailure = document.getElementById('hero-di-failure');
      const elTiming = document.getElementById('hero-di-timing');
      const elWindow = document.getElementById('hero-di-window');
      const elRail = document.getElementById('hero-di-rail');
      const elBudget = document.getElementById('hero-di-budget');
      const elRisk = document.getElementById('hero-di-risk');
      const elPriority = document.getElementById('hero-di-priority');
      const elAction = document.getElementById('hero-di-action');
      const elRationale = document.getElementById('hero-di-rationale');

      if (elFailure) elFailure.innerText = dc.failure_category || 'INSUFFICIENT_FUNDS';
      if (elTiming) elTiming.innerText = dc.historical_timing_window || 'Day 1–2 of Month';
      if (elWindow) elWindow.innerText = dc.next_actionable_window || 'September 1, 2026';
      if (elRail) elRail.innerText = dc.rail_health_status || 'HDFC Rail: 100% Normal';
      if (elBudget) elBudget.innerText = dc.retry_budget || '1 / 3 Allowed';
      if (elRisk) elRisk.innerText = dc.revenue_at_risk || '₹4,999.00';
      if (elPriority) elPriority.innerText = `${dc.recovery_priority} (Score: ${dc.recovery_potential_score})`;
      if (elAction) elAction.innerText = dc.selected_action || 'WAIT_AND_RETRY';
      if (elRationale) elRationale.innerText = dc.rationale || '';
    }

    // Populate Decision -> Outcome Summary Card
    if (data.outcome_summary) {
      const oc = data.outcome_summary;
      const elDecision = document.getElementById('hero-out-decision');
      const elAttempts = document.getElementById('hero-out-attempts');
      const elRecovered = document.getElementById('hero-out-recovered');
      const elCost = document.getElementById('hero-out-cost');
      const elNet = document.getElementById('hero-out-net');
      const elState = document.getElementById('hero-out-state');

      if (elDecision) elDecision.innerText = oc.decision;
      if (elAttempts) elAttempts.innerText = `${oc.attempts} Attempt`;
      if (elRecovered) elRecovered.innerText = oc.recovered_principal;
      if (elCost) elCost.innerText = oc.simulated_operational_cost;
      if (elNet) elNet.innerText = oc.net_recovery;
      if (elState) elState.innerText = `SETTLED: ${oc.final_state}`;
    }

    // Populate Paired Counterfactual Preview
    if (data.counterfactual_preview) {
      const cp = data.counterfactual_preview;
      
      // Policy A: No Recovery
      if (cp.no_recovery) {
        const no = cp.no_recovery;
        const elNoAtt = document.getElementById('cf-no-attempts');
        const elNoRec = document.getElementById('cf-no-recovered');
        const elNoCost = document.getElementById('cf-no-cost');
        const elNoNet = document.getElementById('cf-no-net');
        const elNoStat = document.getElementById('cf-no-status');

        if (elNoAtt) elNoAtt.innerText = no.attempts;
        if (elNoRec) elNoRec.innerText = no.recovered_principal;
        if (elNoCost) elNoCost.innerText = no.simulated_operational_cost;
        if (elNoNet) elNoNet.innerText = no.net_recovery;
        if (elNoStat) elNoStat.innerText = no.final_state;
      }

      // Policy B: Fixed Retry
      if (cp.fixed_retry) {
        const fix = cp.fixed_retry;
        const elFixAtt = document.getElementById('cf-fixed-attempts');
        const elFixRec = document.getElementById('cf-fixed-recovered');
        const elFixCost = document.getElementById('cf-fixed-cost');
        const elFixNet = document.getElementById('cf-fixed-net');
        const elFixStat = document.getElementById('cf-fixed-status');

        if (elFixAtt) elFixAtt.innerText = `${fix.attempts} (${fix.unnecessary_retries} unnecessary)`;
        if (elFixRec) elFixRec.innerText = fix.recovered_principal;
        if (elFixCost) elFixCost.innerText = fix.simulated_operational_cost;
        if (elFixNet) elFixNet.innerText = fix.net_recovery;
        if (elFixStat) elFixStat.innerText = fix.final_state;
      }

      // Policy C: MandateShield
      if (cp.mandateshield) {
        const ms = cp.mandateshield;
        const elMsAtt = document.getElementById('cf-ms-attempts');
        const elMsRec = document.getElementById('cf-ms-recovered');
        const elMsCost = document.getElementById('cf-ms-cost');
        const elMsNet = document.getElementById('cf-ms-net');
        const elMsStat = document.getElementById('cf-ms-status');

        if (elMsAtt) elMsAtt.innerText = `${ms.attempts} (${ms.unnecessary_retries} unnecessary)`;
        if (elMsRec) elMsRec.innerText = ms.recovered_principal;
        if (elMsCost) elMsCost.innerText = ms.simulated_operational_cost;
        if (elMsNet) elMsNet.innerText = `+${ms.net_recovery}`;
        if (elMsStat) elMsStat.innerText = ms.final_state;
      }
    }

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

    // Populate Decision Context
    if (data.decision_context) {
      const dc = data.decision_context;
      const elAiAction = document.getElementById('safety-ai-action');
      const elAiSource = document.getElementById('safety-ai-source');
      const elAiConf = document.getElementById('safety-ai-conf');
      const elAiRationale = document.getElementById('safety-ai-rationale');
      const elPolicyVerdict = document.getElementById('safety-policy-verdict');
      const elFailingRule = document.getElementById('safety-failing-rule');
      const elRuleCat = document.getElementById('safety-rule-cat');
      const elRejectionReason = document.getElementById('safety-rejection-reason');
      const elAuthStatus = document.getElementById('safety-auth-status');

      if (elAiAction) elAiAction.innerText = dc.proposed_action || 'RETRY_NOW';
      if (elAiSource) elAiSource.innerText = dc.planner_source || 'GEMINI_LLM';
      if (elAiConf) elAiConf.innerText = dc.model_confidence || '95% (0.95 Model Score)';
      if (elAiRationale) elAiRationale.innerText = dc.ai_rationale || '';
      if (elPolicyVerdict) elPolicyVerdict.innerText = `VERDICT: ${dc.policy_verdict || 'BLOCKED'}`;
      if (elFailingRule) elFailingRule.innerText = `${dc.failing_rule_id}: ${dc.failing_rule_name}`;
      if (elRuleCat) elRuleCat.innerText = `Provenance: ${dc.rule_category}`;
      if (elRejectionReason) elRejectionReason.innerText = dc.rejection_reason || '';
      if (elAuthStatus) elAuthStatus.innerText = 'DENIED (0 execution authorization tokens issued)';
    }

    // Populate Outcome Summary
    if (data.outcome_summary) {
      const oc = data.outcome_summary;
      const elState = document.getElementById('safety-out-state');
      const elAttempted = document.getElementById('safety-out-attempted');
      const elRecovered = document.getElementById('safety-out-recovered');
      const elCost = document.getElementById('safety-out-cost');
      const elFinal = document.getElementById('safety-out-final');

      if (elState) elState.innerText = `SETTLED: ${oc.final_state}`;
      if (elAttempted) elAttempted.innerText = oc.debit_attempted || '₹0.00';
      if (elRecovered) elRecovered.innerText = oc.recovered_principal || '₹0.00';
      if (elCost) elCost.innerText = oc.simulated_operational_cost || '₹0.00';
      if (elFinal) elFinal.innerText = oc.final_state || 'STOPPED';
    }

    // Render Timeline
    const container = document.getElementById('safety-timeline-container');
    container.innerHTML = data.timeline.map((evt, idx) => `
      <div class="p-3.5 bg-slate-950 rounded-lg border border-slate-800 flex items-start space-x-3 transition hover:border-slate-700">
        <div class="w-6 h-6 rounded-full bg-rose-600/20 text-rose-400 flex items-center justify-center font-mono font-bold text-xs shrink-0 mt-0.5">
          ${idx + 1}
        </div>
        <div class="flex-1 space-y-1">
          <div class="flex items-center justify-between">
            <span class="font-bold text-slate-200 text-xs">${evt.title}</span>
            <span class="text-[10px] text-slate-400 font-mono">${evt.timestamp}</span>
          </div>
          <p class="text-slate-300 text-xs">${evt.description}</p>
          <div class="pt-1 flex flex-wrap gap-2 text-[11px] font-mono text-slate-400">
            ${Object.entries(evt.details).map(([k, v]) => `<span class="bg-slate-900 px-2 py-0.5 rounded border border-slate-800">${k}: <strong class="text-slate-200">${Array.isArray(v) ? v.join(', ') : v}</strong></span>`).join('')}
          </div>
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

    // Populate Decision Context & Checklist
    if (data.decision_context) {
      const dc = data.decision_context;
      const elStage1 = document.getElementById('webhook-stage1-status');
      const elStage2 = document.getElementById('webhook-stage2-status');
      const elStage3 = document.getElementById('webhook-stage3-status');
      const elHmac = document.getElementById('webhook-check-hmac');
      const elAttempt = document.getElementById('webhook-check-attempt');
      const elAmount = document.getElementById('webhook-check-amount');
      const elDedup = document.getElementById('webhook-check-dedup');

      if (elStage1) elStage1.innerText = dc.execution_status || 'AMBIGUOUS_TIMEOUT';
      if (elStage2) elStage2.innerText = dc.security_status || 'HMAC-SHA256 VERIFIED';
      if (elStage3) elStage3.innerText = dc.duplicate_status || 'DUPLICATE IGNORED';

      if (dc.checks && dc.checks.length >= 4) {
        if (elHmac) elHmac.innerText = 'sha256=VERIFIED';
        if (elAttempt) elAttempt.innerText = dc.checks[0].detail || 'att_resilience_01 matched';
        if (elAmount) elAmount.innerText = dc.checks[1].detail || '₹7,999.00 exact match';
        if (elDedup) elDedup.innerText = dc.checks[3].detail || 'evt_rzp_async_9981 cached';
      }
    }

    // Populate Outcome Summary
    if (data.outcome_summary) {
      const oc = data.outcome_summary;
      const elState = document.getElementById('webhook-out-state');
      const elRecovered = document.getElementById('webhook-out-recovered');
      const elCost = document.getElementById('webhook-out-cost');
      const elNet = document.getElementById('webhook-out-net');
      const elFinal = document.getElementById('webhook-out-final');

      if (elState) elState.innerText = `SETTLED: ${oc.final_state}`;
      if (elRecovered) elRecovered.innerText = oc.recovered_principal || '₹7,999.00';
      if (elCost) elCost.innerText = oc.simulated_operational_cost || '₹5.00';
      if (elNet) elNet.innerText = oc.net_recovery || '₹7,994.00';
      if (elFinal) elFinal.innerText = oc.final_state || 'RECOVERED';
    }

    // Render Timeline
    const container = document.getElementById('webhook-timeline-container');
    if (container && data.timeline) {
      container.innerHTML = data.timeline.map((evt, idx) => `
        <div class="p-3.5 bg-slate-950 rounded-lg border border-slate-800 flex items-start space-x-3 transition hover:border-slate-700">
          <div class="w-6 h-6 rounded-full bg-indigo-600/20 text-indigo-400 flex items-center justify-center font-mono font-bold text-xs shrink-0 mt-0.5">
            ${idx + 1}
          </div>
          <div class="flex-1 space-y-1">
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
    }

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
