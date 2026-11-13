# esports-api

LoL 중계 번역 실험의 백엔드 (Django + DRF). 경기 정보(op.gg), 세트 영상, 분석 결과(ASR·화면 OCR·번역)를 저장하고 화면에 제공한다.

- 계획·실험 조건: [esports-analyzer/docs/PLAN.md](https://github.com/Esports-local/esports-analyzer/blob/main/docs/PLAN.md)
- 함께 쓰는 레포: [esports-analyzer](https://github.com/Esports-local/esports-analyzer) (분석) · [esports-ui](https://github.com/Esports-local/esports-ui) (화면)

## 엔드포인트
| No | 메서드 | 경로 | 설명 |
|---|---|---|---|
| 1 | GET | `/games` | 세트 영상 목록 |
| 2 | GET | `/games/{id}` | 세트 상세, 단계별 상태, 경기 정보(진영·포지션별 선수) |
| 3 | GET | `/games/{id}/screen?tag=&min_samples=` | 화면 OCR 구간 |
| 4 | GET | `/games/{id}/lines?from_sec=&to_sec=` | 해설 대사 + 그 시점 화면 정보 + 조건별 번역 + 검수 상태(`review`) |
| 5 | GET | `/games/{id}/analysis?stage=` | 단계 결과 원본 |
| 8 | POST | `/games` | 원본 영상(1920x1080) 등록 + 분석 시작 |
| 9 | POST | `/games/{id}/analyze` | 단계 추가 실행 (예: 번역) |
| 10 | POST | `/games/{id}/cancel` | 분석 중지 |
| 11 | GET | `/games/{id}/estimate?conditions=A,B` | 번역 예상 입력 토큰 |
| 12 | GET | `/sources` | 원본 영상 목록 (`VIDEOS_DIR`) |
| 13 | POST | `/games/{id}/lines/{line_id}/review` | 대사 검수: `text`(고친 문장)·`reviewed`(O/X) 중 하나 이상. 고친 문장은 번역·예상 비용 계산 때 ASR 원문 대신 쓴다 |

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
docker compose exec api python manage.py import_match 32706          # op.gg 경기 번호
docker compose exec api python manage.py import_outputs <결과 이름> --title "..." --lang ko --match 32706 --set 2
docker compose exec api python manage.py test
```
- `import_match`: op.gg 경기 페이지 안의 JSON만 읽어 경기·팀·세트를 저장한다 (같은 번호는 덮어씀)
- `import_outputs`: analyzer 결과 폴더(`ANALYZER_OUTPUTS`, 기본 `../esports-analyzer/outputs`)를 읽어 세트 영상으로 저장하고, 화면 OCR로 읽은 팀·선수 이름을 세트에 채운다

## 구조
| 폴더 | 내용 |
|---|---|
| `api/` | 엔드포인트. 엔드포인트마다 폴더 하나 (`views.py` + 그 엔드포인트만 쓰는 파일) |
| `api/games/` | `/games`, `/sources` (`analyzer.py` analyzer 호출, `jobs.py` 작업 시작·상태 갱신, `reviews.py` 대사 검수) |
| `api/` 공통 | `views.py`(`/health`), `exceptions.py`(에러 형식) |
| `matches/` | LoL 모델, `opgg.py`, `outputs.py`(analyzer 결과 저장), `screen.py`, 관리 명령 |
| `config/` | 설정, `urls.py`, `storage.py`(MinIO/S3) |

## 테이블 (`matches` 앱)
| 테이블 | 내용 |
|---|---|
| Team | 팀 (op.gg id, 이름, 약칭) |
| Match | 경기 (op.gg 번호, 대회·단계, 시작 시각, 스코어, 승리 팀, 패치) |
| MatchGame | 세트 (번호, op.gg 세트 id, 영상 링크, 블루·레드 팀) |
| GamePlayer | 세트별 진영·포지션·선수·챔피언 |
| GameVideo | 세트 영상 하나 (해설 언어별), analyzer 결과 JSON |
| LineReview | 대사 하나의 사람 검수 (고친 문장, O/X, 검수 당시 ASR 원문). 분석 결과와 따로 두어 다시 분석해도 남고, ASR 원문이 바뀌면 그 검수는 쓰지 않는다 |

이전 주제(드라마 스토리 예측) 코드는 `drama` 브랜치에 있다.
