const DISCLAIMER = '本建议由 AI 生成，仅供参考，不构成医疗建议。剧烈运动前请咨询专业人士。';

const state = {
  screen: 'basic',
  mode: 'manual',
  profileQuestion: 0,
  plan: null,
  planTab: 'training',
  profile: {
    goal: '减脂',
    diet: '',
    injuries: ['无伤痛'],
    schedule: '',
    frequency: '每周 3 次',
    sleep: '',
    kitchen: '简单烹饪',
  },
};

const steps = [
  ['01', '身体数据'],
  ['02', '生活画像'],
  ['03', '生成方案'],
  ['04', '两周复盘'],
];

const form = document.querySelector('#wizardForm');
const planView = document.querySelector('#planView');
const alertBox = document.querySelector('#alert');
const stepTitle = document.querySelector('#stepTitle');
const stepKicker = document.querySelector('#stepKicker');
const reviewToggle = document.querySelector('#reviewToggle');

const iconObserver = new MutationObserver(() => {
  iconObserver.disconnect();
  window.lucide?.createIcons({ attrs: { 'aria-hidden': 'true', 'stroke-width': 2 } });
  iconObserver.observe(document.body, { childList: true, subtree: true });
});
iconObserver.observe(document.body, { childList: true, subtree: true });

function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

function showError(message) {
  alertBox.textContent = message;
  alertBox.classList.remove('hidden');
  window.scrollTo({ top: document.querySelector('.panel').offsetTop - 16, behavior: 'smooth' });
}

function clearError() {
  alertBox.textContent = '';
  alertBox.classList.add('hidden');
}

function renderProgress() {
  const current = state.screen === 'basic' ? 0 : state.screen === 'profile' ? 1 : state.screen === 'review' ? 3 : 2;
  document.querySelector('#progressList').innerHTML = steps.map((step, index) => `
    <li class="${index === current ? 'active' : ''} ${index < current ? 'done' : ''}">
      <span class="index">${index < current ? '✓' : step[0]}</span>
      <span>${step[1]}</span>
    </li>
  `).join('');
}

function renderHeader() {
  const labels = {
    basic: ['Phase 1', '身体数据'],
    profile: ['Phase 1', `生活画像 · ${state.profileQuestion + 1}/4`],
    generate: ['Phase 2', '生成前确认'],
    plan: ['Phase 2', '你的一周计划'],
    review: ['Phase 3', '两周复盘与优化'],
  };
  const [kicker, title] = labels[state.screen];
  stepKicker.textContent = kicker;
  stepTitle.textContent = title;
  reviewToggle.classList.toggle('hidden', !state.plan || state.screen === 'review');
}

function renderBasic() {
  const saved = state.plan?.profile || {};
  const p = { ...saved, ...state.profile };
  form.innerHTML = `
    ${state.mode === 'photo' ? `
      <div class="upload-zone">
        <div>
          <h3>上传体脂秤截图</h3>
          <p class="hint">支持 PNG、JPG、WEBP。图片只用于本次识别，不会写入服务器。</p>
          <input id="photoInput" type="file" accept="image/png,image/jpeg,image/webp" aria-label="选择体脂秤照片" />
          <p id="photoStatus" class="hint"></p>
        </div>
      </div>
    ` : ''}
    <div class="grid">
      <div class="field"><label for="height">身高（cm）</label><input id="height" name="height" type="number" min="120" max="230" step="0.1" value="${esc(p.height || '')}" placeholder="例如 168" required /><span class="hint">合理范围：120-230 cm</span></div>
      <div class="field"><label for="weight">体重（kg）</label><input id="weight" name="weight" type="number" min="30" max="250" step="0.1" value="${esc(p.weight || '')}" placeholder="例如 62.5" required /><span class="hint">合理范围：30-250 kg</span></div>
      <div class="field"><label for="bodyFat">体脂率（%）<span class="hint"> 可选</span></label><input id="bodyFat" name="body_fat" type="number" min="2" max="60" step="0.1" value="${esc(p.body_fat || '')}" placeholder="例如 24.5" /></div>
      <div class="field"><label for="muscle">肌肉量（kg）<span class="hint"> 可选</span></label><input id="muscle" name="muscle" type="number" min="10" max="120" step="0.1" value="${esc(p.muscle || '')}" placeholder="例如 42.0" /></div>
      <div class="field"><label for="age">年龄<span class="hint"> 可选</span></label><input id="age" name="age" type="number" min="13" max="90" step="1" value="${esc(p.age || '')}" placeholder="例如 29" /></div>
      <div class="field"><label for="sex">生理性别<span class="hint"> 可选，用于估算参考</span></label><select id="sex" name="sex"><option value="">暂不填写</option><option value="female" ${p.sex === 'female' ? 'selected' : ''}>女性</option><option value="male" ${p.sex === 'male' ? 'selected' : ''}>男性</option><option value="other" ${p.sex === 'other' ? 'selected' : ''}>其他 / 不便透露</option></select></div>
      <div class="field full"><label for="goal">这两周最想优先完成什么？</label><select id="goal" name="goal"><option ${p.goal === '减脂' ? 'selected' : ''}>减脂</option><option ${p.goal === '增肌' ? 'selected' : ''}>增肌</option><option ${p.goal === '维持' ? 'selected' : ''}>维持</option></select></div>
    </div>
    <div class="actions"><button class="primary" type="submit">保存数据，继续了解我 →</button></div>
  `;
}

