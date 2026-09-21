# 자동매매 트레이더 v0.1

토스증권 Open API, FastAPI, PostgreSQL을 사용하는 **모의 자동매매** 프로젝트입니다.

> 안전 원칙: `LIVE_TRADING=false`가 기본값입니다. v0.1에서는 어떤 상황에서도 실제 주문 API를 호출하지 않습니다.

## 현재 단계

5단계까지 완료했습니다. FastAPI 앱, PostgreSQL 연결, 기본 거래 테이블, 토스증권 OAuth 인증, 현재가 조회를 제공합니다.

## 준비 사항

- Python 3.11 이상
- PostgreSQL 16 이상 (다음 DB 연결 단계에서 사용)
- 토스증권 Open API Client ID / Client Secret (인증 단계에서 입력)

## 폴더 구조

```text
trading-bot/
├─ app/
│  ├─ api/
│  ├─ toss/
│  ├─ strategy/
│  ├─ trader/
│  └─ database/
├─ .env
├─ .gitignore
├─ requirements.txt
└─ README.md
```

## 환경 변수

`.env` 파일은 Git에서 제외됩니다. 데이터베이스 연결값을 저장하며, 토스증권 인증 단계에서 Client ID와 Secret을 입력합니다.

## PostgreSQL 테이블

FastAPI가 처음 실행될 때 다음 테이블이 자동으로 생성됩니다.

- `stocks`: 종목 기본 정보
- `prices`: 조회한 현재가 이력
- `orders`: 모의 주문 요청
- `trade_records`: 체결·거래 기록

## 토스증권 인증

`TOSS_CLIENT_ID`와 `TOSS_CLIENT_SECRET`은 `.env`에만 저장합니다. `POST /auth/verify`는 OAuth 2.0 Client Credentials 방식으로 토큰을 발급받아 인증 여부만 반환하며, 액세스 토큰은 응답·로그·DB에 저장하지 않습니다.

토큰은 프로세스 메모리에서 만료 60초 전까지만 재사용합니다. 토스증권은 클라이언트당 최신 토큰 한 개만 유효하므로, 여러 프로그램에서 같은 Client ID를 동시에 사용하지 마세요.

토큰 발급이 `HTTP 403`으로 실패하면 토스증권 WTS의 **설정 → Open API → 허용 IP 관리**에서 이 PC가 사용하는 공인 IP를 등록했는지 확인합니다.

## 현재가 조회

`GET /market/prices?symbols=005930`으로 현재가를 조회합니다. 여러 종목은 `symbols=005930,000660`처럼 최대 200개까지 쉼표로 구분합니다. 조회 결과는 API 응답으로 돌려주고 `stocks`, `prices` 테이블에도 저장합니다.

## 로컬 실행

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py -m uvicorn app.main:app --reload
```

서버가 시작되면 다음 주소에서 확인합니다.

- 상태 확인: <http://127.0.0.1:8000/health>
- API 문서: <http://127.0.0.1:8000/docs>

`/health` 응답의 `live_trading`은 기본값 `false`입니다. 이후 단계에서도 실제 주문 연결 전까지 이 안전 기본값을 유지합니다.
