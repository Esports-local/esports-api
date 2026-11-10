# test_api — 백엔드 (Django + DRF)

> 프로젝트 전체 구성, 결정 사항, 저장소 구조, **API 스펙은 `../PLAN.md`가 기준**이다.
> 작업 전에 반드시 읽고, 스펙과 다르게 구현해야 하면 먼저 사용자에게 확인한다. 스펙을 이 파일에 복사하지 않는다.

## 이 레포의 역할
데이터의 단일 소유자. 작품/회차/등장인물/분석 상태/타임라인/화자 매핑/예측/아이디어를 저장하고 ui에 제공한다.
분석·예측은 main에 위임하고 callback으로 결과를 받는다 (main 연동 스펙은 아직 미정).

## 현재 상태
`config/` Django 프로젝트만 생성됨 (startproject). `requirements.txt`: django, djangorestframework, drf-spectacular, requests.
settings의 SECRET_KEY/DEBUG/ALLOWED_HOSTS는 환경변수(`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`)로 받음.
```
docker build -t vod-api .
docker run --rm -p 8000:8000 -v "$PWD":/app vod-api   # -v: 코드 수정 시 자동 reload
docker run --rm -v "$PWD":/app vod-api python manage.py migrate   # manage.py 명령
```

## 작업 순서
1. `docker-compose.yml`: api + Postgres + MinIO (볼륨으로 데이터 유지), `.env.example`
2. settings: DRF, drf-spectacular, `DATABASE_URL`, `S3_*`, `MAIN_URL` 환경변수
3. 모델: Series, Episode, Character, Segment, Dialogue, Speaker(회차별 S1→Character), Prediction, Idea
   - 분석 상태는 Episode에 (`analyze_status`), 예측·아이디어는 (Series, `target`) 단위로 저장
   - 미확정 분석 결과는 `JSONField` + `schema_version`
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
