const $ = id => document.getElementById(id);
const logBox = $('log');
let ids = [];
let stopped = false;
let running = false;
let current = null;
let batch = [];
let batchNumber = 0;
let tabId = null;
let seenRequests = new Map();
let pendingBodies = new Set();
let inMemoryRequestHeaders = {};
let directRequestUrls = new Set();
let offset = 0;
let committedOffset = 0;
let queueKey = '';
let queueLabel = 'queue';

function log(message) {
  const time = new Date().toLocaleTimeString();
  logBox.textContent += `\n[${time}] ${message}`;
  logBox.scrollTop = logBox.scrollHeight;
}
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

// Handles quoted cells and embedded commas; newlines inside quoted cells are not
// expected in the noteId column of the project's queue.
function csvRow(line) {
  const fields = [];
  let value = '', quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"' && quoted && line[i + 1] === '"') { value += '"'; i++; }
    else if (c === '"') quoted = !quoted;
    else if (c === ',' && !quoted) { fields.push(value); value = ''; }
    else value += c;
  }
  fields.push(value);
  return fields;
}

$('file').addEventListener('change', async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  const lines = (await file.text()).replace(/^\uFEFF/, '').split(/\r?\n/).filter(Boolean);
  const header = csvRow(lines.shift());
  const index = header.indexOf('noteId');
  if (index < 0) { log('CSV 缺少 noteId 列。'); return; }
  ids = [...new Set(lines.map(line => csvRow(line)[index]).filter(id => /^\d{15,20}$/.test(id)))];
  queueKey = `sameMediaQueue:${file.name}:${file.size}:${file.lastModified}`;
  queueLabel = file.name.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9_-]+/g, '_').slice(0, 60) || 'queue';
  offset = Number(localStorage.getItem(queueKey) || 0);
  committedOffset = offset;
  $('start').disabled = ids.length === 0;
  $('reset').disabled = ids.length === 0;
  $('position').textContent = `总数 ${ids.length}；下次从第 ${offset + 1} 条开始。`;
  log(`已载入 ${ids.length} 个不同 note ID，已保存游标 ${offset}。`);
});
$('reset').addEventListener('click', () => {
  if (running) return;
  offset = 0;
  committedOffset = 0;
  localStorage.setItem(queueKey, '0');
  $('position').textContent = `总数 ${ids.length}；下次从第 1 条开始。`;
  log('游标已重置；已下载的结果文件不会删除。');
});

async function command(method, params = {}) {
  return chrome.debugger.sendCommand({tabId}, method, params);
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (source.tabId !== tabId || !current) return;
  if (method === 'Network.requestWillBeSent') {
    if (/BirdwatchFetch(?:AuthenticatedBirdwatch|Media)MatchSlice/.test(params.request.url)) {
      // Only the selected headers needed for the same X request are retained
      // in memory. They are never added to exported results.
      current.requestTemplateUrl = params.request.url;
      const reusableHeaders = Object.fromEntries(Object.entries(params.request.headers || {})
        .filter(([name]) => /^(authorization|x-csrf-token|x-twitter-active-user|x-twitter-auth-type|x-client-transaction-id|x-twitter-client-language|accept)$/i.test(name)));
      if (Object.keys(reusableHeaders).some(name => name.toLowerCase() === 'authorization')) {
        inMemoryRequestHeaders = reusableHeaders;
      }
    }
  } else if (method === 'Network.responseReceived') {
    if (params.response.url.includes('/i/api/graphql/') && /Birdwatch|MediaMatch|communitynotes/i.test(params.response.url)) {
      const path = new URL(params.response.url).pathname;
      current.observedOperations.push({path, status: params.response.status});
    }
    if (!/BirdwatchFetch(?:AuthenticatedBirdwatch|Media)MatchSlice/.test(params.response.url)) return;
    if (directRequestUrls.has(params.response.url)) return;
    seenRequests.set(params.requestId, {
      status: params.response.status,
      path: new URL(params.response.url).pathname,
      noteId: current.noteId
    });
  } else if (method === 'Network.loadingFinished' && seenRequests.has(params.requestId)) {
    const meta = seenRequests.get(params.requestId);
    seenRequests.delete(params.requestId);
    const task = command('Network.getResponseBody', {requestId: params.requestId})
      .then(body => {
        const text = body.base64Encoded
          ? new TextDecoder().decode(Uint8Array.from(atob(body.body), c => c.charCodeAt(0)))
          : body.body;
        let json;
        try { json = JSON.parse(text); }
        catch { json = {unparsedBody: text.slice(0, 2000)}; }
        if (current?.noteId === meta.noteId) {
          current.responses.push({status: meta.status, path: meta.path, json});
          const slice = json?.data?.authenticated_birdwatch_match?.media_cluster_search_result_slice
            ?? json?.data?.birdwatch_media_match?.media_cluster_search_result_slice;
          if (slice?.slice_info) {
            // X omits next_cursor entirely on the final slice.
            current.nextCursor = slice.slice_info.next_cursor ?? null;
          }
          current.lastResponseAt = Date.now();
        }
      })
      .catch(error => { if (current?.noteId === meta.noteId) current.errors.push(`response body: ${error.message}`); })
      .finally(() => pendingBodies.delete(task));
    pendingBodies.add(task);
  }
});

