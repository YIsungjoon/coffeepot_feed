const $ = id => document.getElementById(id);
const setText = (id, value) => { $(id).textContent = value; };
const reader = $('reader');
const previewButton = $('preview-original');
const previewFrame = $('original-frame');
const previewSection = $('original-preview');
let articles = [];
let source = '';
let topic = '';
let keyword = null;
let todayOnly = false;
let primaryOnly = false;
let todayIds = new Set();
let previewUrl = null;
let lastFeed = '';
let feedRequest = 0;

function element(tag, label, className) {
  const node = document.createElement(tag);
  node.textContent = label;
  if (className) node.className = className;
  return node;
}

const formatDate = date => date.replaceAll('-', '.');
const articleTopics = article => [...new Set([article.topic, ...article.related].filter(Boolean))];
const topicTags = article => articleTopics(article).map(value => element('span', value, 'tag'));

function setPreview(open) {
  if (open) previewFrame.src = previewUrl;
  else previewFrame.removeAttribute('src');
  previewSection.hidden = !open;
  previewButton.textContent = open ? '원문 접기' : '이 화면에서 원문 보기';
  previewButton.setAttribute('aria-expanded', String(open));
  reader.classList.toggle('with-original', open);
}

previewButton.addEventListener('click', () => {
  if (previewUrl) setPreview(previewSection.hidden);
});
reader.addEventListener('close', () => setPreview(false));

function readArticle(article) {
  const dateType = article.published_at ? '발행' : '수집';
  setText('article-meta', [article.source, article.date && `${dateType} ${formatDate(article.date)}`].filter(Boolean).join(' · '));
  setText('article-title', article.title);
  $('article-topics').replaceChildren(...topicTags(article));
  $('article-topics').hidden = !articleTopics(article).length;
  setText('excerpt-label', article.excerpt ? article.excerpt_label : '기사 내용');
  setText('article-excerpt', article.excerpt || '내용은 원문 또는 옵시디언 노트에서 확인할 수 있습니다.');
  $('original').hidden = !article.url;
  $('original').href = article.url || '';
  previewUrl = article.url?.startsWith('https://coffeepot.me/') ? article.url : null;
  previewButton.hidden = !previewUrl;
  $('original').classList.toggle('main', !previewUrl);
  $('note').href = article.note_url;
  setPreview(Boolean(previewUrl));
  reader.showModal();
  reader.scrollTop = 0;
}

function articleCard(article) {
  const card = element('article', '', 'card');
  const meta = element('p', '', 'card-meta');
  const date = element('time', formatDate(article.date));
  if (article.date) date.dateTime = article.date;
  meta.append(element('span', article.source), date);
  const heading = element('h3', '');
  const headline = element('button', article.title, 'headline');
  headline.type = 'button';
  headline.addEventListener('click', () => readArticle(article));
  heading.append(headline);
  card.append(meta, heading);
  if (article.excerpt) card.append(element('p', article.excerpt, 'preview'));
  const tags = topicTags(article);
  if (tags.length) {
    const label = element('div', '', 'tags');
    label.append(...tags);
    card.append(label);
  }
  return card;
}

function render() {
  const query = $('search').value.trim().toLocaleLowerCase();
  const keywordIds = keyword ? new Set(keyword.article_ids) : null;
  const matches = articles.filter(article => (!source || article.source === source)
    && (!topic || (primaryOnly ? (article.topic || '미분류') === topic : articleTopics(article).includes(topic)))
    && (!todayOnly || todayIds.has(article.id)) && (!keywordIds || keywordIds.has(article.id))
    && [article.title, article.excerpt].some(text => text.toLocaleLowerCase().includes(query)));
  $('cards').replaceChildren(...matches.map(articleCard));
  setText('count', `${matches.length}건${keyword ? ` · ${keyword.name}` : ''}`);
  $('empty').hidden = matches.length > 0;
  setText('empty', '조건에 맞는 기사가 없습니다.');
  for (const button of $('sources').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.source === source));
  for (const button of $('topics').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.topic === topic));
  for (const button of $('chart').querySelectorAll('button')) button.setAttribute('aria-pressed', String(primaryOnly && button.dataset.topic === topic));
  for (const button of $('keyword-chips').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.keyword === keyword?.name));
  $('today-only').setAttribute('aria-pressed', String(todayOnly));
}

