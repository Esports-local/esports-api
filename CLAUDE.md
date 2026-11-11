# test_api — 백엔드 (Django + DRF)

> 프로젝트 전체 구성, 결정 사항, 저장소 구조, **API 스펙은 `../PLAN.md`가 기준**이다.
> 작업 전에 반드시 읽고, 스펙과 다르게 구현해야 하면 먼저 사용자에게 확인한다. 스펙을 이 파일에 복사하지 않는다.

## 이 레포의 역할
데이터의 단일 소유자. 작품/회차/등장인물/분석 상태/타임라인/화자 매핑/예측/아이디어를 저장하고 ui에 제공한다.
분석은 main에 위임하고 callback으로 결과를 받는다 (main 연동 스펙은 초안, PLAN.md 5장 11절). 예측·아이디어는 api가 LLM으로 직접 한다.

## 현재 상태
작업 순서 1·2 완료. `config/`(settings), `vod/` 앱 (모델 없음, `GET /health`, `storage.py`, `init_storage` 명령).
환경변수는 `.env.example` 참고 (`DJANGO_*`, `DATABASE_URL`, `S3_*`, `MAIN_URL`, `API_URL`). `DATABASE_URL`이 없으면 sqlite.
- MinIO 이미지: 공식 `minio/minio`는 배포 중단 → `chainguard/minio`를 digest로 고정. `mc`가 없어 버킷은 `init_storage`(boto3)로 만든다
- 컴퓨터마다 `.env`만 다르게 둔다. `COMPOSE_PROFILES=minio`면 MinIO를 이 컴퓨터에서 띄우고, 비우면 `S3_*`가 가리키는 외부 저장소 사용 (PLAN.md 3장)
- presigned URL은 `S3_PUBLIC_ENDPOINT_URL`(브라우저 주소)로 서명한다. 서명에 host가 들어가므로 내부 주소와 따로 둔다
```
cp .env.example .env
docker compose up --build              # api :8000, Postgres :5432, MinIO :9000 (콘솔 :9001)
docker compose exec api python manage.py <명령>
docker compose down -v                 # 데이터(볼륨)까지 삭제
```
- `/health`(db·storage 확인), `/api/schema/`, `/api/docs/`

## 작업 순서
1. `docker-compose.yml`: api + Postgres + MinIO (볼륨으로 데이터 유지), `.env.example`
2. settings: DRF, drf-spectacular, `DATABASE_URL`, `S3_*`, `MAIN_URL` 환경변수
3. 모델: Series, Episode, Character, SpeakerMap(회차별 S1→Character), FaceMap(회차별 F1→Character), Prediction, Idea
   - 용어·필드는 main(`../test_main/pipeline/schema.py`)에 맞춤: scene / line / `start_sec`·`end_sec`
   - 분석 상태는 Episode에 (`analyze_status`), 예측·아이디어는 (Series, `target`) 단위로 저장
   - main `episode.json`(scenes·speakers·faces)은 Episode에 `JSONField` + `schema_version`으로 통째로 저장
   - 예측·아이디어는 main이 아니라 api가 LLM으로 직접 수행
4. PLAN.md 5장 엔드포인트를 목업 응답으로 먼저 구현 → ui 병행 개발 가능하게
   - 작품·회차·등장인물은 크롤링 관리 명령(`manage.py crawl`)으로 채우고 API는 조회만 (PLAN.md 4장)
5. MinIO 연동 (업로드, presigned 재생 URL)
6. main 연동 (스펙 확정 후)
7. OpenAPI 스키마 (`/api/schema/`)

## 규칙 요약 (상세는 PLAN.md)
- GET/POST만. 회차 동작은 `/episodes/{id}/analyze`처럼 POST 시작 + 같은 경로 GET 조회
- 시간은 초 단위 float, 장면 참조는 `{segment_id, start, end}`
- 비밀값·주소는 환경변수, 각 서비스 `GET /health`
- 패키지는 `requirements.txt`에 `==` 고정 후 이미지 재빌드 (로컬 가상환경 안 씀)