const profileQuestions = [
  {
    title: '先说说你的饮食习惯。',
    intro: '我会据此换算成常见、买得到、做得出来的餐盘。',
    render: () => `<div class="field full"><label for="diet">偏好、忌口或过敏源</label><textarea id="diet" name="diet" placeholder="例如：喜欢米饭和鱼；不吃香菜；对牛奶不耐受">${esc(state.profile.diet)}</textarea><span class="hint">没有特殊情况可以填写“无”。</span></div>`,
  },
  {
    title: '在安排动作前，我必须先确认你的伤病。',
    intro: '请选出目前存在的疼痛或损伤部位；没有就选“无伤痛”。',
    render: () => `<div class="safety-note">安全边界：任何会让疼痛增加的动作都不做。报告伤痛后，我会从计划中移除对应的高风险动作。</div><div class="field full"><label>目前是否有伤病或疼痛？</label><div class="option-grid">${['无伤痛', '膝部', '腰背', '肩颈', '脚踝 / 足部', '手腕', '其他'].map((item) => `<label class="option"><input type="checkbox" name="injuries" value="${item}" ${state.profile.injuries.includes(item) ? 'checked' : ''} />${item}</label>`).join('')}</div></div><div class="field full"><label for="injuryNote">补充说明<span class="hint"> 可选</span></label><textarea id="injuryNote" name="injury_note" placeholder="例如：右膝上下楼会痛，已持续两周">${esc(state.profile.injuryNote || '')}</textarea></div>`,
  },
  {
    title: '什么时候最容易坚持？',
    intro: '把计划放进你真实的一天里，比写满动作更重要。',
    render: () => `<div class="grid"><div class="field"><label for="schedule">空闲时间段</label><input id="schedule" name="schedule" value="${esc(state.profile.schedule)}" placeholder="例如：工作日 19:00 后" /></div><div class="field"><label for="frequency">每周训练频率</label><select id="frequency" name="frequency">${['每周 2 次', '每周 3 次', '每周 4 次', '每周 5 次'].map((x) => `<option ${x === state.profile.frequency ? 'selected' : ''}>${x}</option>`).join('')}</select></div><div class="field full"><label for="sleep">睡眠作息</label><input id="sleep" name="sleep" value="${esc(state.profile.sleep)}" placeholder="例如：23:30 入睡，7:00 起床" /></div></div>`,
  },
  {
    title: '最后确认厨房条件。',
    intro: '这会决定食谱是“十分钟能完成”，还是可以安排更复杂的烹饪。',
    render: () => `<div class="field full"><label for="kitchen">你平时可以怎样做饭？</label><div class="option-grid">${['只做简单烹饪', '有基础厨具', '可以复杂烹饪', '主要外食'].map((item) => `<label class="option"><input type="radio" name="kitchen" value="${item}" ${state.profile.kitchen === item ? 'checked' : ''} />${item}</label>`).join('')}</div></div>`,
  },
];

function renderProfile() {
  const question = profileQuestions[state.profileQuestion];
  form.innerHTML = `<div class="field full"><h3>${question.title}</h3><span class="hint">${question.intro}</span></div>${question.render()}<div class="actions">${state.profileQuestion > 0 ? '<button class="secondary" type="button" data-action="profile-back">← 返回</button>' : ''}<button class="primary" type="submit">${state.profileQuestion === profileQuestions.length - 1 ? '生成我的计划 →' : '下一步 →'}</button></div>`;
}

function renderLoading(message) {
  form.classList.add('hidden');
  planView.classList.remove('hidden');
  planView.innerHTML = `<div class="loading"><div><div class="spinner"></div><strong>${message}</strong><p class="hint">正在按安全边界整理你的训练与饮食内容。</p></div></div>`;
}