function createFilters() {
  for (const value of [...new Set(articles.map(article => article.source))]) {
    if (Array.from($('sources').children).some(button => button.dataset.source === value)) continue;
    const button = element('button', value === 'COFFEEPOT' ? '커피팟' : value, 'source-button');
    button.type = 'button';
    button.dataset.source = value;
    $('sources').append(button);
  }
  const topics = [...new Set(articles.flatMap(articleTopics))].sort((left, right) => left.localeCompare(right, 'ko'));
  for (const value of ['', ...topics]) {
    if (Array.from($('topics').children).some(button => button.dataset.topic === value)) continue;
    const button = element('button', value || '전체 주제', 'topic-button');
    button.type = 'button';
    button.dataset.topic = value;
    $('topics').append(button);
  }
}

function rankedItem(article, reason) {
  const item = element('li', '');
  const text = element('div', '');
  const title = element('button', article.title, 'headline');
  title.type = 'button';
  title.addEventListener('click', () => readArticle(article));
  const sourceName = article.source === 'COFFEEPOT' ? '커피팟' : article.source;
  text.append(title, element('p', `${sourceName} · ${reason}`));
  item.append(text);
  return item;
}

function filterToday(mainTopic, group) {
  $('search').value = '';
  source = '';
  topic = mainTopic;
  primaryOnly = !!mainTopic;
  keyword = group;
  todayOnly = true;
  render();
  $('feed').scrollIntoView({ block: 'start' });
}

function showBriefing(briefing) {
  todayIds = new Set(briefing.article_ids);
  if (keyword) keyword = briefing.keywords.find(group => group.name === keyword.name) || null;
  setText('briefing-meta', `${formatDate(briefing.day)} · 오늘 수집 ${todayIds.size}건 · 출처 ${briefing.source_count}곳`);
  $('briefing-details').hidden = !todayIds.size;
  $('chart').replaceChildren();
  $('keyword-chips').replaceChildren();
  if (!todayIds.size) return;
  const lookup = new Map(articles.map(article => [article.id, article]));
  $('picks').replaceChildren(...briefing.picks.map(pick => rankedItem(lookup.get(pick.article_id), pick.reason)));

  const largest = Math.max(...briefing.topics.map(({ count }) => count));
  for (const group of briefing.topics) {
    const button = element('button', '', 'bar-button');
    button.type = 'button';
    button.dataset.topic = group.name;
    const bar = element('span', '', 'bar-fill');
    bar.style.setProperty('--bar-size', `${100 * group.count / largest}%`);
    const track = element('span', '', 'bar-track');
    track.append(bar);
    track.setAttribute('aria-hidden', 'true');
    button.append(element('span', group.name), track, element('span', `${group.count}건`, 'bar-count'));
    button.addEventListener('click', () => filterToday(group.name, null));
    $('chart').append(button);
  }
  $('keywords').hidden = !briefing.keywords.length;
  for (const group of briefing.keywords) {
    const button = element('button', `${group.name} ${group.count}건`, 'topic-button');
    button.type = 'button';
    button.dataset.keyword = group.name;
    button.addEventListener('click', () => filterToday('', keyword?.name === group.name ? null : group));
    $('keyword-chips').append(button);
  }
}

async function load() {
  const request = ++feedRequest;
  try {
    const response = await fetch('/api/reader');
    if (!response.ok) throw new Error();
    const feed = await response.text();
    if (request !== feedRequest || feed === lastFeed) return;
    const data = JSON.parse(feed);
    if (!lastFeed && !$('search').value.trim()) todayOnly = data.briefing.article_ids.length > 0;
    lastFeed = feed;
    articles = data.articles;
    createFilters();
    showBriefing(data.briefing);
    $('recommend').disabled = !articles.length;
    render();
  } catch {
    if (!lastFeed) setText('empty', '기사 목록을 불러오지 못했습니다. 잠시 뒤 다시 시도합니다.');
  }
}

$('search').addEventListener('input', () => {
  if ($('search').value.trim()) {
    todayOnly = false;
    keyword = null;
  }
  render();
});
$('today-only').addEventListener('click', () => {
  todayOnly = !todayOnly;
  if (!todayOnly) keyword = null;
  render();
});
$('sources').addEventListener('click', event => {
  const button = event.target.closest('button[data-source]');
  if (!button) return;
  source = button.dataset.source;
  render();
  $('feed').scrollIntoView({ block: 'start' });
});
$('topics').addEventListener('click', event => {
  const button = event.target.closest('button[data-topic]');
  if (!button) return;
  topic = button.dataset.topic;
  primaryOnly = false;
  keyword = null;
  render();
});

function updateArchiveLinks() {
  const query = $('archive-query').value.trim();
  const terms = new URLSearchParams({ q: `site:news.hada.io/topic ${query}` });
  $('search-geeknews').href = query ? `https://www.google.com/search?${terms}` : 'https://news.hada.io/past';
}

