# esports-api

LoL 중계 분석 → 숏폼의 백엔드 (Django + DRF). 세트 영상과 analyzer 분석 결과(경기 정보·화면 OCR·받아쓰기·장면 전환·이벤트)를 저장하고 화면에 제공한다. 분석과 op.gg 호출은 analyzer 가 한다.

- 계획·실험 조건: [esports-analyzer/docs/PLAN.md](https://github.com/Esports-local/esports-analyzer/blob/main/docs/PLAN.md)
- 함께 쓰는 레포: [esports-analyzer](https://github.com/Esports-local/esports-analyzer) (분석) · [esports-ui](https://github.com/Esports-local/esports-ui) (화면)

## 엔드포인트
| No | 메서드 | 경로 | 설명 |
|---|---|---|---|
| 1 | GET | `/games` | 세트 영상 목록 |
| 2 | GET | `/games/{id}` | 세트 상세, 단계별 상태, 경기 정보(진영·포지션별 선수), 원본 영상 재생 주소 `video_url`(analyzer `/videos/{name}/file`) |
| 3 | GET | `/games/{id}/screen?tag=&min_samples=` | 화면 OCR 구간 |
| 4 | GET | `/games/{id}/lines?from_sec=&to_sec=` | 해설 대사 + 그 시점 화면 정보 + 검수 상태(`review`) |
| 5 | GET | `/games/{id}/analysis?stage=` | 단계 결과 원본 |
| 8 | POST | `/games` | 원본 영상(1920x1080) 등록 + 분석 시작 |
| 9 | POST | `/games/{id}/analyze` | 단계 다시 실행 |
| 10 | POST | `/games/{id}/cancel` | 분석 중지 |
| 12 | GET | `/sources` | 원본 영상 목록 (`VIDEOS_DIR`) |
| 13 | POST | `/games/{id}/lines/{line_id}/review` | 대사 검수: `text`(고친 문장)·`reviewed`(O/X) 중 하나 이상 |
| 14 | GET | `/games/{id}/events` | 경기 이벤트(킬·타워·오브젝트) 전부 + 이벤트마다 숏폼 구간 `clip`(analyzer shorts 단계: 해설 소리 기준, 없으면 앞 6초·뒤 4초), 선수(`killer`·`victims`·`assists`: 슬롯·이름·챔피언), `replay`(뒤따르는 리플레이), 추천 장면 `scenes`(LLM 순위 `rank`·제목 `title`·`titles`·`reason`·자른 구간 `clip`·`source`·`warnings`, 순위순). 조건으로 거르기는 ui 가 한다 |
| 15 | POST | `/games/{id}/shorts` | 숏폼 만들기 `{segments: [{start_sec, end_sec}], title, event_ids?}` (추천 장면·모음, 개수·길이 제한 없음) 또는 `{event_ids, pre_sec, post_sec}`. 화면은 위 제목 + 가운데 중계 화면 1180x1080 + 설명 자막(+ BGM). 같은 입력이면 기존 숏폼(200), 실패한 것은 다시 렌더. 응답(15·17번)에 `title`. 영상 위 제목("2026 LCK 결승 1세트" + title)과 설명 자막("Kanavi, Ruler 잡고 / 킬 GEN 3 : 4 HLE")은 고른 이벤트로 api 가 만들어 analyzer 에 넘긴다 |
| 16 | GET | `/games/{id}/shorts` | 세트의 숏폼 목록 (최근순) |
| 17 | GET | `/shorts/{id}` | 숏폼 상태·재생 주소·렌더 시간. 끝나지 않았으면 analyzer 상태로 갱신. `bgm`: 깐 BGM {title, source, license, attribution} |
| 18 | POST | `/games/{id}/shorts/query` | 모음 숏폼 요청 글 `{text}` → 조건 `{text, filter: {killer, type, team, tag}, title, note, error}` (analyzer LLM, 같은 글은 1시간 저장, 실패하면 error 만) |

### 스킬 사용 · 선택 평가 (`/skills`)
Claude Code 플러그인 `esports-dev`([dev-workflow](https://github.com/Esports-local/dev-workflow))의 스킬이 얼마나 쓰이고 제대로 골라지는지 저장한다. 경기 데이터와는 무관하다. 스펙 시트 번호는 아직 없다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/skills?batch=&days=` | 스킬별 집계: 사용(호출·성공률·시간·토큰) + 선택 평가(재현율·정밀도), 결과 이름 목록, 진행 중인 평가 |
| POST | `/skills/usage` | 사용 기록 저장 (dev-workflow 훅이 보냄). 대화 내용은 받지 않는다 |
| GET | `/skills/evals?batch=&skill=&only=` | 평가 요청별 결과 (기본: 틀린 요청만) |
| POST | `/skills/evals` | 평가 실행 기록 저장 (`evals/run.py`가 보냄) |
| GET · POST | `/skills/cases` | 테스트 요청 목록, 화면에서 추가 |
| POST | `/skills/cases/{id}` | 테스트 요청 정답 바꾸기·빼기 (이미 돈 결과도 다시 판정) |
| GET · POST | `/skills/evals/jobs` | 평가 실행 목록, 실행 요청 (한 번에 하나) |
| GET · POST | `/skills/evals/runner` | 실행기 연결 상태, 평가 실행 허용 켜기·끄기 |
| GET · POST | `/skills/improves` | 설명 자동 개선 시도 기록 (`evals/improve.py`가 보냄) |
| GET · POST | `/skills/fixes` | 틀린 요청의 진단·고칠 방법 (실행기가 보냄) |
| POST | `/skills/evals/jobs/{id}/cancel` | 평가 실행 중지 |
| POST | `/skills/cases/sync`, `/skills/evals/jobs/claim`, `/skills/evals/jobs/{id}/progress` | 맥에서 도는 실행기(`evals/worker.py`) 전용 |

이 밖에 `GET /health`(db·저장소 확인). 에러는 `{"error": "메시지"}`. OpenAPI: http://localhost:8002/api/docs/

## 실행
| 서비스 | 주소 |
|---|---|
| ui (화면) | http://localhost:8000 |
| api | http://localhost:8002 (컨테이너끼리는 `http://api:8000`) |
| analyzer | http://localhost:8001 |
| MinIO | http://localhost:9000 (콘솔 :9001) |

```
cp .env.example .env
docker compose up --build                       # ui :8000 + api :8002 (기본 sqlite) + analyzer :8001 + MinIO
docker compose exec api python manage.py import_outputs <결과 이름> --title "..." --lang ko --match 32706 --set 2
docker compose exec api python manage.py import_outputs lck_final_1080_900-1500s --match 32655 --set 1 --video lck_final_1080.mp4  # 구간 분석 폴더
docker compose exec api python manage.py test
```
- `import_outputs`: analyzer 결과 폴더(`ANALYZER_OUTPUTS`, 기본 `../esports-analyzer/outputs`)를 읽어 세트 영상으로 그대로 저장한다. 경기 정보는 analyzer `header` 단계 결과(`work/header.json`)에서 온다 (api 는 op.gg 를 부르지 않음). `--video`는 재생·숏폼에 쓸 원본 파일 이름으로, 폴더 이름만으로 원본을 알 수 없을 때(구간 분석) 준다
- 브라우저가 analyzer 에 닿는 주소는 `MAIN_PUBLIC_URL`(기본 `http://localhost:8001`)이다 (`video_url`). compose 안 주소 `MAIN_URL`과 다르다

## 구조
| 폴더 | 내용 |
|---|---|
| `api/` | 엔드포인트. 엔드포인트마다 폴더 하나 (`views.py` + 그 엔드포인트만 쓰는 파일) |
| `api/games/` | `/games`, `/sources` (`analyzer.py` analyzer 호출·`video_url`, `jobs.py` 작업 시작·상태 갱신, `reviews.py` 대사 검수) |
| `api/shorts/` | `/games/{id}/events`, `/games/{id}/shorts`, `/shorts/{id}` (`shorts.py` 이벤트 → 구간, analyzer 렌더 맡기기, MinIO 업로드) |
| `api/skills/` | `/skills` (스킬 사용 기록, 선택 평가 결과, 테스트 요청, 평가 실행 요청, 개선 시도, 고칠 방법) |
| `api/` 공통 | `views.py`(`/health`), `exceptions.py`(에러 형식) |
| `matches/` | LoL 모델, `outputs.py`(analyzer 결과 저장), `screen.py`(대사 시점 화면 정보), 관리 명령 |
| `skills/` | 스킬 사용 · 평가 모델, `stats.py`(스킬별 집계) |
| `config/` | 설정, `urls.py`, `storage.py`(MinIO/S3) |

## 테이블 (`matches` 앱)
| 테이블 | 내용 |
|---|---|
| GameVideo | 세트 영상 하나 (해설 언어별): analyzer 결과 JSON, 경기 정보(header), op.gg 경기 번호·세트, 원본 파일 이름(분석 대상 `video_name`, 재생·숏폼용 `playback_name`) |
| Short | 숏폼 하나: key(입력 해시), 이벤트·구간, 상태, 저장소 key, 렌더 시간, 시도 횟수 |
| Player | 선수 이름 사전: 영어 이름(op.gg) → 한국어 표기 (Faker → 페이커). 숏폼 자막을 만들 때 바꿔 씀. 내용은 코드 `matches/players_ko.py`가 기준이고 `sync_players`(api 컨테이너를 띄울 때 자동)가 넣음. 새 선수는 그 파일에 한 줄 추가 |
| LineReview | 대사 하나의 사람 검수 (고친 문장, O/X, 검수 당시 ASR 원문). 분석 결과와 따로 두어 다시 분석해도 남고, ASR 원문이 바뀌면 그 검수는 쓰지 않는다 |
| Team · Match · MatchGame · GamePlayer | 예전에 api 가 op.gg 로 채우던 표. 지금은 쓰지 않는다 (지울지 결정 전) |

## 테이블 (`skills` 앱)
| 테이블 | 내용 |
|---|---|
| SkillUsage | 스킬 호출 하나 (스킬 이름, 부른 폴더, 성공 여부, 걸린 시간, 토큰, 도구 호출·오류 수, 시각) |
| SkillEvalRun | 선택 평가 실행 하나 (결과 이름, 테스트 요청, 기대 스킬, 고른 스킬, 판정) |
| SkillEvalCase | 테스트 요청. 기준은 dev-workflow 의 `evals/cases/*.jsonl`이고 실행기가 맞춘다 |
| SkillEvalJob | 화면에서 요청한 평가 실행 (대기 → 실행 → 완료 · 실패 · 중지) |
| SkillImproveTry | 설명 자동 개선 시도 하나 (원인 종류, 가설, 새 설명, 채택·기각, 고쳐진·깨진 요청) |
| EvalRunner | 실행기 연결 시각과 평가 실행 허용 (한 줄) |
| SkillFix | 틀린 요청의 진단과 고칠 방법 |

이전 주제(드라마 스토리 예측) 코드는 `drama` 브랜치에 있다.
