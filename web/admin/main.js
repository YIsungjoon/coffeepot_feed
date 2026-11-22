const $ = id => document.getElementById(id);
const show = (id, value) => { $(id).textContent = value; };
const runButton = $('run');
const statusFilter = $('filter-status');
const states = { classified: '분류 완료', review: '검토 필요', pending: '분류 대기', unclassified: '미분류' };
let articles = [];
let selected = null;
let sending = false;
let lastFinished;

const formatTime = value => value ? value.slice(0, 16).replace('T', ' ') : '—';
function replaceOptions(id, values, first) {
  const old = $(id).value;
  $(id).replaceChildren(new Option(first, ''), ...values.map(value => new Option(value, value)));
  if (values.includes(old)) $(id).value = old;
}
function statusBadge(node, article) {
  node.textContent = article.manual ? '수동 지정' : states[article.status];
  node.dataset.status = article.status;
}
function displayArticle(article) {
  $('detail').hidden = !article;
  $('detail-empty').hidden = !!article;
  if (!article) return;
  show('detail-meta', [article.source, article.date].filter(Boolean).join(' · '));
  statusBadge($('detail-status'), article);
  show('detail-name', article.title);
  show('detail-topic', article.topic || '—');
  show('detail-related', article.related.join(', ') || '—');
  show('detail-model', article.model || '—');
  show('detail-evidence', article.evidence);
  $('evidence').hidden = !article.evidence;
  $('note-link').href = article.note_url;
  $('original-link').hidden = !article.url;
  $('original-link').href = article.url || '';
}

function renderArticles() {
  const search = $('search').value.trim().toLocaleLowerCase();
  const source = $('source').value;
  const topic = $('topic').value;
  const state = statusFilter.value;
  const filtered = articles.filter(article => (!source || source === article.source)
    && (!topic || topic === article.topic || article.related.includes(topic))
    && (!state || state === article.status) && article.title.toLocaleLowerCase().includes(search));
  if (!filtered.some(article => article.id === selected)) selected = filtered[0]?.id;
  const rows = document.createDocumentFragment();
  for (const article of filtered) {
    const row = document.createElement('tr');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'article-button';
    button.textContent = article.title;
    button.addEventListener('click', () => {
      selected = article.id;
      for (const item of $('rows').rows) item.dataset.selected = String(item.dataset.id === selected);
      displayArticle(article);
    });
    row.dataset.id = article.id;
    row.dataset.selected = String(article.id === selected);
    row.insertCell().append(button);
    row.insertCell().textContent = article.source;
    row.insertCell().textContent = article.date || '—';
    const topicCell = row.insertCell();
    topicCell.className = 'topic';
    topicCell.textContent = article.topic || '—';
    const badge = document.createElement('span');
    badge.className = 'status';
    statusBadge(badge, article);
    row.insertCell().append(badge);
    rows.append(row);
  }
  $('rows').replaceChildren(rows);
  $('empty').hidden = filtered.length > 0;
  show('empty', '조건에 맞는 기사가 없습니다.');
  show('count', `${filtered.length}건`);
  displayArticle(filtered.find(article => article.id === selected));
  for (const button of document.querySelectorAll('[data-filter]')) {
    button.setAttribute('aria-pressed', String(button.dataset.filter === state));
  }
}

async function loadArticles() {
  const response = await fetch('/api/articles');
  if (!response.ok) throw new Error('기사 목록을 불러오지 못했습니다.');
  const data = await response.json();
  articles = data.articles;
  replaceOptions('source', [...new Set(articles.map(article => article.source))].sort(), '전체 출처');
  replaceOptions('topic', [...new Set([...data.topics, ...articles.map(article => article.topic).filter(Boolean)])], '전체 주제');
  show('total', articles.length);
  show('classified', articles.filter(article => article.status === 'classified').length);
  show('review', articles.filter(article => article.status === 'review').length);
  renderArticles();
  if (data.unreadable) show('notice', `읽지 못한 기사 노트 ${data.unreadable}건`);
}

async function refresh() {
  try {
    const response = await fetch('/api/status');
    if (!response.ok) throw new Error();
    const { running, next_run, last_run, log } = await response.json();
    $('connection').dataset.online = 'true';
    show('connection', running ? '수집·분류 중' : '서버 연결됨');
    show('next', formatTime(next_run));
    if (last_run) {
      const summary = running ? '진행 중' : last_run.exit_code === 0 ? '성공' : '실패';
      show('last', `최근 실행 ${summary} · ${formatTime(last_run.finished_at || last_run.started_at)}`);
    }
    show('log', log.length ? log.join('\n') : '아직 기록된 수집이 없습니다.');
    runButton.disabled = running || sending;
    const finished = last_run?.finished_at || '';
    if (lastFinished !== finished) {
      await loadArticles();
      lastFinished = finished;
    }
  } catch {
    $('connection').dataset.online = 'false';
    show('connection', '서버 연결 확인 필요');
    runButton.disabled = true;
  }
}

for (const id of ['source', 'topic', 'filter-status']) $(id).addEventListener('change', renderArticles);
$('search').addEventListener('input', renderArticles);
for (const button of document.querySelectorAll('[data-filter]')) {
  button.addEventListener('click', () => {
    $('search').value = $('source').value = $('topic').value = '';
    statusFilter.value = button.dataset.filter;
    renderArticles();
  });
}

runButton.addEventListener('click', async () => {
  sending = true;
  runButton.disabled = true;
  show('notice', '');
  try {
    const response = await fetch('/api/run', { method: 'POST' });
    if (!response.ok) show('notice', (await response.json()).error);
  } catch {
    show('notice', '수집 요청을 보내지 못했습니다.');
  } finally {
    sending = false;
    await refresh();
  }
});
refresh();
setInterval(refresh, 3000);
