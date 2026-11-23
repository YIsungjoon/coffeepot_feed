const $ = id => document.getElementById(id);
const detail = $('detail');
const sources = { arxiv: 'arXiv · DataCite', crossref: 'Crossref', openalex: 'OpenAlex' };
const sourceName = source => sources[source] || source;
const topicNames = {
  'Life Sciences': '생명과학', 'Social Sciences': '사회과학',
  'Physical Sciences': '물리과학', 'Health Sciences': '보건과학',
  'Computer Science': '컴퓨터과학', 'Artificial Intelligence': '인공지능', 'Information Systems': '정보 시스템',
  Engineering: '공학', Mathematics: '수학', Medicine: '의학', Psychology: '심리학',
  'Economics and Econometrics': '경제학·계량경제학', 'Environmental Science': '환경과학',
};
const topicName = name => topicNames[name] || name;
const library = new Map();
let selected = null;
let activeSearch = null;
let searchRequest = null;
let visibleReferences = 12;
let libraryError = '';
let catalog = null;
let loadingTopics = false;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '요청을 완료하지 못했습니다.');
  return result;
}

function openView(name) {
  for (const view of ['search', 'topics', 'library']) {
    $(`${view}-tab`).setAttribute('aria-pressed', String(view === name));
    $(`${view}-view`).hidden = view !== name;
  }
  if (name === 'library') renderLibrary();
  if (name === 'topics' && !catalog) loadTopics();
}

function listing(paper, source) {
  const row = node('li', '', 'paper');
  const heading = node('h3');
  const title = node('button', paper.title, 'paper-title');
  title.type = 'button';
  title.addEventListener('click', () => openPaper(library.get(paper.doi.toLowerCase()) || { ...paper, source }));
  heading.append(title);
  const authors = paper.authors.slice(0, 4).join(', ') + (paper.authors.length > 4 ? ` 외 ${paper.authors.length - 4}명` : '');
  const metadata = [paper.date || paper.year, paper.venue || sourceName(source), authors].filter(Boolean).join(' · ');
  row.append(heading, node('p', metadata, 'meta'));
  if (paper.summary) row.append(node('p', paper.summary, 'paper-summary'));
  return row;
}

async function search(params, page = 1) {
  searchRequest?.abort();
  const request = new AbortController();
  searchRequest = request;
  activeSearch = { ...params, page };
  const { topicLabel, ...filters } = activeSearch;
  const inTopic = Boolean(filters.subfield);
  const query = new URLSearchParams(filters);
  history.replaceState(null, '', `/paper?${query}`);
  $('topic-context').hidden = !inTopic;
  $('topic-note').hidden = true;
  $('active-topic').textContent = topicLabel || '소분류별 논문';
  $('topic-order').value = inTopic ? params.order : 'recent';
  $('search-submit').disabled = true;
  $('pages').hidden = true;
  $('results').replaceChildren();
  $('search-status').textContent = '논문을 찾는 중입니다.';
  try {
    const endpoint = inTopic ? 'topic-works' : 'search';
    const result = await api(`/api/paper/${endpoint}?${query}`, { signal: request.signal });
    if (searchRequest !== request) return;
    const source = result.source || params.source;
    const topicPath = result.topic_path || result.papers[0]?.groups;
    if (inTopic && !topicLabel && topicPath) {
      $('active-topic').textContent = topicPath.map(topicName).join(' › ');
    }
    if (result.topic_keyword) {
      $('topic-note').textContent = `OpenAlex 분류 결과가 없어 Crossref에서 ‘${result.topic_keyword}’ 키워드로 검색했습니다.`;
      $('topic-note').hidden = false;
    }
    $('results').replaceChildren(...result.papers.map(paper => listing(paper, source)));
    $('search-status').textContent = result.papers.length
      ? `${sourceName(source)} · ${result.total.toLocaleString('ko-KR')}건`
      : '이 조건에 맞는 논문을 찾지 못했습니다.';
    $('pages').hidden = page === 1 && !result.has_next;
    $('page-number').textContent = `${page}페이지`;
    $('prev').disabled = page === 1;
    $('next').disabled = !result.has_next;
  } catch (error) {
    if (error.name !== 'AbortError') $('search-status').textContent = error.message;
  } finally {
    if (searchRequest === request) $('search-submit').disabled = false;
  }
}

async function loadTopics() {
  if (loadingTopics) return;
  loadingTopics = true;
  $('topics-retry').hidden = true;
  $('topics-status').textContent = 'OpenAlex 분야 목록을 불러오는 중입니다.';
  try {
    catalog = (await api('/api/paper/topics')).topics;
    renderTopics();
  } catch (error) {
    $('topics-status').textContent = error.message;
    $('topics-retry').hidden = false;
  } finally {
    loadingTopics = false;
  }
}

