"""Build the reader's daily briefing from locally collected articles."""

import re
from collections import Counter


TOKEN = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9+#.-]{1,}")
PARTICLE = re.compile(r"^([가-힣]{3,}?)(에서도|에서는|으로는|에서|으로|에게|까지|부터|처럼|[은는이가을를의에와과로도])$")
COMMON = {
    "개발", "결과", "기능", "기반", "기술", "기존", "내용", "다른", "대한", "도입", "대응", "때문", "동향", "동작",
    "모델", "문제", "방식", "방법", "발표", "비교", "사용", "사례", "상태", "서비스", "소개", "시대", "시장", "실행",
    "아래", "어떤", "여러", "예시", "오늘", "온라인", "운영", "이상", "이야기", "이후", "일부", "자료", "적용", "전환",
    "제공", "제품", "조직", "지원", "추가", "코드", "핵심", "활용", "환경", "회복", "가격", "자체", "직접", "전체",
    "이번", "이전", "최근", "새로운", "가능", "보여", "있음", "있습니다", "합니다", "했음", "합니다만",
    "변화", "위기", "요약", "실적", "역할", "엔비디아", "앤트로픽", "넷플릭스", "애플", "젠슨", "뉴스", "피드",
    "인터뷰", "에이전트", "방향", "방향이",
    "ai", "show", "gn", "the", "and", "for", "with", "from", "via", "news", "feed", "open", "new", "how", "into",
}
ALIASES = {
    "엔비디아": r"엔비디아|\bnvidia\b",
    "젠슨 황": r"젠슨\s*황|\bjensen\s+huang\b",
    "앤트로픽": r"앤트로픽|\banthropic\b",
    "넷플릭스": r"넷플릭스|\bnetflix\b",
    "애플": r"애플|\bapple\b",
    "AI 에이전트": r"ai\s*에이전트|코딩\s*에이전트|에이전틱|\bai\s+agents?\b|\bagentic\b",
    "데이터센터": r"데이터\s*센터|\bdata\s+cent(?:er|re)s?\b",
    "인수·합병": r"인수(?:합병)?|합병|\bm\s*&\s*a\b",
}


def keywords(text: str) -> dict[str, str]:
    terms = {}
    for raw_word in TOKEN.findall(text):
        word = raw_word.strip(".-")
        particle = PARTICLE.fullmatch(word)
        if particle:
            word = particle[1]
        key = word.casefold()
        if len(key) >= 3 and key not in COMMON:
            terms.setdefault(key, word)
    for name, pattern in ALIASES.items():
        if re.search(pattern, text, re.IGNORECASE):
            terms[name] = name
    return terms


def daily_briefing(articles: list[dict], day: str) -> dict:
    todays = [article for article in articles if article["collected_at"][:10] == day]
    topic_counts = Counter(article["topic"] or "미분류" for article in todays)
    title_words = [keywords(article["title"]) for article in todays]
    labels = {key: word for row in title_words for key, word in row.items()}
    all_words = [set(row) | keywords(article["excerpt"]).keys() for article, row in zip(todays, title_words)]
    groups = []
    for key, name in labels.items():
        matches = [i for i, words in enumerate(all_words) if key in words]
        if len(matches) < 2:
            continue
        source_count = len({todays[i]["source"] for i in matches})
        in_titles = sum(key in title_words[i] for i in matches)
        groups.append((source_count, len(matches), in_titles, name, key, matches))
    groups.sort(key=lambda group: (-group[0], -group[1], -group[2], -len(group[3]), group[3]))

    distinct_groups = []
    for group in groups:
        members = set(group[-1])
        if any(len(members.intersection(other[-1])) / len(members.union(other[-1])) >= 0.72 for other in distinct_groups):
            continue
        distinct_groups.append(group)
        if len(distinct_groups) == 8:
            break

    picks = []
    used_ids, used_topics = set(), set()
    used_clusters = []
    for source_count, size, _, name, key, matches in distinct_groups:
        if any(len(set(matches).intersection(cluster)) / min(len(matches), len(cluster)) >= 0.6 for cluster in used_clusters):
            continue
        ordered = sorted(matches, key=lambda i: (key not in title_words[i], i))
        for index in ordered:
            article = todays[index]
            if article["id"] in used_ids or (article["topic"] or "미분류") in used_topics:
                continue
            reason = f"{name} 관련 기사 {size}건 · 출처 {source_count}곳"
            picks.append({"article_id": article["id"], "reason": reason})
            used_ids.add(article["id"])
            used_topics.add(article["topic"] or "미분류")
            used_clusters.append(set(matches))
            break
        if len(picks) == 3:
            break

    for name, count in topic_counts.most_common():
        if len(picks) == 3:
            break
        if name in used_topics or name in {"기타", "미분류"}:
            continue
        article = next(a for a in todays if a["topic"] == name)
        picks.append({"article_id": article["id"], "reason": f"{name} · 오늘 수집 {count}건"})
        used_ids.add(article["id"])
    for article in todays:
        if len(picks) == 3:
            break
        if article["id"] not in used_ids:
            picks.append({"article_id": article["id"], "reason": "오늘 수집한 기사"})

    return {
        "day": day,
        "article_ids": [article["id"] for article in todays],
        "source_count": len({article["source"] for article in todays}),
        "topics": [{"name": name, "count": count} for name, count in topic_counts.most_common()],
        "keywords": [
            {"name": name, "count": size, "source_count": source_count, "article_ids": [todays[i]["id"] for i in matches]}
            for source_count, size, _, name, _, matches in distinct_groups
        ],
        "picks": picks,
    }
