# 겟슝 웹버전 (셀프호스트 · 소규모용)

브라우저에서 유튜브 URL을 넣으면 **서버가 받아 mp4로 변환해** 내려주는 웹 앱.
데스크톱 앱과 달리 설치 없이 링크만 공유하면 지인도 바로 쓸 수 있어요.

> ⚠️ **사용 범위 주의**: 나/지인 소규모용입니다. 불특정 다수 공개 서비스는
> 유튜브 약관·저작권·호스팅 약관 위반 및 서버/도메인 차단 위험이 있어요.
> 반드시 **접근 코드(ACCESS_CODE)**를 설정해 아는 사람만 쓰게 하세요.

## 구성
| 파일 | 설명 |
|---|---|
| `server.py` | Flask 서버 (yt-dlp + ffmpeg, 접근코드·동시제한·자동정리) |
| `index.html` | 다운로드 UI (라이트 테마) |
| `Dockerfile` | 컨테이너 이미지 (ffmpeg 포함) |
| `fly.toml` | Fly.io 배포 설정 |
| `requirements.txt` | 파이썬 의존성 |

## 환경변수
| 변수 | 기본값 | 설명 |
|---|---|---|
| `ACCESS_CODE` | (없음) | **꼭 설정 권장.** 이 코드가 있어야 사용 가능(지인 공유용) |
| `MAX_CONCURRENT` | `2` | 동시 다운로드 수 |
| `MAX_DURATION_SEC` | `10800` | 허용 최대 영상 길이(초, 기본 3시간) |
| `FILE_TTL_SEC` | `1800` | 받은 파일 보관 시간(초, 기본 30분) |
| `PORT` | `8080` | 포트 |

---

## 배포 방법

### 옵션 1) Fly.io (추천 · 소규모 무료 티어)
```bash
# 1) flyctl 설치: https://fly.io/docs/hractl/install/
brew install flyctl
fly auth signup   # 또는 fly auth login

cd getshoong-web
fly launch --no-deploy         # 앱 이름/지역 정하기 (fly.toml 생성/갱신)
fly secrets set ACCESS_CODE=원하는비밀코드   # 지인 공유용 코드
fly deploy

fly open        # 브라우저로 열기 → 나온 URL을 지인에게 공유
```
`auto_stop_machines`가 켜져 있어 안 쓸 땐 0대로 내려가 비용이 거의 안 나와요.

### 옵션 2) Railway
```bash
# railway.app 에서 New Project → Deploy from Repo(또는 Dockerfile)
# Variables 에 ACCESS_CODE 추가 후 배포. 도메인 생성하면 그 URL 공유.
```

### 옵션 3) 직접 서버 / 내 PC (Docker)
```bash
cd getshoong-web
docker build -t getshoong-web .
docker run -d --name getshoong -p 8080:8080 \
  -e ACCESS_CODE=원하는비밀코드 \
  getshoong-web
# http://서버IP:8080  (외부 공유하려면 방화벽/포트포워딩 또는 cloudflared 터널)
```
집 PC로 임시 공유는 `cloudflared tunnel --url http://localhost:8080` 가 편해요.

### 로컬에서 그냥 실행 (도커 없이, 테스트용)
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# ffmpeg 필요: brew install ffmpeg
ACCESS_CODE=test python server.py
# http://localhost:8080
```

## 동작
1. 접근 코드가 설정돼 있으면 첫 사용 시 코드 입력(브라우저에 저장됨)
2. 유튜브 URL 붙여넣기 → 정보 가져오기 → 화질 선택 → 다운로드
3. 서버가 변환한 mp4를 브라우저로 내려줌 (파일은 30분 뒤 서버에서 자동 삭제)

## 비용/부하 관리 팁
- `MAX_CONCURRENT`를 낮게(1~2) 유지
- `ACCESS_CODE` 필수 — 없으면 아무나 서버 자원을 쓸 수 있음
- Fly.io는 `min_machines_running=0`이라 유휴 시 정지 → 비용 최소
