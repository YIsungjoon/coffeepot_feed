# 피드 리더

GeekNews 공식 Atom 피드와 커피팟 공개 글 목록을 수집해 옵시디언 Markdown 노트로 저장합니다. 독자 화면에서 기사 발췌문, 주요 키워드, 주제별 기사 수와 읽을 순서를 확인할 수 있습니다. NVIDIA API를 설정하면 새 기사의 주제 분류와 관심사 기반 추천을 사용할 수 있습니다.

## 로컬 실행

Python 3.12를 사용합니다. 아래 명령은 Windows PowerShell에서 저장소 폴더를 기준으로 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m feed.setup_vault
.\.venv\Scripts\python.exe feed_server.py
```

- **독자 화면** [http://127.0.0.1:8765/](http://127.0.0.1:8765/)
- **관리 화면** [http://127.0.0.1:8765/admin](http://127.0.0.1:8765/admin)

기본 벌트는 저장소 폴더 옆의 `NVIDIA Feed Vault`입니다. 위치를 바꾸려면 `.env`의 `OBSIDIAN_VAULT_PATH`를 설정한 뒤 `python -m feed.setup_vault`를 실행하세요. 옵시디언에서 그 폴더를 **보관함 폴더 열기**로 지정하면 기사 노트와 대시보드를 볼 수 있습니다. 초기화 스크립트는 이미 존재하는 노트를 보존합니다.

관리 화면의 **지금 수집** 버튼으로 첫 수집을 실행할 수 있습니다. 서버가 실행 중이면 매일 오전 7시 30분(한국 시간)에 수집합니다. 서버는 로컬 접속용 `127.0.0.1`에 바인딩됩니다.

커피팟 기사를 선택하면 상세 화면 안에 원문이 열립니다. GeekNews는 피드 발췌문을 보여주며, 발행처 페이지는 **원문 새 탭**으로 열 수 있습니다.

## NVIDIA와 피드 설정

- 로컬 `.env`의 `NVIDIA_API_KEY`를 채우면 새 기사 분류와 독자 화면의 관심사 추천이 활성화됩니다. 키 없이도 수집, 기사 열람, 일간 브리핑을 사용할 수 있습니다.
- `config/sources.json`에서 RSS 또는 Atom 출처를 추가할 수 있습니다. 커피팟은 공식 홈의 공개 글 목록을 수집합니다.
- 새 설치에서는 `.runtime/`에 수집·서버 로그와 SQLite 실행 이력이 저장됩니다. 이전 설치의 최상위에 남아 있는 로그와 DB도 계속 읽습니다. 옮기려면 서버를 종료한 뒤 `collector.log`, `feed_server.log`, `feed_server.sqlite3` 및 이름이 같은 SQLite 보조 파일을 함께 `.runtime/`에 넣으세요.
- 개별 명령은 `python -m feed.collect`와 `python -m feed.classify`로 실행할 수 있습니다.

## 구성

| 영역 | 파일 |
| --- | --- |
| 웹 서버 실행과 HTTP 라우팅 | `feed_server.py`, `feed/http.py` |
| 독자·관리 화면의 HTML, CSS, JavaScript | `web/reader/`, `web/admin/` |
| 일일 수집 예약, 실행 이력, 수집·분류 실행 | `feed/jobs.py`, `feed/worker.py` |
| 피드 수집, 출처 파서, 기사 링크 | `feed/collect.py`, `feed/sources.py`, `feed/links.py` |
| 옵시디언 기사 노트 읽기·쓰기, 화면에 제공할 기사 목록 | `feed/vault.py`, `feed/articles.py` |
| 주제 분류, 관심사 추천, 일간 브리핑 | `feed/classify.py`, `feed/recommendations.py`, `feed/briefing.py` |
| 공통 NVIDIA 호출, 주제 목록, 로컬 설정 | `feed/nvidia.py`, `feed/topics.py`, `feed/settings.py` |
| 출처 설정과 분류 평가 기준 | `config/` |
| 벌트 초기화와 대시보드 | `feed/setup_vault.py`, `vault-templates/` |