function renderTopics() {
  const query = $('topic-query').value.trim().toLocaleLowerCase();
  const topics = (catalog || []).filter(topic => [topic.domain, topic.field, topic.name]
    .some(name => `${name} ${topicName(name)}`.toLocaleLowerCase().includes(query)));
  const domains = Map.groupBy(topics, topic => topic.domain);
  $('topics-status').textContent = topics.length
    ? `OpenAlex · 대분류 ${domains.size}개 · 중분류 ${new Set(topics.map(topic => topic.field)).size}개 · 소분류 ${topics.length}개`
    : '일치하는 분야가 없습니다.';
  $('topic-groups').replaceChildren(...Array.from(domains, ([domain, members]) => {
    const branch = node('details', '', 'topic-domain');
    branch.open = Boolean(query);
    branch.append(node('summary', `${topicName(domain)} · ${members.length}개 소분류`));
    for (const [field, subjects] of Map.groupBy(members, topic => topic.field)) {
      const section = node('details', '', 'topic-field');
      const list = node('ul', '', 'topic-items');
      section.open = Boolean(query);
      section.append(node('summary', `${topicName(field)} · ${subjects.length}`), list);
      for (const topic of subjects) {
        const item = node('li');
        const button = node('button', topicName(topic.name));
        button.type = 'button';
        button.addEventListener('click', () => {
          const topicLabel = [topic.domain, topic.field, topic.name].map(topicName).join(' › ');
          openView('search');
          search({ source: 'openalex', subfield: topic.id, order: 'recent', topicLabel });
        });
        item.append(button);
        list.append(item);
      }
      branch.append(section);
    }
    return branch;
  }));
}

function options(id, values, label) {
  const select = $(id);
  const previous = select.value;
  select.replaceChildren(new Option(label, ''), ...[...new Set(values)].map(value => new Option(value, value)));
  select.value = values.includes(previous) ? previous : '';
}

function renderLibrary() {
  const all = [...library.values()].sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  $('library-count').textContent = all.length ? String(all.length) : '';
  $('filters').hidden = !all.length;
  options('domain', all.map(paper => paper.groups[0]).sort(), '전체');
  const domains = all.filter(paper => !$('domain').value || paper.groups[0] === $('domain').value);
  options('field', domains.map(paper => paper.groups[1]).sort(), '전체');
  const fields = domains.filter(paper => !$('field').value || paper.groups[1] === $('field').value);
  options('subfield', fields.map(paper => paper.groups[2]).sort(), '전체');
  const subjects = fields.filter(paper => !$('subfield').value || paper.groups[2] === $('subfield').value);
  const period = paper => paper.date?.slice(0, 7) || '발행일 미상';
  options('period', subjects.map(period), '전체');
  const filtered = subjects.filter(paper => !$('period').value || period(paper) === $('period').value);
  $('library-status').textContent = libraryError || (all.length ? `${filtered.length}건` : '검색 결과를 열고 보관함에 저장하세요.');
  const dates = Map.groupBy(filtered, paper => paper.date || '발행일 미상');
  $('library-list').replaceChildren(...Array.from(dates, ([day, papers]) => {
    const section = node('section');
    section.append(node('h3', day, 'period'));
    const groups = Map.groupBy(papers, paper => paper.groups.join(' › '));
    for (const [label, group] of groups) {
      const cluster = node('details', '', 'cluster');
      cluster.open = true;
      const list = node('ol', '', 'paper-list');
      list.append(...group.map(paper => listing(paper, paper.source)));
      cluster.append(node('summary', `${label} · ${group.length}건`), list);
      section.append(cluster);
    }
    return section;
  }));
}

function relatedBy(reference, paper) {
  return (reference.id && reference.id === paper.openalex_id) || reference.doi === paper.doi;
}

function linkedPaper(paper) {
  const button = node('button', paper.title);
  button.type = 'button';
  button.addEventListener('click', () => openPaper(paper));
  return button;
}

function renderNetwork(paper) {
  const saved = [...library.values()];
  const incoming = saved.filter(item => item.doi !== paper.doi && item.references.some(reference => relatedBy(reference, paper)));
  $('network-current').textContent = paper.title;
  $('references-title').textContent = `확인된 참고문헌 · ${paper.references.length}건`;
  $('citing').replaceChildren(...incoming.map(item => {
    const li = node('li');
    li.append(linkedPaper(item));
    return li;
  }));
  if (!incoming.length) $('citing').append(node('li', '보관함에 인용한 논문이 없습니다.', 'meta'));
  $('references').replaceChildren(...paper.references.slice(0, visibleReferences).map(reference => {
    const li = node('li');
    const match = saved.find(item => relatedBy(reference, item));
    if (match) li.append(linkedPaper(match));
    else {
      const link = node('a', reference.title || reference.doi || reference.id.split('/').at(-1));
      link.href = reference.url;
      link.target = '_blank';
      link.rel = 'noreferrer';
      li.append(link);
    }
    return li;
  }));
  if (!paper.references.length) $('references').append(node('li', '출처에서 제공한 참고문헌이 없습니다.', 'meta'));
  $('more-references').hidden = visibleReferences >= paper.references.length;
}