function renderGenerate() {
  form.classList.remove('hidden');
  planView.classList.add('hidden');
  form.innerHTML = `<div class="safety-note"><strong>安全核对已完成</strong><br/>${esc(state.profile.injuries.join('、'))}。训练动作会根据你的反馈做保护性替换。</div><div class="summary-grid"><div class="metric-card"><span>目标</span><strong>${esc(state.profile.goal)}</strong></div><div class="metric-card"><span>饮食条件</span><strong>${esc(state.profile.kitchen)}</strong></div><div class="metric-card"><span>训练频率</span><strong>${esc(state.profile.frequency)}</strong></div><div class="metric-card"><span>饮水参考</span><strong>按体重计算</strong></div></div><div class="actions"><button class="secondary" type="button" data-action="profile-back">← 返回修改</button><button class="primary" type="submit">生成一周训练 + 饮食方案 →</button></div>`;
}

function formatExercise(exercise) {
  return `${esc(exercise.name)} · ${esc(exercise.sets)}组 × ${esc(exercise.reps)} · 休息 ${esc(exercise.rest)}`;
}

function renderPlan() {
  const plan = state.plan;
  if (!plan) return;
  form.classList.add('hidden');
  planView.classList.remove('hidden');
  const review = plan.review;
  const reviewBanner = review ? `<div class="safety-note"><strong>复盘结果：${esc(review.status)}</strong><br/>体重变化 ${review.weight_delta > 0 ? '+' : ''}${esc(review.weight_delta)} kg${review.fat_delta == null ? '' : `，体脂变化 ${review.fat_delta > 0 ? '+' : ''}${esc(review.fat_delta)}%`}。${esc(plan.coach_note || '')}</div>` : '';
  const tabButtons = `<div class="tabs" role="tablist"><button class="tab ${state.planTab === 'training' ? 'active' : ''}" data-plan-tab="training" type="button">训练安排</button><button class="tab ${state.planTab === 'diet' ? 'active' : ''}" data-plan-tab="diet" type="button">饮食菜单</button><button class="tab ${state.planTab === 'metrics' ? 'active' : ''}" data-plan-tab="metrics" type="button">评估与提醒</button></div>`;
  let content = '';
  if (state.planTab === 'training') {
    content = `<div class="safety-note">${esc(plan.injury_note || DISCLAIMER)}</div><div class="day-list">${plan.workouts.map((day) => `<article class="day-card"><div><span>${esc(day.day)} · ${esc(day.time)}</span><h3>${esc(day.focus)} <span class="pill">${esc(day.duration)}</span></h3></div><ul>${day.exercises.map((exercise) => `<li>${formatExercise(exercise)}</li>`).join('')}</ul></article>`).join('')}</div>`;
  } else if (state.planTab === 'diet') {
    content = `<div class="meal-list">${plan.meals.map((meal, index) => `<article class="meal-card"><div><span>DAY ${String(index + 1).padStart(2, '0')}</span><h3>一日餐盘</h3></div><ul><li><strong>早：</strong>${esc(meal.breakfast)}</li><li><strong>中：</strong>${esc(meal.lunch)}</li><li><strong>晚：</strong>${esc(meal.dinner)}</li><li><strong>加餐：</strong>${esc(meal.snack)}</li></ul></article>`).join('')}</div>`;
  } else {
    content = `<div class="summary-grid"><div class="metric-card"><span>每日饮水</span><strong>${esc(plan.water_liters)} L</strong></div><div class="metric-card"><span>两周后的关键数据</span><strong>体重</strong></div><div class="metric-card"><span>趋势数据</span><strong>体脂率</strong></div><div class="metric-card"><span>围度数据</span><strong>腰围</strong></div></div><ul class="plain-list">${plan.metrics.map((metric) => `<li class="review-card">${esc(metric)}</li>`).join('')}</ul><div class="safety-note">${esc(plan.review_reminder || '两周后回来填写新数据，我会继续调整。')}</div>`;
  }
  planView.innerHTML = `<div class="section-title"><div><p class="step-kicker">${review ? '优化版计划' : '你的起始计划'}</p><h3>${esc(plan.goal)} · ${esc(plan.focus)}</h3></div><button class="secondary" type="button" data-action="download-pdf">下载 PDF ↓</button></div>${reviewBanner}${tabButtons}${content}<div class="actions"><button class="ghost" type="button" data-action="review">两周后反馈数据</button><button class="primary" type="button" data-action="new-plan">重新填写</button></div><p class="hint">${DISCLAIMER}</p>`;
}

function collect(formElement) {
  const data = {};
  new FormData(formElement).forEach((value, key) => {
    if (key === 'injuries') {
      data.injuries = data.injuries || [];
      data.injuries.push(value);
    } else data[key] = value;
  });
  return data;
}

