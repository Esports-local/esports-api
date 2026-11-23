# esports-api — 백엔드 (Django + DRF)

> 프로젝트 전체 구성과 결정 사항은 **`../esports-analyzer/docs/PLAN.md`가 기준**이다.
> **ui → api 스펙은 구글 스펙 시트 spec_sheet_lol이 기준** (링크는 PLAN.md 6장). 스펙과 다르게 구현해야 하면 먼저 사용자에게 확인한다. 스펙을 이 파일에 복사하지 않는다.
> 드라마 스토리 예측 버전(작품·회차·예측)은 `drama` 브랜치에만 있다. main 은 LoL 만: 모델은 `matches` 앱, 엔드포인트는 `api/`. (스킬 사용·평가용 `skills` 앱은 별개)

## 스킬 먼저 (esports-dev 플러그인)
아래 작업은 코드를 보거나 명령을 치기 전에 해당 스킬을 먼저 부른다. 이 문서의 구조·명령만 보고 바로 하면 스킬에 적힌 순서와 같이 고칠 곳(스펙 시트, ui·analyzer)을 빠뜨린다.
- 엔드포인트 추가, 응답·요청 모양 변경(필드·계산값·파라미터 추가 포함) → `esports-dev:add-endpoint`
- analyzer 결과 폴더를 DB 에 넣기 (`import_outputs`) → `esports-dev:import-game`
- 로컬 서버 띄우기·끄기·로그 → `esports-dev:local-up`

## 이 레포의 역할
데이터 저장과 ui 제공만 한다. 세트 영상과 analyzer 가 만든 결과(경기 정보 header 포함)를 그대로 저장하고 ui 에 돌려준다.
분석과 외부 데이터(op.gg·Data Dragon) 가져오기는 analyzer 가 한다. api 는 op.gg 를 부르지 않는다. 지금은 analyzer 결과 폴더를 관리 명령으로 읽어 넣는다 (큐 + 워커 연동은 나중).

## 구조
- `api/`: ui 에 주는 엔드포인트. 엔드포인트마다 폴더 하나 (`views.py` + 그 엔드포인트만 쓰는 파일). 앱(`matches`)과 관리 명령은 `api`를 import 하지 않는다
  - 공통: `views.py`(`/health`), `exceptions.py`(에러 형식 `{"error": "메시지"}`, `get_or_404`)
  - `games/` (LoL, `/games`, `/sources`): `views.py` 스펙 1~5번 조회(4번 `/lines`는 대사 + 화면 정보 + 검수, 번역 없음), 8~10·12번 `POST /games`(영상 등록 + 분석), `/analyze`(단계 다시 실행), `/cancel`, `GET /sources`, 13번 `POST /games/{id}/lines/{line_id}/review`(원문 검수). 번역(조건 A/B/C, 11번 `/estimate`)은 뺐다 (analyzer 코드도 지움). 6·7번 `/cases`는 evaluate 단계 후
  - `shorts/` (14~18번 `/games/{id}/events`, `/games/{id}/shorts`, `/games/{id}/shorts/query`, `/shorts/{id}`): `shorts.py` 이벤트: analyzer `shorts` 단계 결과가 있으면 이벤트별 클립(해설 소리 기준 구간, 선수 이름·챔피언, 뒤따르는 리플레이)과 추천 장면(`scenes`), 없으면 timeline 이벤트 앞 6초·뒤 4초. 14번은 거르지 않고 전부 준다(거르기는 ui). 18번 `POST /games/{id}/shorts/query`가 요청 글을 analyzer `POST /shorts/query`로 조건으로 바꾼다(같은 글은 1시간 캐시). 추천 장면은 LLM 순위·제목·자른 구간 포함. 15번은 `{segments, title, event_ids}`(추천 장면·모음, 겹치면 합침, 개수·길이 제한 없음) 또는 예전 `{event_ids}`. 렌더는 위 제목 + 가운데 1180x1080 + 설명 자막(`overlay`: 이벤트로 틀을 채움, `LAYOUT_VERSION`이 key 에 들어가 화면 구성을 바꾸면 다시 렌더), BGM 정보는 `Short.bgm`. 자막의 선수 이름은 `Player` 사전(영어 → 한국어, 대소문자 무시)으로 바꾸고, 바꾼 자막도 key 에 들어가 사전을 고치면 다시 렌더. key = 입력(timeline 버전·구간·제목) 해시라 같은 요청은 같은 행(`Short.key` unique, 다시 렌더 안 함). 렌더는 analyzer `POST /shorts`, 조회할 때 상태를 묻고 끝나면 `/outputs`의 mp4 를 저장소 `shorts/<key>.mp4`(공개 읽기)로 올린다. analyzer 가 기록을 잃으면(404) 다시 맡기고, 실패한 숏폼은 같은 요청으로 다시 렌더
    - `analyzer.py`: analyzer HTTP 호출 (`MAIN_URL`, 스펙은 `../esports-analyzer/api/*/schemas.py`). 2번 `video_url`은 브라우저가 analyzer 에서 원본 영상을 받는 주소 `MAIN_PUBLIC_URL/videos/{video}/file` (`playback_name` 또는 `video_name`, 둘 다 없으면 null). `jobs.py`: 작업 시작, 조회할 때 상태 갱신, 끝나면 `matches/outputs.py`로 결과 저장
    - `reviews.py`: 대사 검수(LineReview)를 `/lines`에 붙인다
  - `skills/` (`/skills`, 스펙 시트 번호 없음): 스킬별 집계, 사용 기록 `/usage`, 평가 결과 `/evals`, 테스트 요청 `/cases`(화면에서 추가, `/cases/{id}`로 정답 바꾸기·빼기 → 이미 돈 결과도 다시 판정), 평가 실행 `/evals/jobs`(`case_ids`로 일부 요청만, 실행기는 `/evals/runner`의 허용이 켜져 있을 때만 가져감), 설명 개선 시도 `/improves`(improve.py 가 보냄, 수정안만 받은 것은 `proposed`), 고칠 방법 `/fixes`(실행기가 진단해 보냄), 실행 요청 `kind`(eval·apply_line·propose·evaluate_try·commit_line), `GET /skills?compare=`로 결과 비교. 보내는 쪽은 `../dev-workflow` (훅, `evals/run.py`, `evals/worker.py`). `/cases/sync`·`/jobs/claim`·`/jobs/{id}/progress`는 실행기 전용
