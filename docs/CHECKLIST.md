# 작업 체크리스트

확정 스펙은 구글 스펙 시트 기준 (링크는 `../PLAN.md` 5장). 시트에 없는 호출은 PLAN.md 5장 초안 참고.

## 완료
- [x] docker-compose: api + Postgres 17 + MinIO (`COMPOSE_PROFILES=minio`일 때만 MinIO), 볼륨으로 데이터 유지
- [x] 환경변수: `DATABASE_URL`, `S3_*`, `MAIN_URL`, `API_URL`, `TMDB_*`, `PREDICT_BACKEND`, `VIDEOS_DIR` (`.env.example`)
- [x] MinIO: `vod` 버킷, `hls/` 공개 읽기 정책 (`init_storage`), boto3 타임아웃, 실패해도 서버 기동
- [x] 모델: Series, Episode, Character, Prediction
- [x] 엔드포인트 8개: `GET /series`, `GET /series/{id}`, `POST·GET /series/{id}/predict`, `GET /episodes/{id}`, `GET /episodes/{id}/analysis`, `GET·POST /episodes/{id}/reviews` + `GET /health`
- [x] 대사 검수(ui 회차 검수 화면용): LineReview 모델, 판정 ok·wrong·fixed·clear
- [x] 에러 응답 `{"error": "메시지"}` 통일, 한국어 메시지
- [x] 예측 mock (`PREDICT_BACKEND=mock`), 모르는 백엔드는 failed
- [x] Swagger `/api/docs/`, 스키마 검증 통과
- [x] 테스트 22개 (`tests/`, 스펙 시트 탭별)
- [x] `seed_demo` 데모 작품 (12화, 1~10화 분석 완료)
- [x] 데모 1화에 esports-analyzer `tts_drama` HLS 연결 → 실제 재생 확인 (master → index → ts, CORS)
- [x] 코드리뷰 1~9번 수정
- [x] TMDB API 키 설정·인증 확인

## 실영상이 오면
- [ ] `manage.py add_videos --series <id> /videos/*.mp4`: 파일명에서 회차 번호 → MinIO `raw/` 업로드 → 회차 연결 (이미 있으면 건너뜀)
- [ ] `manage.py import_analysis --episode <id> <main outputs 폴더>`: `hls/`, `analysis/episode.json` → MinIO, Episode에 `hls_key`·`duration`·`analysis`·`analyze_status=done`
  - 다시 분석한 회차면 그 회차의 대사 검수(LineReview)를 지운다 (대사 순서가 바뀌므로)
- [ ] 실제 영상 한 편으로 영상 → main(CLI) → import → 재생·예측 근거까지 한 바퀴 확인
- [ ] 디스크 용량 확인 (1시간 회차당 원본 1~3GB + HLS 1~2GB). 원본은 구글 드라이브에 두고 `raw/` 정리 여부 결정

## 스펙 추가 (시트에 먼저 적고 확인받은 뒤 구현)
- [ ] 분석: `POST·GET /episodes/{id}/analyze` (시작, 진행 상태)
- [ ] 장면: `GET /episodes/{id}/scenes` — 지금은 6번 `analysis` 원본으로 충분. 인물 id를 붙인 가공 응답이 필요해지면 추가
- [ ] 화자 매핑: `GET·POST /episodes/{id}/speakers` + SpeakerMap 모델
- [ ] 얼굴 매핑: `GET·POST /episodes/{id}/faces` + FaceMap 모델
- [ ] 아이디어: `POST·GET /series/{id}/ideas` + Idea 모델
- [ ] 회차 문서: `GET /episodes/{id}/document` (LLM 입력 header + body, 디버그용)

## 검수
- [ ] ui `web/api_client.py`의 `get_analysis`, `get_line_reviews`, `save_line_review`를 6~8번 호출로 교체 (esports-ui)
- [ ] 검수 결과 활용: 고친 대사(fixed)를 예측 입력(회차 문서)에 반영할지 결정
- [ ] 장면 단위 검수(지문·유형·장면 경계)가 필요한지 결정

## 데이터 수집
- [ ] 작품 정보 넣는 방법 결정: 관리자 화면 직접 입력 / JSON fixture / TMDB `crawl`
- [ ] (crawl 하면) `manage.py crawl <TMDB id>`: 작품·회차·등장인물·배우 사진, `tmdb_id` 기준 갱신
- [ ] 관리자 계정: `createsuperuser`

## main 연동 (main `app/` 스펙 확정 후)
- [ ] api → main `POST /jobs` (`job_id`, `episode_id`, `video_uri`, `stages`, `callback_url`)
- [ ] main → api callback 받는 주소, 상태 변환 (`succeeded→done`, `cancelled→failed`)
- [ ] callback 받으면 `import_analysis`와 같은 처리 자동 실행
- [ ] 워크스테이션 분리 시 주소 설정 (`MAIN_URL`, `API_URL`, main의 `S3_ENDPOINT_URL`)

## 예측 (LLM)
- [ ] 모델 결정 (Gemini Flash 계열), API 키 환경변수
- [ ] 1차 호출(header만) → body 장면 선별 → 2차 호출(예측 + 근거 장면)
- [ ] 근거 장면 검증 (2차에 넘긴 장면 중 하나인지)
- [ ] 비동기 실행 (요청 → queued → running → done/failed)
- [ ] 개발 중 호출 수 줄이기 (결과 저장 재사용, mock 유지)

## ui (esports-ui, 관리자 페이지 형식)
- [ ] 작품 목록 → 작품 상세(회차·등장인물 표) → 회차 상세(hls.js 재생) → 예측 폼 → 결과 표(근거 누르면 영상 이동)

## 정리
- [ ] `feat/infra-settings` 브랜치 main 병합 / 원격 저장소 푸시
- [ ] 스펙 시트 공유 설정 "제한됨"으로 되돌리기
- [ ] 외부 배포 시: `DEBUG` 기본값 끄기, 비밀키·MinIO 키 기본값 제거, `/health` 에러 상세 숨기기