function clientNumber(value, label, min, max, optional = false) {
  if (value === '' && optional) return undefined;
  const number = Number(value);
  if (!Number.isFinite(number) || number < min || number > max) throw new Error(`${label}应在 ${min}-${max} 范围内，请重新输入。`);
  return number;
}

function saveLocal() {
  if (state.plan) localStorage.setItem('health-planner-plan', JSON.stringify(state.plan));
}

async function postJson(url, body) {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试。');
  return data;
}

async function generatePlan() {
  clearError();
  renderLoading('正在生成你的专属计划');
  try {
    const data = await postJson('/api/plan', { ...state.profile, injuries: state.profile.injuries.join('、'), height: state.profile.height, weight: state.profile.weight, body_fat: state.profile.body_fat, muscle: state.profile.muscle, age: state.profile.age, sex: state.profile.sex });
    state.plan = data.plan;
    saveLocal();
    state.screen = 'plan';
    state.planTab = 'training';
    form.classList.remove('hidden');
    renderHeader(); renderProgress(); renderPlan();
  } catch (error) {
    form.classList.remove('hidden');
    planView.classList.add('hidden');
    showError(error.message);
    renderGenerate();
  }
}

async function handlePhoto(file) {
  if (!file) return;
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) return showError('请上传 PNG、JPG 或 WEBP 图片。');
  if (file.size > 10 * 1024 * 1024) return showError('图片超过 10MB，请压缩后重试。');
  const status = document.querySelector('#photoStatus');
  status.textContent = '正在识别图片中的数字…';
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const data = await postJson('/api/ocr', { image: reader.result });
      const metrics = data.metrics || {};
      for (const [id, key] of [['weight', 'weight'], ['bodyFat', 'body_fat'], ['muscle', 'muscle']]) {
        if (metrics[key] != null) document.querySelector(`#${id}`).value = metrics[key];
      }
      status.textContent = '已识别可用数字，请检查后继续。';
    } catch (error) {
      status.textContent = '图片未能可靠识别，请在下方手动输入关键指标。';
      showError(error.message);
    }
  };
  reader.readAsDataURL(file);
}

async function submitBasic() {
  const data = collect(form);
  try {
    state.profile = { ...state.profile, ...data };
    state.profile.height = clientNumber(data.height, '身高', 120, 230);
    state.profile.weight = clientNumber(data.weight, '体重', 30, 250);
    state.profile.body_fat = clientNumber(data.body_fat || '', '体脂率', 2, 60, true);
    state.profile.muscle = clientNumber(data.muscle || '', '肌肉量', 10, 120, true);
    state.profile.age = clientNumber(data.age || '', '年龄', 13, 90, true);
    state.profile.goal = data.goal || '减脂';
    state.screen = 'profile';
    state.profileQuestion = 0;
    clearError(); renderHeader(); renderProgress(); renderProfile();
  } catch (error) { showError(error.message); }
}

function submitProfile() {
  const data = collect(form);
  if (state.profileQuestion === 0) {
    state.profile.diet = data.diet?.trim() || '无';
  } else if (state.profileQuestion === 1) {
    const injuries = data.injuries || [];
    if (!injuries.length) return showError('请先选择“无伤痛”或具体的疼痛部位。');
    if (injuries.length > 1 && injuries.includes('无伤痛')) return showError('“无伤痛”不能与其他部位同时选择。');
    state.profile.injuries = injuries;
    state.profile.injuryNote = data.injury_note?.trim() || '';
  } else if (state.profileQuestion === 2) {
    state.profile.schedule = data.schedule?.trim() || '工作日晚上';
    state.profile.frequency = data.frequency || '每周 3 次';
    state.profile.sleep = data.sleep?.trim() || '按个人作息';
  } else if (state.profileQuestion === 3) {
    if (!data.kitchen) return showError('请选择你的厨房条件。');
    state.profile.kitchen = data.kitchen;
    state.screen = 'generate';
    clearError(); renderHeader(); renderProgress(); renderGenerate();
    return;
  }
  state.profileQuestion += 1;
  clearError(); renderHeader(); renderProfile();
}

