# 피드 대시보드

Obsidian에서 **설정 → 커뮤니티 플러그인**으로 이동해 **Dataview**를 설치하고 활성화하세요. 이 파일을 보관함에 복사한 뒤 읽기 보기로 열면 됩니다.

## 안 읽은 피드

```dataview
TABLE WITHOUT ID link(file.path, default(title, file.name)) AS "기사",
  date AS "수집일", source AS "출처", topics AS "주제"
FROM "10_Feeds/Articles"
WHERE type = "feed-article" AND status = "unread"
SORT date DESC, created_at DESC, file.name ASC
LIMIT 30
```

기사를 읽은 뒤 속성에서 `status`를 `read`로 바꾸면 위 표에서 빠집니다. `archived`로 바꾼 기사도 주제별 목록에서는 계속 찾을 수 있습니다.

## 주제별 기사

```dataview
TABLE WITHOUT ID topic AS "주제", length(rows) AS "건수",
  rows.article AS "기사"
FROM "10_Feeds/Articles"
WHERE type = "feed-article"
FLATTEN default(topics, list("미분류")) AS topic
FLATTEN list(link(file.path, default(title, file.name))) AS article
SORT date DESC, created_at DESC, file.name ASC
GROUP BY topic
SORT topic ASC
```

기사가 여러 주제에 해당하면 해당 주제마다 링크가 표시됩니다. 주제별 목록도 안 읽은 기사만 보려면 두 번째 쿼리의 `WHERE` 끝에 `AND status = "unread"`를 추가하세요.

개인 메모는 `20_Notes`에 쓰고 기사 파일을 `[[파일명|기사 제목]]`으로 연결하세요.