function nextSliceUrl(template, cursor) {
  const url = new URL(template);
  const raw = url.searchParams.get('variables');
  if (!raw) throw new Error('GraphQL URL has no variables parameter');
  const variables = JSON.parse(raw);
  variables.cursor = cursor;
  url.searchParams.set('variables', JSON.stringify(variables));
  return url.href;
}

async function loadSliceDirectly(template, cursor) {
  const url = nextSliceUrl(template, cursor);
  directRequestUrls.add(url);
  const headers = inMemoryRequestHeaders;
  if (!Object.keys(headers).some(name => name.toLowerCase() === 'authorization')) {
    throw new Error('original request had no reusable authorization header');
  }
  const expression = `(async () => {
    const response = await fetch(${JSON.stringify(url)}, {
      method: 'GET', credentials: 'include', cache: 'no-store',
      headers: ${JSON.stringify(headers)}
    });
    return JSON.stringify({status: response.status, body: await response.text()});
  })()`;
  const evaluated = await command('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  if (evaluated.exceptionDetails || typeof evaluated.result?.value !== 'string') {
    throw new Error('browser page could not fetch the next slice');
  }
  const response = JSON.parse(evaluated.result.value);
  if (response.status !== 200) throw new Error(`direct slice HTTP ${response.status}`);
  return JSON.parse(response.body);
}

async function continueSlicesDirectly(target) {
  if (!target.requestTemplateUrl || !target.nextCursor) return false;
  const visited = new Set();
  for (let index = 0; index < 2000 && target.nextCursor; index++) {
    const cursor = target.nextCursor;
    if (visited.has(cursor)) throw new Error('repeated pagination cursor');
    visited.add(cursor);
    const json = await loadSliceDirectly(target.requestTemplateUrl, cursor);
    const slice = json?.data?.authenticated_birdwatch_match?.media_cluster_search_result_slice
      ?? json?.data?.birdwatch_media_match?.media_cluster_search_result_slice;
    if (!Array.isArray(slice?.tweets_results) || !slice?.slice_info) {
      throw new Error('direct slice response missing list');
    }
    target.responses.push({status: 200, path: 'direct_authenticated_slice', json});
    target.nextCursor = slice.slice_info.next_cursor ?? null;
    target.lastResponseAt = Date.now();
    await sleep(250);
  }
  return target.nextCursor === null;
}

async function pageState() {
  const result = await command('Runtime.evaluate', {
    expression: `JSON.stringify({
      url: location.href,
      title: document.title,
      ready: document.readyState,
      y: scrollY,
      height: document.documentElement.scrollHeight,
      view: innerHeight,
      width: innerWidth,
      rootScroll: document.scrollingElement?.scrollTop ?? null,
      scrollables: [...document.querySelectorAll('main, section, div')]
        .filter(e => e.scrollHeight > e.clientHeight + 100 && e.clientHeight > 200)
        .filter(e => /auto|scroll/.test(getComputedStyle(e).overflowY))
        .slice(0, 5)
        .map(e => ({tag: e.tagName, top: e.scrollTop, height: e.scrollHeight, view: e.clientHeight})),
      articles: document.querySelectorAll('article').length,
      postIds: [...document.querySelectorAll('article a[href*="/status/"]')]
        .map(a => a.href.split('/status/')[1]?.split(/[/?#]/)[0])
        .filter(id => /^\\d{15,20}$/.test(id)),
      emptyNotice: /doesn.t have any matches yet|没有.*匹配|还没有.*匹配/i.test(document.body?.innerText || ''),
      bodyPreview: (document.body?.innerText || '').slice(0, 300)
    })`,
    returnByValue: true
  });
  if (result.exceptionDetails || typeof result.result?.value !== 'string') {
    throw new Error(result.exceptionDetails?.text || 'page-state evaluation returned no value');
  }
  return JSON.parse(result.result.value);
}