function updateLink(id, url) {
  const link = $(id);
  link.hidden = !url;
  if (url) link.href = url;
  else link.removeAttribute('href');
}

function openPaper(paper) {
  selected = paper;
  visibleReferences = 12;
  $('paper-title').textContent = paper.title;
  $('paper-meta').textContent = [paper.date || paper.year, paper.venue || sourceName(paper.source), paper.kind].filter(Boolean).join(' · ');
  $('paper-authors').textContent = paper.authors.join(', ');
  $('paper-class').hidden = !paper.groups;
  $('paper-class').textContent = paper.groups?.join(' › ') || '';
  $('paper-summary').textContent = paper.summary || '출처가 초록을 제공하지 않았습니다. 원문 페이지에서 확인하세요.';
  $('paper-status').textContent = '';
  updateLink('pdf', paper.pdf_url);
  updateLink('open-access', paper.open_access_url && paper.open_access_url !== paper.url ? paper.open_access_url : null);
  updateLink('publisher', paper.url);
  $('save').disabled = Boolean(paper.references);
  $('save').textContent = paper.references ? '보관함에 저장됨' : '보관함에 저장';
  $('relationships').hidden = !paper.references;
  if (paper.references) renderNetwork(paper);
  if (!detail.open) detail.showModal();
  detail.scrollTop = 0;
}

$('search-tab').addEventListener('click', () => openView('search'));
$('topics-tab').addEventListener('click', () => openView('topics'));
$('library-tab').addEventListener('click', () => openView('library'));
$('topics-retry').addEventListener('click', loadTopics);
$('topic-query').addEventListener('input', () => { if (catalog) renderTopics(); });
$('topic-order').addEventListener('change', () => search({ ...activeSearch, order: $('topic-order').value }));
for (const id of ['domain', 'field', 'subfield', 'period']) $(id).addEventListener('change', renderLibrary);
$('search-form').addEventListener('submit', event => {
  event.preventDefault();
  const q = $('query').value.trim();
  if (q) search({ q, source: $('source').value, order: $('order').value });
});
$('prev').addEventListener('click', () => search(activeSearch, activeSearch.page - 1));
$('next').addEventListener('click', () => search(activeSearch, activeSearch.page + 1));
$('more-references').addEventListener('click', () => { visibleReferences += 24; renderNetwork(selected); });
$('save').addEventListener('click', async () => {
  const paper = selected;
  $('save').disabled = true;
  $('paper-status').textContent = '분류와 참고문헌을 확인하며 저장하는 중입니다.';
  try {
    const result = await api('/api/paper/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: paper.source, doi: paper.doi }),
    });
    library.set(result.paper.doi, result.paper);
    renderLibrary();
    if (selected === paper && detail.open) {
      openPaper(result.paper);
      $('paper-status').textContent = '보관함에 저장했습니다.';
    }
  } catch (error) {
    if (selected === paper) {
      $('paper-status').textContent = error.message;
      $('save').disabled = false;
    }
  }
});

api('/api/paper/library').then(result => {
  for (const paper of result.papers) library.set(paper.doi, paper);
  renderLibrary();
}).catch(error => { libraryError = error.message; renderLibrary(); });

const initial = new URLSearchParams(location.search);
const initialQuery = initial.get('q')?.trim().slice(0, 180);
const initialSubfield = initial.get('subfield') || '';
const initialPage = Number(initial.get('page'));
const page = Number.isInteger(initialPage) && initialPage >= 1 && initialPage <= 100 ? initialPage : 1;
if (/^\d{1,6}$/.test(initialSubfield)) {
  const order = initial.get('order') === 'cited' ? 'cited' : 'recent';
  search({ source: 'openalex', subfield: initialSubfield, order }, page);
} else if (initialQuery) {
  const source = initial.get('source') === 'crossref' ? 'crossref' : 'arxiv';
  const order = initial.get('order') === 'recent' ? 'recent' : 'relevance';
  $('query').value = initialQuery;
  $('source').value = source;
  $('order').value = order;
  search({ q: initialQuery, source, order }, page);
}
