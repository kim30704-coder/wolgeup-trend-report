# 월급실험실 트렌드 리포트

매일 아침 세 가지 데이터를 모아서 "오늘 어떤 영상을 만들면 좋을지" 리포트를 만들어 주는 프로그램이에요.

| 데이터 | 알려주는 것 | 필요한 키 |
|---|---|---|
| 구글 트렌드 급상승 검색어 (한국) | 오늘 사람들이 갑자기 많이 찾는 단어, 그중 채널과 관련된 것 표시 | 없음 |
| 유튜브 아웃라이어 (최근 7일) | 구독자 수보다 훨씬 많이 조회된 영상 = 주제·제목·썸네일이 먹힌 영상. 제목 패턴도 분석 | YouTube API 키 |
| 네이버 검색어 트렌드 (API HUB) | 연말정산·청약·AI 일자리 같은 키워드의 검색량이 오르는지 내리는지 | 네이버 Client ID/Secret |

그리고 세 데이터를 엮어서 **"검색량이 오르는데 실제로 터진 영상도 있는 주제"**를 맨 위에 뽑아 줘요. 예시는 `sample/sample_report.md`를 보세요(가짜 데이터예요).

키가 없어도 구글 트렌드 부분은 바로 돌아가요. 키를 넣을수록 리포트가 풍부해져요.

---

## 1단계. 무료 API 키 받기 (각 10분)

### YouTube Data API 키
1. https://console.cloud.google.com 접속 → 구글 계정으로 로그인
2. 위쪽 프로젝트 선택 → **새 프로젝트** → 이름 아무거나(예: trend-report) → 만들기
3. 왼쪽 메뉴 **API 및 서비스 → 라이브러리** → "YouTube Data API v3" 검색 → **사용**
4. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → API 키**
5. 나온 키를 복사해 두기. (권장: 키 수정 → API 제한사항에서 YouTube Data API v3만 허용)

무료 할당량은 하루 10,000이고, 기본 설정은 하루 약 1,400만 써요. 결제 정보는 필요 없어요.

### 네이버 검색어 트렌드 키 (NAVER API HUB)
2026년부터 데이터랩 API는 네이버 개발자센터가 아니라 **네이버 클라우드 플랫폼의 NAVER API HUB**에서 받아요. (현재 한시적 무료)
1. https://www.ncloud.com 접속 → 오른쪽 위 **회원가입**(네이버 아이디로 가입 가능) → 로그인
2. 오른쪽 위 **콘솔** 클릭
3. 콘솔 오른쪽 위 **리전 & 플랫폼**에서 **한국 / VPC** 선택 → 적용
4. 왼쪽 위 **메뉴(☰) → Services → Application Services → NAVER API HUB**
5. 처음이면 **이용 신청** → 동의
6. 왼쪽 **Application** → **Application 등록**
7. 사용할 API에서 **검색어 트렌드**(Data Lab) 체크 → 다음 → 이름(예: `wolgeup-trend`) 입력 → 완료
8. Application 목록에서 방금 만든 것 선택 → **인증 정보** → **Client ID**와 **Client Secret** 복사

---

## 2단계. 실행 방법 (둘 중 하나)

### 방법 A. GitHub에서 매일 자동 실행 (추천, 컴퓨터 꺼져 있어도 됨)
1. https://github.com 가입 → 오른쪽 위 **+ → New repository**
   - 이름: `wolgeup-trend-report`, **Private** 선택 → Create
2. **uploading an existing file** 클릭 → 이 폴더 안의 파일을 전부 끌어다 놓기 → Commit
   - `.github` 폴더가 안 올라가면: **Add file → Create new file**에서 이름을 `.github/workflows/daily-report.yml`로 쓰고 내용 붙여넣기
3. 저장소의 **Settings → Secrets and variables → Actions → New repository secret**에서 3개 등록
   - `YOUTUBE_API_KEY`
   - `NAVER_CLIENT_ID`
   - `NAVER_CLIENT_SECRET`
4. **Actions** 탭 → "매일 트렌드 리포트" → **Run workflow**로 한 번 실행해서 확인
5. 이후 매일 아침 7시 13분에 자동 실행되고, 결과는 `reports/latest.md`(오늘)와 `reports/날짜.md`(기록)에 쌓여요.
   - 휴대폰 GitHub 앱에서 저장소 → reports → latest.md 를 열면 표까지 보기 좋게 보여요.

### 방법 B. 내 컴퓨터에서 실행 / Claude Code에서 실행
```bash
pip install -r requirements.txt

# Mac/Linux
export YOUTUBE_API_KEY="키"
export NAVER_CLIENT_ID="아이디"
export NAVER_CLIENT_SECRET="시크릿"
python trend_report.py

# Windows PowerShell
$env:YOUTUBE_API_KEY="키"; $env:NAVER_CLIENT_ID="아이디"; $env:NAVER_CLIENT_SECRET="시크릿"
python trend_report.py
```
Claude Code에서는 이 폴더를 열고 "키 설정하고 리포트 실행해줘"라고 하면 돼요.

---

## 설정 바꾸기 (`config.yaml`)
- `youtube.search_queries`: 유튜브에서 찾아볼 검색어. 하나 늘릴 때마다 할당량 약 100 사용
- `youtube.days`, `min_views`: 최근 며칠, 최소 조회수
- `naver.keyword_groups`: 검색량을 볼 키워드 묶음. 같은 뜻의 단어를 한 그룹에 넣기
- `naver.anchor`: 기준 키워드. 모든 키워드를 이 단어 검색량과 비교해서 "기준 대비" 숫자를 만들어요
- `google_trends.relevance_words`: 급상승 검색어 중 "채널 연관"으로 표시할 단어

## 리포트 읽는 법
- **배수**: 조회수 ÷ 구독자 수. 10배가 넘으면 채널 힘이 아니라 주제·제목이 먹힌 영상이에요. 이런 영상의 제목 구조를 참고하세요.
- **하루 평균**: 올라온 뒤 하루에 몇 회씩 보는지. 높을수록 지금 알고리즘을 타는 중이에요.
- **네이버 변화율**: 최근 14일 평균 vs 그 전 14일. 🔥 급상승(+50% 이상), ⬆ 상승(+15% 이상)
- **기준 대비**: '재테크' 검색량을 100으로 봤을 때. 200이면 재테크의 2배 정도 검색돼요.

## 한계
- 네이버 숫자는 상대값이라 정확한 검색 횟수가 아니에요.
- 유튜브 검색 결과는 유튜브가 골라 준 상위 영상이라 모든 영상을 보는 건 아니에요.
- 구독자 수를 숨긴 채널은 배수가 "-"로 나와요.

## 테스트
```bash
pip install pytest
pytest -q                     # 가짜 데이터로 전체 흐름 검사
python tests/test_report.py   # sample/sample_report.md 다시 만들기
```

## 유튜브 검색 추이 (리포트 4번 항목)
- 구글 트렌드의 'YouTube 검색' 필터 데이터를 가져와요. **키가 필요 없어요.**
- `config.yaml`의 `youtube_search.keywords`에 보고 싶은 단어를 넣으면 돼요. 기준 키워드(`anchor`, 기본 '연봉') 평균을 100으로 환산해요.
- 공식 API가 아니라서 구글이 막는 날(429)은 이 항목만 비고, 나머지 리포트는 그대로 나와요.