async function flushBatch() {
  if (!batch.length) return;
  const payload = JSON.stringify({source: 'X official Posts with the same media page responses', capturedAt: new Date().toISOString(), pages: batch}, null, 2);
  const url = URL.createObjectURL(new Blob([payload], {type: 'application/json'}));
  batchNumber++;
  await chrome.downloads.download({url, filename: `same_media_capture/batch_${queueLabel}_${String(batchNumber).padStart(4, '0')}.json`, conflictAction: 'uniquify', saveAs: false});
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  log(`已导出第 ${batchNumber} 批，${batch.length} 条 note。`);
  batch = [];
  committedOffset = offset;
  localStorage.setItem(queueKey, String(committedOffset));
  $('position').textContent = `总数 ${ids.length}；下次从第 ${committedOffset + 1} 条开始。`;
}

async function collectOne(noteId) {
  const started = performance.now();
  current = {noteId, pageUrl: `https://x.com/i/communitynotes/m/${noteId}`, startedAt: new Date().toISOString(), responses: [], observedOperations: [], visiblePostIds: [], errors: [], status: 'partial'};
  inMemoryRequestHeaders = {};
  directRequestUrls = new Set();
  seenRequests.clear();
  await chrome.tabs.update(tabId, {url: current.pageUrl});
  // Wait for this navigation to reach the intended page before inspecting DOM.
  // A fixed delay can accidentally inspect the previous note's page.
  for (let attempt = 0; attempt < 40 && !stopped; attempt++) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === 'complete' && tab.url?.includes(`/i/communitynotes/m/${noteId}`)) break;
    if (attempt >= 12 && tab.status === 'complete' && tab.url && !tab.url.startsWith('https://x.com/i/communitynotes/m/')) {
      current.status = 'redirected_or_login_required';
      current.finalUrl = tab.url;
      current.durationMs = Math.round(performance.now() - started);
      const finished = current;
      current = null;
      return finished;
    }
    await sleep(250);
  }
  await sleep(1200);
  let stable = 0;
  let last = '';
  const visibleIds = new Set();
  const began = Date.now();
  for (let step = 0; step < 100 && !stopped; step++) {
    let state;
    try { state = await pageState(); }
    catch (error) { current.errors.push(`page state: ${error.message}`); break; }
    if (!state.url.includes(`/i/communitynotes/m/${noteId}`)) {
      current.status = 'redirected_or_login_required';
      current.finalUrl = state.url;
      break;
    }
    for (const id of state.postIds || []) visibleIds.add(id);
    current.visiblePostIds = [...visibleIds];
    current.lastPageState = {title: state.title, ready: state.ready, articles: state.articles, emptyNotice: state.emptyNotice, bodyPreview: state.bodyPreview, y: state.y, height: state.height, view: state.view, rootScroll: state.rootScroll, scrollables: state.scrollables};
    if (state.emptyNotice && state.articles === 0 && current.responses.length > 0 && visibleIds.size === 0) {
      current.status = 'explicit_empty_page';
      break;
    }
    if (current.responses.length && current.nextCursor && current.requestTemplateUrl && !current.directFetchAttempted) {
      current.directFetchAttempted = true;
      try {
        if (await continueSlicesDirectly(current)) current.fastPath = 'direct_slices_complete';
      } catch (error) {
        current.fastPath = `direct_slices_unavailable: ${error.message}`;
        // Continue with the X page's own scrolling as a fallback.
      }
    }
    const signature = `${state.y}/${state.height}/${current.responses.length}`;
    if (signature === last && state.y + state.view >= state.height - 20) stable++;
    else stable = 0;
    last = signature;
    if (pendingBodies.size === 0 && current.responses.length && current.nextCursor === null) {
      current.status = 'pagination_complete';
      break;
    }
    if (Date.now() - (current.lastResponseAt ?? began) > 45000) {
      current.status = current.responses.length ? 'pagination_stalled' : 'no_matching_response_observed';
      break;
    }
    // Keep stimulating the page's own infinite-scroll loader while a cursor
    // remains. A temporary DOM bottom is not a completed server-side slice.
    await command('Input.dispatchMouseEvent', {
      type: 'mouseWheel', x: Math.round(state.width / 2), y: Math.round(state.view * 0.75),
      deltaX: 0, deltaY: Math.max(900, state.view * 1.2)
    });
    await command('Runtime.evaluate', {expression: `(() => {
      window.scrollTo(0, document.documentElement.scrollHeight);
      const candidates = [...document.querySelectorAll('main, section, div')]
        .filter(e => e.scrollHeight > e.clientHeight + 100 && e.clientHeight > 200)
        .filter(e => /auto|scroll/.test(getComputedStyle(e).overflowY));
      for (const e of candidates.slice(0, 3)) e.scrollTop = e.scrollHeight;
    })()`});
    await sleep(1600);
  }
  await Promise.allSettled([...pendingBodies]);
  if (current.status === 'partial' && !stopped) current.errors.push('step_limit_reached');
  current.durationMs = Math.round(performance.now() - started);
  delete current.requestTemplateUrl;
  inMemoryRequestHeaders = {};
  directRequestUrls = new Set();
  const finished = current;
  current = null;
  return finished;
}