- `skills/` (Claude Code 스킬 사용·선택 평가 앱. 경기 데이터와 무관): `models.py` SkillUsage(스킬 호출, 대화 내용 없음), SkillEvalRun(평가 실행 하나), SkillEvalCase(테스트 요청, 기준은 dev-workflow 의 `evals/cases`), SkillEvalJob(화면에서 요청한 평가 실행), SkillImproveTry(설명 개선 시도 하나), EvalRunner(실행기 연결 시각·평가 실행 허용, 한 줄), SkillFix(틀린 요청의 진단·고칠 방법). `stats.py` 스킬별 집계(재현율·정밀도·성공률)
- `matches/` (LoL 앱: 모델·관리 명령)
  - `models.py`: GameVideo(세트 영상 = 스펙의 games. analyzer 결과 JSON 통째로 `results`, 경기 기본 정보 `header`, op.gg 경기 번호·세트 `opgg_match`·`set_number`), Short(숏폼: key·구간·상태·저장소 key·렌더 시간·시도 횟수), LineReview(대사 원문 검수: 고친 문장·O/X. 결과와 따로 둬서 재분석해도 남음, 검수 때 ASR 원문과 지금 원문이 다르면 안 씀). Team·Match·MatchGame·GamePlayer 는 예전에 api 가 op.gg 로 채우던 표로 이제 쓰지 않는다 (지울지 결정 전)
  - `outputs.py`: analyzer 결과 폴더 → GameVideo 저장, 가공 없음 (`jobs.py`와 `import_outputs`가 같이 씀). `header.json`은 `GameVideo.header`에도 넣고, analyzer 가 op.gg 에서 못 받았으면(error) 이전 헤더를 둔다. 2번 응답의 `match`는 이 헤더를 응답 모양으로 옮긴 것. `screen.py`: roi_ocr 구간 → 대사 시점 화면 정보 (잡음 구간 제외, 안 바뀌는 값은 가장 오래 뜬 값)
  - 영상 등록(`POST /games`)에 `match`·`set`을 주면 저장해 두고 analyzer 작업 맨 앞에 `header` 단계를 넣어 `{"header": {"match", "set"}}`로 넘긴다. 경기·세트를 모르는 영상의 `header` 단계는 뺀다 (`jobs.start`)
  - 관리 명령: `init_storage`(MinIO 버킷 준비, compose 가 띄울 때 실행), `sync_players`(선수 이름 사전 `matches/players_ko.py` → Player 표, 세트 영상 header 선수의 팀을 맞추고 사전에 없는 선수를 출력. compose 가 띄울 때 실행. 사전은 코드로만 고친다, admin 에 없음), `import_outputs <analyzer 결과 이름> --title --lang --match --set --video` (결과 폴더를 그대로 저장, `--match`·`--set`은 기록만, `--video`는 재생할 원본 파일 이름: 구간 분석 폴더(`<영상>_900-1500s`)처럼 이름만으로 원본을 알 수 없을 때 줘야 재생된다. `playback_name`에 넣어 재생·숏폼 렌더에만 쓰고, 재분석 대상 `video_name`은 안 바꾼다 (바꾸면 "분석 다시 실행"이 원본 전체를 분석한다))
- `config/`: 설정·`urls.py`, `storage.py`(MinIO/S3, `/health`·재생 주소·`init_storage`가 같이 씀)
- 테스트: 최상위 `tests/` (`test_matches.py`, `test_games.py` …). 실행 `docker compose exec api python manage.py test`
- CI: `.github/workflows/ci.yml` (푸시·PR 마다 `check`, 마이그레이션 누락 확인, 테스트. 서비스 없이 sqlite)

```
cp .env.example .env
docker compose up --build              # ui :8000, api :8002 (sqlite), analyzer :8001, MinIO :9000 (콘솔 :9001)
docker compose exec api python manage.py import_outputs words_test_1080 --title "..." --lang ko --match 32706 --set 2
```
- DB 는 기본 sqlite (`db.sqlite3`, git 제외). 쓰기 요청이 겹치면 기다리도록 `transaction_mode=IMMEDIATE`. Postgres 는 `COMPOSE_PROFILES`에 `postgres`를 넣고 `DATABASE_URL`을 바꿀 때만
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
