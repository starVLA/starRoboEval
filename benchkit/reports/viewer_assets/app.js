/* Local artifact viewer. All record-derived text is inserted as textContent. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const data = window.EVALUATION_VIEWER;
  const PAGE_SIZE = 32;
  const cameraLabel = (camera) => `${camera} 相机`;
  let task, calls = [], steps = [], filtered = [], searchText = [], selected = 0, page = 0;
  let mainCamera, videos = [], seekGuardUntil = 0, taskIndex = 0;
  const finite = (value) => value !== null && value !== '' && Number.isFinite(Number(value));
  const number = (value, fallback = 0) => finite(value) ? Number(value) : fallback;
  const show = (value) => value === null || value === undefined || value === '' ? '未记录' : String(value);
  const count = (value) => finite(value) ? Number(value).toLocaleString('zh-CN') : '未记录';
  const list = (value) => Array.isArray(value) ? value : [];
  const text = (id, value) => { $(id).textContent = show(value); };
  const node = (tag, className, value) => { const el = document.createElement(tag); if (className) el.className = className; if (value !== undefined) el.textContent = value; return el; };
  const statusLabel = (status) => ({closed: '已闭合', completed: '已完成', failed: '已结束', error: '异常结束', running: '运行中', aborted: '已中止', stopped: '已停止'}[status] || '已记录');
  const qValue = (item) => finite(item.score?.value) ? Number(item.score.value).toFixed(3) : '未记录';
  const note = (call) => typeof call.decision?.note === 'string' && call.decision.note.trim() ? call.decision.note : '未记录输出备注';
  const callName = (call, index) => `调用 ${show(call.policy_call ?? index + 1)}`;
  const safeMediaURL = (url) => typeof url === 'string' && /^media\/[a-zA-Z0-9_./-]+$/.test(url) && !url.split('/').includes('..') ? url : null;
  const stepFor = (call, index) => Math.max(0, number(call.input_to_policy?.step, number(call.first_ack?.control, index + 1) - 1));
  function metric(label, value) { const el = node('div', 'call-metric', label); el.append(node('strong', '', show(value))); return el; }
  function badge(value, teal = false) { return node('span', `tag${teal ? ' tag-teal' : ''}`, value); }
  function renderSummary() {
    const entries = [['任务', data.tasks.length], ['已闭合', data.tasks.filter((item) => ['closed', 'completed', 'failed', 'error', 'aborted', 'stopped'].includes(item.status)).length], ['原生成功', data.tasks.filter((item) => item.success === true).length]];
    $('summary').replaceChildren(...entries.map(([label, value]) => { const el = node('div', 'summary-item'); el.append(node('strong', '', String(value)), node('span', '', label)); return el; }));
    text('page-title', data.title || '评测回放');
    document.title = data.title || '评测回放';
    text('generated-at', data.generated_at ? `导出于 ${data.generated_at}` : '');
  }
  function renderTabs() {
    $('task-tabs').replaceChildren(...data.tasks.map((item, index) => {
      const button = node('button', 'task-tab'); button.type = 'button'; button.setAttribute('aria-pressed', String(index === taskIndex));
      button.append(node('span', 'task-tab-title', show(item.title || item.task || item.id)));
      const meta = node('span', 'task-tab-meta'); meta.append(node('strong', '', `分数 ${qValue(item)}`), node('span', '', `${count(item.counters?.action_decisions)} 次决策 · ${count(item.counters?.controls)} 控制`));
      button.append(meta); button.addEventListener('click', () => selectTask(index)); return button;
    }));
  }
  function selectTask(index) {
    videos.forEach(({video}) => video.pause()); taskIndex = index; task = data.tasks[index]; calls = list(task.calls); selected = 0; page = 0; mainCamera = list(task.contracts?.observation?.cameras).find((camera) => list(task.videos).some((v) => v.camera === camera)) ?? task.videos?.[0]?.camera;
    steps = calls.map(stepFor); searchText = calls.map((call, i) => `${callName(call, i)} ${note(call)}`.toLocaleLowerCase());
    $('note-search').value = ''; filtered = calls.map((_, i) => i);
    renderTabs(); text('task-title', task.title || task.task || task.id); text('task-id', task.task || task.id);
    $('task-outcome').replaceChildren(badge(statusLabel(task.status)), badge(task.success === true ? '原生成功' : task.success === false ? '未成功' : '成功状态未记录'), badge(`分数 ${qValue(task)} · 事后`, true));
    $('decision-slider').max = String(Math.max(0, calls.length - 1)); $('decision-slider').disabled = calls.length === 0;
    renderVideos(); renderCheckpoints(); renderSource(); selectCall(0, true);
  }
  function renderVideos() {
    videos.forEach(({video}) => video.pause()); videos = []; $('camera-grid').replaceChildren(); text('video-status', ''); $('video-status').textContent = '';
    const sources = list(task.videos).slice().sort((a, b) => Number(b.camera === mainCamera) - Number(a.camera === mainCamera));
    if (!sources.length) { $('camera-grid').append(node('p', 'empty', '此任务未附带视频。仍可查看决策与动作记录。')); return; }
    for (const source of sources) {
      const isMain = source.camera === mainCamera;
      const tile = node('figure', `camera-tile${isMain ? ' main-camera' : ''}`);
      const caption = node('figcaption'); caption.append(node('span', '', cameraLabel(source.camera)));
      const url = safeMediaURL(source.url);
      if (!url) { tile.append(node('p', 'camera-unavailable', '视频路径不可用')); }
      else {
        const video = document.createElement('video'); video.src = url; video.preload = 'metadata'; video.controls = isMain; video.muted = true; video.playsInline = true; video.setAttribute('aria-label', `${cameraLabel(source.camera)}回放`);
        const entry = {video, source, pendingControl: calls.length ? steps[selected] : 0}; videos.push(entry); video.playbackRate = Number($('playback-speed').value);
        video.addEventListener('loadedmetadata', () => { seekEntry(entry, entry.pendingControl); });
        video.addEventListener('error', () => { $('video-status').textContent = `${cameraLabel(source.camera)}视频无法加载，请确认回看服务及原始视频可用，且浏览器支持 MP4。`; });
        if (isMain) {
          video.addEventListener('timeupdate', () => followVideo(entry));
          video.addEventListener('seeking', () => syncOthers(entry));
          video.addEventListener('play', () => { syncOthers(entry); videos.filter((v) => v !== entry).forEach(({video: other}) => { const result = other.play(); if (result) result.catch(() => {}); }); });
          video.addEventListener('pause', () => videos.filter((v) => v !== entry).forEach(({video: other}) => other.pause()));
          video.addEventListener('ratechange', () => videos.filter((v) => v !== entry).forEach(({video: other}) => { other.playbackRate = video.playbackRate; }));
        } else { const switcher = node('button', '', '设为主画面'); switcher.type = 'button'; switcher.addEventListener('click', () => { mainCamera = source.camera; renderVideos(); seekControl(steps[selected] || 0); }); caption.append(switcher); }
        tile.append(video);
      }
      tile.append(caption); $('camera-grid').append(tile);
    }
  }
  function fps(entry) { return Math.max(1, number(entry.source.fps, 30)); }
  function seekEntry(entry, control) {
    entry.pendingControl = control;
    if (!entry.video.readyState) return;
    const target = (Math.max(0, control) + 0.1) / fps(entry);
    const maximum = finite(entry.video.duration) ? Math.max(0, entry.video.duration - 0.001) : target;
    try { entry.video.currentTime = Math.min(target, maximum); } catch (_) { /* Retry on loadedmetadata. */ }
  }
  function seekControl(control) { seekGuardUntil = performance.now() + 450; videos.forEach((entry) => seekEntry(entry, control)); text('frame-label', `控制帧 ${count(control)}`); }
  function syncOthers(main) {
    const control = main.video.currentTime * fps(main);
    for (const entry of videos) { if (entry !== main && entry.video.readyState && Math.abs(entry.video.currentTime - control / fps(entry)) > 0.12) { entry.video.currentTime = Math.min(control / fps(entry), Math.max(0, entry.video.duration - 0.001)); } }
  }
  function followVideo(entry) {
    const control = Math.max(0, Math.floor(entry.video.currentTime * fps(entry) + 0.001)); text('frame-label', `控制帧 ${count(control)}`);
    if (!$('auto-follow').checked || !calls.length || performance.now() < seekGuardUntil) return;
    // Input steps are ordered by the recorded sequential control protocol.
    let lo = 0, hi = steps.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (steps[mid] <= control) lo = mid + 1; else hi = mid; }
    const index = Math.max(0, lo - 1); if (index !== selected) selectCall(index, false);
    if (!entry.video.paused) syncOthers(entry);
  }
  function renderCheckpoints() {
    const points = [['首次', 0], ['25% 序号', .25], ['50% 序号', .5], ['75% 序号', .75], ['末次', 1]];
    $('checkpoints').replaceChildren(...points.map(([label, ratio]) => { const button = node('button', '', label); button.type = 'button'; button.disabled = !calls.length; const index = Math.round((calls.length - 1) * ratio); button.title = `等距采样：第 ${index + 1} 条记录`; button.addEventListener('click', () => selectCall(index, true)); return button; }));
  }
  function selectCall(index, seek) {
    selected = Math.max(0, Math.min(index, calls.length - 1)); $('decision-slider').value = String(selected);
    text('decision-position', calls.length ? `${selected + 1} / ${count(calls.length)}` : '0 / 0');
    $('previous-call').disabled = !calls.length || selected === 0; $('next-call').disabled = !calls.length || selected === calls.length - 1;
    const call = calls[selected]; $('seek-before').disabled = !call || !videos.length; $('seek-after').disabled = !call || !videos.length || !finite(call.last_ack?.control);
    const filteredPosition = filtered.indexOf(selected); if (filteredPosition >= 0) page = Math.floor(filteredPosition / PAGE_SIZE);
    renderNotes(); renderRecord();
    if (seek && call) seekControl(steps[selected]);
  }
  function renderNotes() {
    const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE)); page = Math.min(page, pages - 1);
    text('search-count', `${count(filtered.length)} 条`); text('page-position', `${page + 1} / ${pages} 页`);
    $('previous-page').disabled = page === 0; $('next-page').disabled = page >= pages - 1;
    const fragment = document.createDocumentFragment();
    for (const index of filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)) {
      const call = calls[index], button = node('button', 'note-item'); button.type = 'button'; button.setAttribute('aria-current', String(index === selected));
      const meta = node('span', 'note-meta'); meta.append(node('span', '', callName(call, index)), node('span', '', `输入 step ${steps[index]}`));
      button.append(meta, node('span', 'note-preview', note(call))); button.addEventListener('click', () => selectCall(index, true)); fragment.append(button);
    }
    if (!filtered.length) fragment.append(node('p', 'empty', calls.length ? '没有匹配的备注。' : '未记录策略调用。'));
    const container = $('notes-list');
    const hadFocus = container.contains(document.activeElement);
    const previousScroll = container.scrollTop; container.replaceChildren(fragment); container.scrollTop = previousScroll;
    const current = container.querySelector('[aria-current="true"]');
    if (current) {
      const bounds = current.getBoundingClientRect(), viewport = container.getBoundingClientRect();
      if (bounds.top < viewport.top) container.scrollTop -= viewport.top - bounds.top;
      else if (bounds.bottom > viewport.bottom) container.scrollTop += bounds.bottom - viewport.bottom;
      if (hadFocus) current.focus({preventScroll: true});
    }
  }
  function renderRecord() {
    const call = calls[selected];
    if (!call) { text('call-label', '无记录'); text('decision-note', '此任务没有可展示的策略调用。'); $('call-metrics').replaceChildren(); $('record-flags').replaceChildren(); text('ack-summary', '未记录'); $('ack-boundaries').replaceChildren(); text('instruction', '未记录'); text('actions-summary', '提交的动作 · 未记录'); text('actions-json', '未记录提交动作。'); text('action-contract', '未记录'); renderState('state-table', null); renderState('after-state-table', null); return; }
    const actionsRecorded = call.actions_availability === 'recorded' && Array.isArray(call.submitted_actions);
    const actions = actionsRecorded ? call.submitted_actions : [], ack = finite(call.acknowledged_count) ? Number(call.acknowledged_count) : null;
    text('call-label', `${callName(call, selected)} · 第 ${selected + 1} 条`);
    const metrics = [metric('输入 step', steps[selected]), metric('提交动作', actionsRecorded ? actions.length : '未记录'), metric('确认控制', ack)];
    if (finite(call.decision?.chunk_length)) metrics.push(metric('提议动作块长度', Number(call.decision.chunk_length)));
    if (finite(call.usage?.latency_s)) metrics.push(metric('调用耗时', `${Number(call.usage.latency_s).toFixed(2)} s`));
    if (call.timestamp) metrics.push(metric('记录时间', call.timestamp)); $('call-metrics').replaceChildren(...metrics);
    text('decision-note', note(call)); text('instruction', call.input_to_policy?.instruction);
    const flags = [];
    if (call.decision?.stop) flags.push('本次输出请求停止。');
    if (call.error) flags.push('本次调用记录了异常；此页不展开内部错误详情。');
    if (call.rejection) flags.push('本次提交记录了拒绝；请结合确认数量判断实际执行。');
    const unacked = Array.isArray(call.unacknowledged_actions) ? call.unacknowledged_actions.length : number(call.unacknowledged_actions, actionsRecorded && ack !== null ? Math.max(0, actions.length - ack) : 0);
    if (unacked > 0) flags.push(`${unacked} 个提交动作没有执行确认。`);
    $('record-flags').textContent = flags.join(' ');
    text('ack-summary', `${actionsRecorded ? `提交 ${actions.length} 个动作` : '提交动作未记录'}；${ack !== null ? `记录 ${ack} 个执行确认` : '执行确认数量未记录'}。`);
    $('ack-boundaries').replaceChildren(...[['首个确认', call.first_ack], ['末个确认', call.last_ack]].map(([label, boundary]) => { const card = node('div', 'ack-card'); card.append(node('strong', '', label)); card.append(node('span', '', boundary ? `control ${show(boundary.control)} · 观测 step ${show(boundary.observation?.step)}` : '未记录')); return card; }));
    text('actions-summary', `提交的动作 · ${actionsRecorded ? `${actions.length} 个` : '未记录'}`);
    const contract = task.contracts?.action || {};
    text('action-contract', `动作维度：${show(contract.size)}。字段顺序：${list(contract.names).join(' · ') || '未记录'}。以下是提交值；执行结果以 ACK 为准。`);
    // Only the action arrays are exposed; no raw call or administrative metadata.
    text('actions-json', actionsRecorded ? JSON.stringify(actions, null, 2) : '未记录提交动作；不能据此认定提交了 0 个动作。提议动作块长度也不等于实际提交或执行数量。');
    renderState('state-table', call.input_to_policy?.state);
    renderState('after-state-table', call.last_ack?.observation?.state);
  }
  function renderState(target, state) {
    const names = list(task.contracts?.observation?.state_names);
    let rows = [];
    if (Array.isArray(state)) rows = state.map((value, i) => [names[i] || `state[${i}]`, value]);
    else if (state && typeof state === 'object') rows = Object.entries(state);
    $(target).replaceChildren(...rows.map(([name, value]) => { const row = node('tr'); row.append(node('td', '', name), node('td', '', Array.isArray(value) ? value.map(show).join(', ') : show(value))); return row; }));
    if (!rows.length) { const row = node('tr'), cell = node('td', '', '未记录状态'); cell.colSpan = 2; row.append(cell); $(target).append(row); }
  }
  function renderSource() {
    const entries = [['原始 run_id', task.run_id], ['任务 ID', task.task || task.id], ['Benchmark', task.benchmark], ['协议', task.protocol], ['方法', task.method], ['方法版本', task.method_version], ['请求 / 声明模型', task.model], ['模型身份依据', '运行记录中的请求或声明；不构成提供方身份认证。'], ['种子', task.seed], ['状态', statusLabel(task.status)], ['策略调用 / 动作决策 / 控制', `${count(task.counters?.policy_calls)} / ${count(task.counters?.action_decisions)} / ${count(task.counters?.controls)}`], [task.score?.label || '原生 benchmark 分数（事后）', task.score?.scale ? `${qValue(task)}（${task.score.scale}）` : qValue(task)], ['评分来源', task.score?.source], ['输入相机', list(task.contracts?.observation?.cameras).join(' · ')]];
    // Show curated public termination labels; unknown codes must remain enum-shaped.
    const reasons = {'environment:terminated': '原生环境终止', 'environment:truncated': '原生环境截断', 'runner:policy_call_limit': '策略调用次数上限', 'runner:step_limit': '执行控制步数上限', 'policy:safety_stop': '策略请求安全停止', 'policy:task_complete': '策略声明任务完成'};
    const reason = task.termination_reason;
    const publicCode = typeof reason === 'string' && /^(environment|runner|policy):[a-z][a-z0-9_]{0,79}$/.test(reason);
    entries.push(['终止原因', reasons[reason] ? `${reasons[reason]} · ${reason}` : publicCode ? reason : reason ? '已记录（详见原始评测产物）' : '未记录']);
    for (const video of list(task.videos)) entries.push([cameraLabel(video.camera), `${count(video.frames)} 帧 · ${show(video.fps)} FPS · ${finite(video.bytes) ? (Number(video.bytes) / 1048576).toFixed(2) + ' MiB' : '大小未记录'}`]);
    $('source-details').replaceChildren(...entries.flatMap(([label, value]) => [node('dt', '', label), node('dd', '', show(value))]));
  }
  $('decision-slider').addEventListener('input', (event) => selectCall(Number(event.target.value), true));
  $('previous-call').addEventListener('click', () => selectCall(selected - 1, true)); $('next-call').addEventListener('click', () => selectCall(selected + 1, true));
  $('seek-before').addEventListener('click', () => seekControl(steps[selected] || 0)); $('seek-after').addEventListener('click', () => { if (finite(calls[selected]?.last_ack?.control)) seekControl(Number(calls[selected].last_ack.control)); });
  $('playback-speed').addEventListener('change', (event) => videos.forEach(({video}) => { video.playbackRate = Number(event.target.value); }));
  $('note-search').addEventListener('input', (event) => { const query = event.target.value.trim().toLocaleLowerCase(); filtered = calls.map((_, i) => i).filter((i) => !query || searchText[i].includes(query)); page = 0; $('notes-list').scrollTop = 0; renderNotes(); });
  $('previous-page').addEventListener('click', () => { page--; $('notes-list').scrollTop = 0; renderNotes(); }); $('next-page').addEventListener('click', () => { page++; $('notes-list').scrollTop = 0; renderNotes(); });
  if (!data || !Array.isArray(data.tasks) || !data.tasks.length) { $('load-status').textContent = '未找到可用的回放数据。请确认回看服务可用，或 data.js 与本页面位于同一目录。'; return; }
  renderSummary(); $('load-status').hidden = true; $('workspace').hidden = false; selectTask(0);
})();