$('stop').addEventListener('click', () => { stopped = true; log('正在停止并导出当前批次…'); });
$('start').addEventListener('click', async () => {
  if (running) return;
  running = true;
  stopped = false;
  $('start').disabled = true;
  $('stop').disabled = false;
  const limit = Math.max(1, Math.min(200000, Number($('limit').value) || 1));
  const runEnd = Math.min(ids.length, committedOffset + limit);
  try {
    if (runEnd <= committedOffset) {
      log('当前 CSV 已全部处理；如需重跑，请先点“从头开始”。');
      return;
    }
    // X may defer page rendering and scrolling in background tabs.
    const target = await chrome.tabs.create({url: 'about:blank', active: true});
    tabId = target.id;
    await chrome.debugger.attach({tabId}, '1.3');
    await command('Network.enable');
    await command('Runtime.enable');
    for (let i = committedOffset; i < runEnd; i++) {
      if (stopped) break;
      const id = ids[i];
      const result = await collectOne(id);
      batch.push(result);
      const captureFailed = !['pagination_complete', 'explicit_empty_page'].includes(result.status) || result.errors.length > 0;
      // Save incomplete pages for a separate retry pass, then move on. A
      // single large or inaccessible list must not block the entire queue.
      const loginRequired = /\/(?:login|i\/flow\/login)(?:[/?#]|$)/.test(result.finalUrl || '');
      const fatal = loginRequired || result.status === 'no_matching_response_observed';
      offset = fatal ? i : i + 1;
      log(`${id}: ${result.status}, ${result.responses.length} 个列表响应，${result.visiblePostIds.length} 个页面帖 ID，${result.observedOperations.length} 个相关接口响应。`);
      if (batch.length >= 25 || captureFailed) await flushBatch();
      if (captureFailed) log(fatal ? `${id}: 采集暂停，登录状态或页面响应需要检查。` : `${id}: 结果未完整，已保存供稍后重试；继续下一条。`);
      if (fatal) { stopped = true; break; }
      await sleep(800);
    }
    await flushBatch();
  } catch (error) {
    log(`采集停止：${error.message}`);
    await flushBatch();
  } finally {
    if (tabId !== null) {
      try { await chrome.debugger.detach({tabId}); } catch {}
    }
    tabId = null;
    current = null;
    inMemoryRequestHeaders = {};
    directRequestUrls = new Set();
    running = false;
    $('start').disabled = ids.length === 0;
    $('stop').disabled = true;
  }
});
