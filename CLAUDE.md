# esports-api — 백엔드 (Django + DRF)

> 프로젝트 전체 구성과 결정 사항은 **`../esports-analyzer/docs/PLAN.md`가 기준**이다.
> **ui → api 스펙은 구글 스펙 시트 spec_sheet_lol이 기준** (링크는 PLAN.md 6장). 스펙과 다르게 구현해야 하면 먼저 사용자에게 확인한다. 스펙을 이 파일에 복사하지 않는다.
> 드라마 스토리 예측 버전(작품·회차·예측)은 `drama` 브랜치에만 있다. main 은 LoL 만: 모델은 `matches` 앱, 엔드포인트는 `api/`.

## 이 레포의 역할
데이터 저장과 ui 제공. 경기 정보(op.gg), 세트 영상, analyzer 분석 결과를 저장하고 ui 에 돌려준다.
분석은 analyzer 가 한다. 지금은 analyzer 결과 폴더를 관리 명령으로 읽어 넣는다 (큐 + 워커 연동은 나중).

## 구조
- `api/`: ui 에 주는 엔드포인트. 엔드포인트마다 폴더 하나 (`views.py` + 그 엔드포인트만 쓰는 파일). 앱(`matches`)과 관리 명령은 `api`를 import 하지 않는다
  - 공통: `views.py`(`/health`), `exceptions.py`(에러 형식 `{"error": "메시지"}`, `get_or_404`)
  - `games/` (LoL, `/games`, `/sources`): `views.py` 스펙 1~5번 조회, 8~12번 `POST /games`(영상 등록 + 분석), `/analyze`, `/cancel`, `/estimate`, `GET /sources`, 13번 `POST /games/{id}/lines/{line_id}/review`(대사 검수). 6·7번 `/cases`는 evaluate 단계 후
    - `analyzer.py`: analyzer HTTP 호출 (`MAIN_URL`, 스펙은 `../esports-analyzer/api/*/schemas.py`). `jobs.py`: 작업 시작, 조회할 때 상태 갱신, 끝나면 `matches/outputs.py`로 결과 저장
    - `reviews.py`: 대사 검수(LineReview)를 `/lines`에 붙이고, 번역·예상 때 고친 문장을 analyzer `translate.text_overrides`로 넘긴다
- `matches/` (LoL 앱: 모델·관리 명령)
  - `models.py`: Team, Match(경기, op.gg 번호), MatchGame(세트), GamePlayer(세트별 진영·포지션·선수·챔피언), GameVideo(세트 영상 = 스펙의 games, analyzer 결과 JSON 통째로), LineReview(대사 검수: 고친 문장·O/X. 결과와 따로 둬서 재분석해도 남음, 검수 때 ASR 원문과 지금 원문이 다르면 안 씀)
  - `opgg.py`: op.gg 경기 페이지 안 JSON(`__NEXT_DATA__`)만 읽는다. op.gg 내부 API 는 쓰지 않는다. 세트별 진영·선수·챔피언은 페이지에 없다
  - `outputs.py`: analyzer 결과 폴더 → GameVideo 저장 (`jobs.py`와 `import_outputs`가 같이 씀). `screen.py`: roi_ocr 구간 → 대사 시점 화면 정보 (잡음 구간 제외, 안 바뀌는 값은 가장 오래 뜬 값)
  - 관리 명령: `init_storage`(MinIO 버킷 준비, compose 가 띄울 때 실행), `import_match <op.gg 번호|주소>`, `import_outputs <analyzer 결과 이름> --title --lang --match --set` (화면 OCR 팀·선수 이름으로 세트를 채움)
- `config/`: 설정·`urls.py`, `storage.py`(MinIO/S3, `/health`·재생 주소·`init_storage`가 같이 씀)
- 테스트: 최상위 `tests/` (`test_matches.py`, `test_games.py` …). 실행 `docker compose exec api python manage.py test`

```
cp .env.example .env
docker compose up --build              # ui :8000, api :8002 (sqlite), analyzer :8001, MinIO :9000 (콘솔 :9001)
docker compose exec api python manage.py import_match 32706
docker compose exec api python manage.py import_outputs words_test_1080 --title "..." --lang ko --match 32706 --set 2
```
- DB 는 기본 sqlite (`db.sqlite3`, git 제외). Postgres 는 `COMPOSE_PROFILES`에 `postgres`를 넣고 `DATABASE_URL`을 바꿀 때만
- analyzer 결과 폴더는 `ANALYZER_OUTPUTS`(기본 `../esports-analyzer/outputs`)를 `/outputs`로 읽기 전용 마운트
- analyzer 서비스는 `../esports-analyzer` 이미지·코드를 쓰고, 원본 영상 폴더 `VIDEOS_DIR`을 `/data`로 붙인다 (`GEMINI_API_KEY`는 `../esports-analyzer/.env`)
- `/health`(db·storage 확인), `/api/schema/`, `/api/docs/`

## 규칙 요약
- GET/POST만. 에러는 `{"error": "메시지"}` + 4xx/5xx
- 시간은 원본 영상 기준 초(float), 필드명 `start_sec`/`end_sec`
- 비밀값·주소는 환경변수 (`.env`, git 제외)
- 패키지는 `requirements.txt`에 `==` 고정 후 이미지 재빌드 (로컬 가상환경 안 씀)
- 문서(md)는 `docs/`에, 테스트는 `tests/`에

## 커밋 규칙
- 메시지는 `종류/내용` 한 줄 (`feat/` `refactor/` `fix/` `docs/` `chore/`)
- 작성자는 사용자 본인만. Claude 를 `Co-Authored-By` 등 공동 작성자로 넣지 않는다
