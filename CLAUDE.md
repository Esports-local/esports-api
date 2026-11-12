# esports-api — 백엔드 (Django + DRF)

> 프로젝트 전체 구성과 결정 사항은 **`../esports-analyzer/docs/PLAN.md`가 기준**이다.
> **ui → api 스펙은 구글 스펙 시트 spec_sheet_lol이 기준** (링크는 PLAN.md 6장). 스펙과 다르게 구현해야 하면 먼저 사용자에게 확인한다. 스펙을 이 파일에 복사하지 않는다.
> 드라마 스토리 예측 버전(작품·회차·예측)은 `drama` 브랜치에 있다. main 에도 `vod` 앱이 남아 있지만 새 기능은 `matches` 앱에 만든다.

## 이 레포의 역할
데이터 저장과 ui 제공. 경기 정보(op.gg), 세트 영상, analyzer 분석 결과를 저장하고 ui 에 돌려준다.
분석은 analyzer 가 한다. 지금은 analyzer 결과 폴더를 관리 명령으로 읽어 넣는다 (큐 + 워커 연동은 나중).

## 구조
- `matches/` (LoL)
  - `models.py`: Team, Match(경기, op.gg 번호), MatchGame(세트), GamePlayer(세트별 진영·포지션·선수·챔피언), GameVideo(세트 영상 = 스펙의 games, analyzer 결과 JSON 통째로)
  - `opgg.py`: op.gg 경기 페이지 안 JSON(`__NEXT_DATA__`)만 읽는다. op.gg 내부 API 는 쓰지 않는다. 세트별 진영·선수·챔피언은 페이지에 없다
  - `screen.py`: roi_ocr 구간 → 대사 시점 화면 정보 (잡음 구간 제외, 안 바뀌는 값은 가장 오래 뜬 값)
  - `views.py`: 스펙 1~5번 `/games`, `/games/{id}`, `/games/{id}/screen`, `/games/{id}/lines`, `/games/{id}/analysis`. 6·7번 `/cases`는 evaluate 단계 후
  - 관리 명령: `import_match <op.gg 번호|주소>`, `import_outputs <analyzer 결과 이름> --title --lang --match --set` (화면 OCR 팀·선수 이름으로 세트를 채움)
- `vod/`: 드라마 버전 (`/series`, `/episodes`). 에러 형식(`vod/exceptions.py`, `{"error": "메시지"}`)과 `/health`는 공통으로 쓴다
- 테스트: 최상위 `tests/` (`test_matches.py`, `test_games.py` …). 실행 `docker compose exec api python manage.py test`

```
cp .env.example .env
docker compose up --build              # api :8000 (sqlite), MinIO :9000 (콘솔 :9001)
docker compose exec api python manage.py import_match 32706
docker compose exec api python manage.py import_outputs words_test_1080 --title "..." --lang ko --match 32706 --set 2
```
- DB 는 기본 sqlite (`db.sqlite3`, git 제외). Postgres 는 `COMPOSE_PROFILES`에 `postgres`를 넣고 `DATABASE_URL`을 바꿀 때만
- analyzer 결과 폴더는 `ANALYZER_OUTPUTS`(기본 `../esports-analyzer/outputs`)를 `/outputs`로 읽기 전용 마운트
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