function renderReview() {
  state.screen = 'review';
  renderHeader(); renderProgress();
  form.classList.remove('hidden'); planView.classList.add('hidden');
  form.innerHTML = `<div class="safety-note">请在相同条件下填写新数据（建议晨起、如厕后）。如果两周内有明显疼痛、头晕或异常疲劳，请先暂停训练并咨询专业人士。</div><div class="grid"><div class="field"><label for="newWeight">新体重（kg）</label><input id="newWeight" name="weight" type="number" min="30" max="250" step="0.1" required /></div><div class="field"><label for="newFat">新体脂率（%）<span class="hint"> 可选</span></label><input id="newFat" name="body_fat" type="number" min="2" max="60" step="0.1" /></div><div class="field"><label for="newWaist">新腰围（cm）<span class="hint"> 可选</span></label><input id="newWaist" name="waist" type="number" min="40" max="200" step="0.1" /></div><div class="field"><label for="adherence">计划完成度</label><select id="adherence" name="adherence"><option value="high">80% 以上</option><option value="mid">50%-80%</option><option value="low">低于 50%</option></select></div><div class="field full"><label>如果本周期有效，下一周期菜单</label><div class="option-grid" role="radiogroup" aria-label="下一周期菜单选择"><label class="option"><input type="radio" name="menu_preference" value="keep" />继续当前菜单</label><label class="option"><input type="radio" name="menu_preference" value="refresh" checked />更换整周菜单</label></div><span class="hint">若本周期未达到目标，将按复盘结果重新调整训练和菜单。</span></div></div><div class="actions"><button class="secondary" type="button" data-action="back-plan">← 回看计划</button><button class="primary" type="submit">分析变化并生成下一周期 →</button></div>`;
}

async function submitReview() {
  const data = collect(form);
  try {
    data.weight = clientNumber(data.weight, '新体重', 30, 250);
    if (data.body_fat) data.body_fat = clientNumber(data.body_fat, '新体脂率', 2, 60);
    clearError(); renderLoading('正在对比两周变化');
    const response = await postJson('/api/review', { plan: state.plan, metrics: data });
    state.plan = response.plan; saveLocal(); state.screen = 'plan'; state.planTab = 'metrics'; renderHeader(); renderProgress(); renderPlan();
  } catch (error) {
    form.classList.remove('hidden'); planView.classList.add('hidden'); showError(error.message); renderReview();
  }
}

async function downloadPdf() {
  if (!state.plan) return;
  const button = document.querySelector('[data-action="download-pdf"]');
  if (button) { button.disabled = true; button.textContent = '正在准备…'; }
  try {
    const response = await fetch('/api/pdf', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan: state.plan }) });
    if (!response.ok) throw new Error('PDF 生成失败，请稍后重试。');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'health-plan.pdf'; anchor.click(); URL.revokeObjectURL(url);
  } catch (error) { showError(error.message); }
  finally { if (button) { button.disabled = false; button.textContent = '下载 PDF ↓'; } }
}

document.addEventListener('click', (event) => {
  const mode = event.target.closest('[data-mode]');
  if (mode) {
    state.mode = mode.dataset.mode;
    document.querySelectorAll('[data-mode]').forEach((button) => button.classList.toggle('active', button === mode));
    renderBasic();
    clearError();
  }
  const tab = event.target.closest('[data-plan-tab]');
  if (tab) { state.planTab = tab.dataset.planTab; renderPlan(); }
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (!action) return;
  if (action === 'profile-back') {
    if (state.screen === 'generate') state.profileQuestion = profileQuestions.length - 1;
    else state.profileQuestion = Math.max(0, state.profileQuestion - 1);
    state.screen = 'profile'; clearError(); renderHeader(); renderProfile();
  }
  if (action === 'download-pdf') downloadPdf();
  if (action === 'review') renderReview();
  if (action === 'back-plan') { state.screen = 'plan'; renderHeader(); renderProgress(); renderPlan(); }
  if (action === 'new-plan') { state.screen = 'basic'; state.plan = null; localStorage.removeItem('health-planner-plan'); renderHeader(); renderProgress(); renderBasic(); }
});

form.addEventListener('change', (event) => {
  if (event.target.matches('#photoInput')) handlePhoto(event.target.files[0]);
});

form.addEventListener('submit', (event) => {
  event.preventDefault();
  if (state.screen === 'basic') submitBasic();
  else if (state.screen === 'profile') {
    submitProfile();
  } else if (state.screen === 'generate') generatePlan();
  else if (state.screen === 'review') submitReview();
});

reviewToggle.addEventListener('click', renderReview);

function init() {
  try {
    const saved = JSON.parse(localStorage.getItem('health-planner-plan') || 'null');
    if (saved?.profile) {
      state.plan = saved;
      state.profile = { ...state.profile, ...saved.profile, ...(saved.preferences || {}) };
      state.screen = 'plan';
    }
  } catch (_) { /* ignore malformed local state */ }
  renderHeader(); renderProgress();
  if (state.screen === 'plan') renderPlan();
  else renderBasic();
}

init();
