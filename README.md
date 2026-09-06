# Trend Signal — 개인용 트렌드 대시보드

Google Trends 급상승 검색어 · 경제뉴스 · 시장지표 · 부동산 실거래를 **공개 원본 소스에서 직접**
수집·가공해 하루 한 번 자동 갱신되는 개인 대시보드입니다.

GitHub Pages(무료, 무제한 기간, HTTPS 자동)에 호스팅되고,
GitHub Actions가 매일 데이터를 받아 **AES-256-GCM으로 암호화한 뒤** 배포합니다.
서버가 없으므로 해킹당할 백엔드 자체가 존재하지 않습니다.

---

## 1. 설치 (10분)

### 1) 리포지토리 만들기

GitHub에서 새 리포지토리를 만듭니다. 이름은 자유(예: `trend-signal`).
**Public / Private 아무거나 상관없습니다** — 데이터가 암호화되어 있기 때문입니다.
(단, Private 리포지토리는 Pages를 쓰려면 유료 플랜이 필요하므로 **Public 권장**.)

이 폴더의 파일 전체를 그 리포지토리에 올립니다.

```bash
cd trend-dashboard
git init
git add .
git commit -m "init: trend signal dashboard"
git branch -M main
git remote add origin https://github.com/<사용자명>/<리포지토리명>.git
git push -u origin main
```

### 2) 비밀번호 등록

리포지토리 → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `SITE_PASSWORD` | 사이트에 접속할 때 쓸 비밀번호 (8자 이상, 길수록 안전) |
| `DATA_GO_KR_KEY` | (선택) 공공데이터포털 서비스키 — 부동산 섹션용 |

> `SITE_PASSWORD`는 **데이터를 여는 열쇠 그 자체**입니다. 바꾸면 다음 갱신부터 적용됩니다.
> 잊어버리면 복구 방법이 없으니 비밀번호 관리자에 저장해 두세요.

### 3) Pages 켜기

**Settings → Pages → Build and deployment → Source** 를 **GitHub Actions** 로 선택합니다.

### 4) 첫 실행

**Actions 탭 → "데이터 갱신 및 배포" → Run workflow** 를 눌러 수동 실행합니다.
2~3분 뒤 `https://<사용자명>.github.io/<리포지토리명>/` 에서 열립니다.

---

## 2. 부동산 데이터 켜기 (선택)

1. [공공데이터포털](https://www.data.go.kr) 회원가입
2. "**아파트 매매 실거래가 상세 자료**" 검색 → 활용신청 (자동 승인, 무료)
3. 마이페이지에서 **일반 인증키(Encoding)** 복사
4. 리포지토리 Secret 에 `DATA_GO_KR_KEY` 로 등록

조회 지역은 `scripts/collect.py` 의 `REGION_CODES` 에서 바꿉니다 (법정동 코드 앞 5자리).

```python
REGION_CODES = {
    "11680": "서울 강남구",
    "41135": "성남 분당구",
    # 원하는 지역 추가
}
```

---

## 3. 갱신 주기 바꾸기

`.github/workflows/update.yml` 의 `cron` 을 수정합니다. **UTC 기준**이므로 KST에서 9시간을 뺍니다.

| 원하는 시각(KST) | cron |
|---|---|
| 매일 07:30 (기본) | `30 22 * * *` |
| 매일 08:00 | `0 23 * * *` |
| 하루 3회 (07/13/19시) | `0 22 * * *` + `0 4,10 * * *` |
| 매시간 | `0 * * * *` |

> GitHub Actions 무료 한도는 Public 리포지토리에서 **무제한**입니다.
> Private 리포지토리는 월 2,000분이며, 이 작업은 1회에 1~2분 정도 씁니다.

---

## 4. 로컬에서 테스트

```bash
pip install cryptography

export SITE_PASSWORD="테스트비밀번호"
python scripts/collect.py build/latest.json
python scripts/crypt.py encrypt build/latest.json site/data/latest.enc.json

cd site && python -m http.server 8080
# → http://localhost:8080
```

---

## 5. 구조

```
scripts/collect.py   수집 + 가공 (소스 하나가 죽어도 나머지는 계속 동작)
scripts/crypt.py     AES-256-GCM 암·복호화 (브라우저 Web Crypto와 호환)
site/index.html      대시보드 마크업
site/assets/app.js   복호화 + 렌더링 (전부 브라우저에서만 실행)
site/assets/style.css
site/data/           암호화된 데이터가 여기에 커밋됨 (평문은 절대 커밋되지 않음)
.github/workflows/update.yml   매일 수집 → 암호화 → 커밋 → 배포
```

---

## 6. 데이터 출처

| 섹션 | 출처 | 인증 |
|---|---|---|
| 급상승 검색어 | Google Trends RSS (`trends.google.com/trending/rss?geo=KR`) | 불필요 |
| 뉴스 | 연합뉴스 / 한국경제 / 매일경제 / SBS / Google News RSS | 불필요 |
| 시장지표 | Yahoo Finance, Upbit, open.er-api.com | 불필요 |
| 부동산 | 공공데이터포털 국토교통부 실거래가 API | 서비스키 |

수집한 기사와 키워드는 **제목·링크·출처만** 보관하며 본문은 저장하지 않고, 모든 항목이 원문으로
링크됩니다. 개인 열람 목적의 구성이며, 원본 데이터의 권리는 각 출처에 있습니다.

---

## 7. 보안 메모

- 데이터는 **PBKDF2-SHA256(310,000회) + AES-256-GCM** 으로 암호화되어 저장됩니다.
  URL을 아는 사람도 비밀번호 없이는 내용을 읽을 수 없습니다.
- 비밀번호는 브라우저 밖으로 전송되지 않습니다. 복호화는 Web Crypto API로 로컬에서만 일어납니다.
- 정적 파일만 배포되므로 SQL 인젝션·서버 침해 같은 공격 표면이 없습니다.
- `<meta name="robots" content="noindex">` 로 검색엔진 노출을 차단합니다.
- 더 강한 보호를 원하면 Cloudflare Pages + **Cloudflare Access**(무료 50명)로 옮겨
  이메일 일회용 코드 로그인을 걸 수 있습니다. 이 저장소의 `site/` 폴더를 그대로 쓸 수 있습니다.