$('archive-query').addEventListener('input', updateArchiveLinks);
$('archive').addEventListener('toggle', () => {
  if ($('archive').open && !$('archive-query').value) {
    $('archive-query').value = $('search').value.trim().slice(0, 120);
    updateArchiveLinks();
  }
});

async function saveArchiveArticle(url, title) {
  const response = await fetch('/api/archive/import', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, title }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '기사를 저장하지 못했습니다.');
  await load();
  return result;
}

function archiveResult(article) {
  const item = element('li', '');
  const details = element('div', '');
  const link = element('a', article.title, 'headline');
  link.href = article.url;
  link.target = '_blank';
  link.rel = 'noreferrer';
  details.append(link);
  if (article.excerpt) details.append(element('p', article.excerpt));
  const saved = articles.some(savedArticle => savedArticle.url === article.url);
  const button = element('button', saved ? '저장됨' : '저장', 'dialog-action');
  button.type = 'button';
  button.disabled = saved;
  button.setAttribute('aria-label', `${article.title} ${button.textContent}`);
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const result = await saveArchiveArticle(article.url, article.title);
      button.textContent = '저장됨';
      button.setAttribute('aria-label', `${article.title} 저장됨`);
      setText('archive-message', result.already_saved ? '이미 저장된 기사입니다.' : '옵시디언에 저장했습니다.');
    } catch (error) {
      setText('archive-message', error.message);
      button.disabled = false;
    }
  });
  item.append(details, button);
  return item;
}

$('archive-search').addEventListener('submit', async event => {
  event.preventDefault();
  const query = $('archive-query').value.trim();
  if (!query) return;
  $('search-coffeepot').disabled = true;
  $('archive-results').replaceChildren();
  setText('archive-message', '커피팟 라이브러리를 검색하는 중입니다.');
  try {
    const response = await fetch(`/api/archive/coffeepot?${new URLSearchParams({ q: query })}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    setText('archive-message', result.articles.length
      ? `커피팟 검색 결과 첫 페이지 · ${result.articles.length}건`
      : '커피팟에서 검색 결과를 찾지 못했습니다.');
    $('archive-results').replaceChildren(...result.articles.map(archiveResult));
    const more = element('a', '커피팟 라이브러리 검색 결과 전체 보기 ↗');
    more.href = `https://coffeepot.me/library/?${new URLSearchParams({ keyword_type: 'all', keyword: query })}`;
    more.target = '_blank';
    more.rel = 'noreferrer';
    $('archive-message').append(' · ', more);
  } catch (error) {
    setText('archive-message', error.message || '커피팟 검색에 실패했습니다.');
  } finally {
    $('search-coffeepot').disabled = false;
  }
});

$('archive-import').addEventListener('submit', async event => {
  event.preventDefault();
  const url = $('archive-url').value.trim();
  const title = $('archive-title').value.trim();
  $('archive-save').disabled = true;
  setText('import-message', '기사 정보를 확인하는 중입니다.');
  try {
    const result = await saveArchiveArticle(url, title);
    setText('import-message', result.already_saved ? '이미 저장된 기사입니다.' : '옵시디언에 저장했습니다.');
    const saved = articles.find(article => article.url === result.url);
    if (saved) {
      const open = element('button', '저장된 기사 보기', 'topic-button');
      open.type = 'button';
      open.addEventListener('click', () => readArticle(saved));
      $('import-message').append(' ', open);
    }
    event.target.reset();
  } catch (error) {
    setText('import-message', error.message);
  } finally {
    $('archive-save').disabled = false;
  }
});

$('recommend-form').addEventListener('submit', async event => {
  event.preventDefault();
  const interest = $('interest').value.trim();
  if (!interest) { setText('recommend-message', '관심사를 입력해 주세요.'); return; }
  $('recommend').disabled = true;
  $('recommend-results').replaceChildren();
  setText('recommend-message', '관심사와 맞는 기사를 찾는 중입니다.');
  try {
    const response = await fetch('/api/recommend', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ interest }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '추천을 불러오지 못했습니다.');
    setText('recommend-message', result.picks.length
      ? `${result.scope} ${result.count}건 중 ${result.picks.length}건 추천`
      : `${result.scope}에서 관심사와 직접 관련된 기사를 찾지 못했습니다.`);
    $('recommend-results').replaceChildren(...result.picks.map(pick => rankedItem(pick.article, pick.reason)));
  } catch (error) {
    setText('recommend-message', error.message || '추천에 실패했습니다. 다시 시도해 주세요.');
  } finally {
    $('recommend').disabled = false;
  }
});
load();
setInterval(() => { if (!document.hidden) load(); }, 60_000);
