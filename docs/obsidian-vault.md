# 옵시디언 볼트: 에이전트의 지식을 폰과 PC에서 읽기

두 분이 에이전트들이 쌓은 지식을 **읽고, 검색하고, 그래프로 훑어보도록** 만든 옵시디언(Obsidian) 폴더입니다. 옵시디언은 마크다운 파일이 든 폴더를 여는 앱이라서, 이 문서의 "볼트"는 그냥 **서버가 매일 새로 만드는 폴더**입니다. 코드: `paperbot/obsidian_export.py`(만드는 곳), 모양 틀: `paperbot/obsidian_vault/`.

## 1. 먼저, 이게 아닌 것

- **에이전트의 기억(DB)이 아닙니다.** 원본은 그대로 `agents3.db`, `paper3.db` 등에 있습니다. 볼트는 그 **읽기 전용 사본(보기용)**이고, 지워도 다음 날 다시 만들어집니다.
- **되돌려 쓰지 않습니다.** 볼트에서 노트를 고쳐도 에이전트나 DB에는 아무 일도 일어나지 않습니다(7절에 이유).
- **실험을 바꾸지 않습니다.** 매매 코드, 규칙, 해시로 고정한 문서는 건드리지 않습니다. 이 내보내기는 새 코드이고 DB를 읽기만 합니다(`mode=ro`, `query_only`). 테스트가 DB 파일이 한 바이트도 안 바뀌는 것을 확인합니다.
- **비밀이 들어 있지 않습니다.** 키, 토큰, 채팅 번호, IP, 서버 경로(`/etc/...`, `/var/lib/...`)는 글을 넣기 전에 지웁니다(`[비밀값 삭제]`, `[IP 삭제]` 등으로 바뀝니다). 테스트가 이 패턴들을 볼트 전체에서 찾아봅니다.

## 2. 안에 무엇이 있나

| 폴더 | 내용 |
|---|---|
| `00 홈` | **홈**(한눈에 보는 화면), 읽는 법(용어 풀이·그래프 색), 시스템 지도(그림과 캔버스), 볼트 상태 |
| `01 실험` | 규칙 한눈에, 타임라인(30일 간트: 시작 → 관찰 기간 끝(시작 + 21일) → 1차 체크포인트(시작 + 30일), 날짜는 실행 시작에서 계산), 레버리지 계단(규칙 B: 좋은 자리 50/40 vs 보통 30/20), 체크포인트 판정 |
| `02 매매법` | 매매법 36개, **한 매매법 = 노트 하나**: 한눈에, 봉별 실전 기록, 좋은 자리 vs 보통, 그림자 비교(같은 거래끼리), 5년 성격 카드, 가설·시험, 관련 회의, 에이전트 메모. 동전 던지기 봇, 추가 계좌도 여기. **딥시크·릴스**(허브): 딥시크 계열 17개마다 노트 하나(정의와 쉬운 말 규칙, 5년 연구, 거래·파산 수만: 딥시크 손익은 대시보드 딥시크 묶음에서만), 릴스 5분 단타 노트 하나 |
| `03 직원` | 조직도(그림 + 캔버스), 팀 12개, 역할 36명(활동·최근 발언), 딥시크·릴스 담당 5명(맡은 계열·방), 직원 성적표(가설 적중률). 담당 5명의 방은 `구조·유동성 담당 방`처럼 한글 이름으로, 그 회의(딥시크·릴스 손실·파산·주간)는 손실·긴급 회의로 묶입니다 |
| `04 회의` | **하루 한 장**(`일일/회의 날짜`), 주간 요약(`주간/`), 손실 복기·시세 급변·체크포인트·사고 회의 모음 |
| `05 교훈·가설` | 교훈(날짜별), **가설 장부**(코드 채점, 적중률과 표본 표시), **시험 장부**(시험 횟수와 우연 보정 기준), 낙관·비관 토론 채점, 가설 노트(최근 200개) |
| `06 연구` | 5년 연구 요약: 레버리지·손절, 익절 방식, 유명 매매법, 라이브러리, 오더플로, 3라운드, 진입 연구 등, DeepSeek 200개 분류(와 결과 파일이 생기면 그것도) |
| `07 매일 점검` | 밤 점검을 날짜별로: paper와 재계산 일치, 데이터, 비용, 그림자 |
| `08 규칙·문서` | 고정 규칙 문서의 읽기 전용 사본과 **해시 확인**(일치/불일치) |
| `99 내 메모` | **두 분이 쓰는 곳.** 내보내기가 이 폴더를 만들기만 하고(처음 한 번 `메모 시작` 노트 하나), 그 뒤로는 파일을 만들거나 고치거나 지우지 않습니다 |

노트 수는 30일 실험 기준 약 300~450개, 용량은 몇 MB 이하입니다. 매일 재생성에 몇 초에서 1분이 걸립니다(리허설 데이터 156계좌·거래 약 1만 건·회의 400번 기준 약 4초).

### 읽을 때 지키는 정직 원칙(노트에 이미 표시돼 있습니다)

1. **코드 계산 / AI 작성 / 원문 문서**를 글머리 라벨로 구분합니다. 회의 글, 메모, 가설 문장은 AI가 쓴 것이라 틀릴 수 있습니다. 숫자 표는 코드가 계산한 것입니다.
2. **표본 크기**를 같이 보여줍니다. 거래 10건 미만은 `표본 적음`(저장소의 `SMALL_N = 10`), 30건 미만은 체크포인트 판정 보류 수준으로 표시합니다.
3. **30일 체크포인트 전에는 결론이 없습니다.** 모든 숫자는 "중간 기록"이라고 적습니다. 순위가 아니라 번호순으로 늘어놓습니다.
4. 모든 노트 맨 위에 **자동 생성 시각(KST)**과 **자료 기준 시각**이 있습니다.
5. 규칙 문서 사본은 원본의 SHA-256과 기록된 해시를 비교해 `일치/불일치`를 보여줍니다.

### 연결과 그래프

노트마다 속성(frontmatter)이 있어 옵시디언의 속성 창이나 Bases, Dataview 식 검색에 쓸 수 있습니다: `type`(허브·전략·회의·교훈·가설·연구·규칙·직원·점검·시험·실험), `strategy`, `timeframe`, `status`, `date`, `n_trades`, `small_sample`, `tags`, `cssclasses`, `source`(code/ai/mixed/doc). **어떤 커뮤니티 플러그인에도 기대지 않습니다**: 표는 모두 코드가 만든 마크다운입니다.

링크: 매매법 ↔ 회의(날짜) ↔ 가설 ↔ 교훈 ↔ 연구 문서 ↔ 점검(날짜), 그리고 허브들. 그래프 색(Catppuccin Mocha 팔레트):

| 종류 | 색 | 그래프 필터 |
|---|---|---|
| 허브(목록·지도, 큰 점) | 노랑 | `tag:#허브` |
| 매매법 | 보라 | `tag:#전략` |
| 회의 | 파랑 | `tag:#회의` |
| 교훈 | 초록 | `tag:#교훈` |
| 가설 | 주황 | `tag:#가설` |
| 연구 | 청록 | `tag:#연구` |
| 규칙·문서 | 빨강 | `tag:#규칙` |
| 직원 | 분홍 | `tag:#직원` |
| 밤 점검 | 하늘 | `tag:#점검` |
| 시험 장부 | 적갈 | `tag:#시험` |
| 실험 | 연보라 | `tag:#실험` |

점의 크기는 옵시디언이 연결 수로 정하므로 허브가 저절로 커집니다(`graph.json`의 `nodeSizeMultiplier` 1.4).

### 그림과 모양

- **머메이드 그림**(옵시디언 기본 기능): 조직도, 자료 흐름도, 30일 간트, 레버리지 계단, 마감 이유 파이.
- **캔버스 파일 2개**: `조직도.canvas`(클릭하면 팀 노트), `시스템 지도.canvas`.
- **콜아웃**(`info`, `warning`, `success`, `danger`)과 전용 `pb-hero`(큰 제목 블록), `pb-stat`(숫자 타일), `pb-ai`(AI 글), `pb-code`(코드 결과), 접을 수 있는 섹션, `<progress>` 진행 막대, 배지(코드 계산·AI 작성·표본 적음).
- 노트 종류별 **배너**(색 띠, 이미지 없이 CSS만)는 `cssclasses`(`pb-home`, `pb-strategy`, `pb-meeting` …)로 붙습니다.

## 3. 모양(테마) 설정

`.obsidian/` 틀이 볼트에 같이 만들어집니다.

| 파일 | 하는 일 |
|---|---|
| `appearance.json` | 어두운 기본, CSS 조각 2개 켜기. 테마는 비움(없어도 멀쩡) |
| `snippets/paperbot-palette.css` | 바탕·글자·링크·제목 색을 **Catppuccin Mocha(어두움) / Latte(밝음)**로. AnuPpuccin·Minimal이 같은 이름의 변수(`--ctp-*`)를 정의하면 그 값을 따라갑니다 |
| `snippets/paperbot.css` | 히어로 블록, 숫자 타일, 콜아웃, 표, 배지, 배너, 한글 글꼴(Pretendard → Noto Sans KR → 맑은 고딕), 진행 막대. 위 변수를 읽기만 하므로 테마 위에 겹쳐 얹힙니다 |
| `graph.json` | 그래프 색 그룹(위 표), 노드 크기, 간격 |
| `app.json` | 읽기 화면으로 열기(실수로 고치는 것 방지), **새 노트는 `99 내 메모`에 저장**, 읽기 좋은 줄 폭 |
| `core-plugins.json` | 그래프, 백링크, 아웃고잉 링크, 태그, 속성, 검색, 캔버스, 개요 켬. 데일리 노트는 끔 |
| `bookmarks.json` | 홈, 읽는 법, 매매법 목록 … 즐겨찾기 |
| `types.json` | 속성 형식(날짜, 숫자, 체크박스) |

**두 분이 직접 바꾼 `.obsidian` 파일은 덮어쓰지 않습니다.** 내보내기는 (a) 없는 파일만 만들고, (b) 자기가 만들고 아직 그대로인 파일만 새 틀로 바꿉니다. 옵시디언이 설정 파일을 다시 써 버리면 그 파일은 "두 분 것"이 되어 그대로 남습니다.

### 인기 테마 얹기 (선택, 탭 두 번)

테마 파일을 이 저장소나 볼트에 **넣어 두지 않습니다**(라이선스 미확인). 옵시디언 안에서 받습니다.

1. 설정(톱니바퀴) → **모양(Appearance)** → 테마 **관리(Manage)** → 둘러보기 → `AnuPpuccin` 검색 → **설치 및 사용**.
   - 더 얌전한 쪽이 좋으면 같은 방법으로 `Minimal`을 받고, 색 구성표에서 Catppuccin 또는 Nord를 고릅니다.
2. (AnuPpuccin을 쓸 때 선택) 같은 화면의 CSS 조각에서 `paperbot-palette`를 끕니다. 테마가 바탕색을 정하게 두는 것이고, `paperbot`(배너·콜아웃·표)는 켜 둡니다. **테마를 설치하지 않아도** 이미 같은 팔레트로 보입니다.
3. 테마를 지우거나 안 받아도 아무것도 깨지지 않습니다(조각 CSS는 테마 변수가 없으면 자기 값을 씁니다).

> 테마는 기기마다 옵시디언이 `.obsidian/themes/`에 받아 둡니다. 4절의 권장 방식(서버 → 기기 한 방향)에서는 **폰과 PC가 서로의 테마를 주고받지 않으므로 기기마다 한 번씩** 위 1을 합니다(1분). `.obsidian`까지 두 기기가 서로 주고받게 하려면 4절의 "선택: 설정 폴더도 공유"를 보세요.

사용한 팔레트는 Catppuccin(MIT)의 공개 색 값이며, 색 숫자만 썼고 테마 파일은 가져오지 않았습니다.

## 4. 폰과 PC로 가져오기

두 분은 **Windows 10 PC와 안드로이드 폰** 둘 다에서 보길 원합니다. 서버 폴더는 `/var/lib/paperbot/obsidian`입니다. 비교한 방법 네 가지:

| | ① Syncthing + Tailscale | ② Windows에서 `scp -r` | ③ 비공개 GitHub + Obsidian Git | ④ Obsidian Sync (유료) |
|---|---|---|---|---|
| 비용 | 무료 | 무료 | 무료(비공개 저장소) | 유료(구독, 월 몇 달러; 가격은 가입 화면에서 확인) |
| 폰 | 됨 (Syncthing-Fork 앱) | 안 됨(PC에서 폰으로 옮기는 일이 따로 필요) | 됨(플러그인이 느리고 불안정할 수 있음) | 됨 |
| 자동 갱신 | 됨(밤에 만들면 몇 분 안에) | 아니오(두 분이 명령을 칠 때만) | 서버가 밤마다 푸시 + 기기에서 풀 | 됨 |
| 서버에 새로 두는 것 | Syncthing(읽기 전용 사용자) | 없음 | **쓰기 권한 토큰**(아래 위험) + 푸시 작업 | 서버에는 못 둠(화면 없는 서버에서 공식 앱을 못 돌림). 서버 폴더를 가져오는 ①/② 단계가 또 필요 |
| 이미 있는 것 활용 | Tailscale 그대로 | SSH 그대로 | GitHub 계정 | 없음 |
| 위험 | 두 방향으로 열면 실수 편집이 서버에 올라감(아래 "한 방향") | 없음 | 서버의 토큰이 털리면 그 저장소에 쓸 수 있음. 내용이 GitHub 서버에 저장됨 | 양방향이라 실수 편집이 서로 퍼짐 |
| 초보에게 | 한 번만 설정하면 끝 | 매번 명령 입력 | 설정 많음 | 쉬움(하지만 서버 연결이 안 해결됨) |

### 권장: ① Syncthing (서버 → 기기, 한 방향)

이유: 무료이고, 이미 있는 Tailscale 안에서만 오가고(인터넷 공개 없음), 한 번 설정하면 두 분은 앱만 열면 됩니다. 폰도 PC도 같은 방식입니다.

**한 방향으로 두는 이유.** 서버는 폴더를 **보내기만(Send Only)** 하고 PC와 폰은 **받기만(Receive Only)** 합니다. 기기에서 생긴 변경(실수로 노트를 고치거나 지움)이 서버로 올라가지 않아서, 서버의 노트가 한 번 고쳐진 채 굳어 버리는 일(내보내기는 "고친 노트는 지킴" 규칙이 있습니다)이 없습니다.

**두 분의 메모(`99 내 메모`)는 따로 둡니다.** 받기 전용 폴더 안에서 쓴 글은 그 기기에만 남고 서로 안 건너갑니다. 그래서 `99 내 메모`만 **두 번째 Syncthing 폴더**로 PC ↔ 폰 양방향으로 맞춥니다(서버는 끼지 않으므로 서버에 쓰기 길을 열지 않습니다).

설정은 한 번만 하면 되고, 서버 쪽은 이 저장소 주인이나 Claude와 함께 합니다.

#### 서버 (한 번, 관리자 계정으로)

```bash
sudo apt-get install -y syncthing acl
sudo adduser --system --group --home /var/lib/syncthing syncthing
# syncthing 사용자가 볼트만 읽게(DB 파일은 못 읽음): 폴더를 지나가기만, 볼트는 읽기만
sudo setfacl    -m u:syncthing:--x /var/lib/paperbot
sudo setfacl -R -m u:syncthing:rX  /var/lib/paperbot/obsidian
sudo setfacl -R -d -m u:syncthing:rX /var/lib/paperbot/obsidian
sudo -u paperbot mkdir -p /var/lib/paperbot/obsidian/.stfolder      # Syncthing이 확인하는 표식(쓰기 권한이 없어도 되게)
sudo systemctl enable --now syncthing@syncthing
```

1. 서버의 Syncthing 화면은 서버 안에서만 열립니다. Windows 명령 프롬프트(cmd)에서 `ssh -L 8384:127.0.0.1:8384 사용자@서버Tailscale이름` 을 켜 두고, PC 브라우저에서 `http://127.0.0.1:8384` 를 엽니다.
2. 설정 → 연결: **전역 검색, 로컬 검색, 릴레이, NAT 통과를 모두 끕니다**(Tailscale 주소로만 연결하려고).
3. 폴더 추가: 경로 `/var/lib/paperbot/obsidian`, 이름 `paperbot-vault`, 유형 **Send Only(보내기 전용)**. 고급 → **무시 패턴**에 `99 내 메모` 와 `.obsidian/workspace*.json` 한 줄씩.

#### Windows PC (두 분)

1. syncthing.org에서 Windows용을 받아 설치하고 실행합니다(브라우저에서 `http://127.0.0.1:8384`).
2. **장치 추가**: 서버의 장치 ID를 넣고, 주소에 `tcp://서버의Tailscale주소(100.x.x.x):22000` 을 적습니다(서버 쪽에서도 PC 장치를 같은 방법으로 승인).
3. 서버가 보낸 폴더 `paperbot-vault`를 받을 때 **폴더 유형을 Receive Only(받기 전용)**로, 경로는 예: `C:\Users\이름\Documents\paperbot-vault`. 같은 폴더의 무시 패턴에도 `99 내 메모`를 넣습니다.
4. 옵시디언 설치 → **보관함(Vault) 폴더 열기** → 위 폴더 선택 → **홈** 노트를 엽니다.

#### 안드로이드 폰 (두 분)

1. 앱: **Syncthing-Fork**(F-Droid 또는 Google Play). 옛 공식 Syncthing 안드로이드 앱은 개발이 끝났습니다.
2. 같은 방법으로 서버 장치를 추가하고(Tailscale 앱이 켜져 있어야 합니다), `paperbot-vault`를 **받기 전용**으로 `/storage/emulated/0/Documents/paperbot-vault` 에 받습니다. 무시 패턴에 `99 내 메모`.
3. 옵시디언 앱 → **보관함 폴더 열기** → 위 폴더 → **홈**.

#### 두 분의 메모 동기화 (PC ↔ 폰)

PC의 Syncthing에서 폴더 추가: 경로 `...\paperbot-vault\99 내 메모`, 유형 **Send & Receive**, 폰과 공유(서버와는 공유하지 않음). 폰에서도 같은 폴더를 받습니다. (`99 내 메모`는 위 큰 폴더에서 "무시"해 두었기 때문에 겹치지 않습니다.)

#### 선택: 설정 폴더도 공유

`.obsidian`(테마 설치, 즐겨찾기, 창 배치)까지 PC ↔ 폰이 서로 맞게 하고 싶다면, 위의 `.obsidian/workspace*.json` 무시와 별개로 `.obsidian`을 세 번째 Send & Receive 폴더로 PC ↔ 폰에 공유하고 큰 폴더의 무시 패턴에 `.obsidian`을 더합니다. 그러면 한 기기에서 AnuPpuccin을 받으면 다른 기기도 받습니다. 다만 서버가 새 틀을 만들어도 이 기기들에는 가지 않으므로, 새 틀이 필요하면 한 번 직접 복사합니다. **처음에는 권장하지 않습니다**(설정이 하나 더 늘어남).

#### 확인

PC에서 `paperbot-vault` 폴더에 `00 홈`이 보이면 성공입니다. 서버에서 밤 갱신(09:50 KST) 뒤 몇 분 안에 바뀐 노트만 건너옵니다. Syncthing 화면에 "로컬에서 변경된 항목"이 보이면 그 기기에서 받기 전용 폴더의 파일을 고친 것입니다. **되돌리기(Revert Local Changes)**를 누르면 서버 버전으로 돌아옵니다(`99 내 메모`는 따로 있어 영향 없음).

### 대안 ②: Windows에서 `scp -r` (Syncthing이 안 될 때)

서버 쪽에서 로그인하는 사용자에게 읽기 권한을 한 번 줍니다(`사용자`는 SSH 로그인 이름).

```bash
sudo setfacl    -m u:사용자:--x /var/lib/paperbot
sudo setfacl -R -m u:사용자:rX  /var/lib/paperbot/obsidian
```

Windows 10 명령 프롬프트(cmd)에서(서버 이름은 Tailscale 이름):

```
mkdir "%USERPROFILE%\Documents\paperbot-vault"
scp -r "사용자@서버:/var/lib/paperbot/obsidian/0*" "%USERPROFILE%\Documents\paperbot-vault\"
```

- 처음 한 번만 설정 폴더도: `scp -r "사용자@서버:/var/lib/paperbot/obsidian/.obsidian" "%USERPROFILE%\Documents\paperbot-vault\"`. 이후에는 `0*`만 받아 두 분이 바꾼 테마가 덮이지 않게 합니다.
- `0*`는 `00 홈`부터 `08 규칙·문서`까지입니다. `99 내 메모`는 받지 않으므로 두 분의 메모가 안전합니다.
- 받을 때마다 같은 이름 파일을 덮어쓰고, 서버에서 없어진 노트는 지우지 않습니다. 폰에는 이 방법이 안 맞습니다.

### ③ 비공개 GitHub + Obsidian Git: 권하지 않는 이유

서버가 밤마다 볼트를 커밋해서 GitHub에 올려야 하므로 서버에 **그 저장소에 쓸 수 있는 토큰(또는 배포 키)**이 필요합니다. 서버가 뚫리면 그 토큰으로 저장소에 쓸 수 있습니다(실거래 키는 아니지만, 볼트 내용이 바꿔치기될 수 있고 GitHub에 사본이 남습니다). 토큰은 **그 저장소 하나에만** 쓰기 권한을 주는 키로 만들고 `/etc/paperbot` 같은 비밀 폴더에 두어야 합니다. 폰의 Obsidian Git은 큰 볼트에서 느리고 불안정할 수 있고, 올리는 작업(커밋·푸시)은 이번에 만들지 않았습니다. 정말 쓰려면 별도 작업으로 만드세요.

### ④ Obsidian Sync: 서버를 못 이어서 단독으로는 부족

기기끼리 동기화는 쉽고 암호화도 되지만, 서버가 만든 폴더를 Sync에 올리려면 서버에서 옵시디언 앱이 돌아야 하는데 화면 없는 서버에서는 공식적으로 어렵습니다. 결국 ①이나 ②로 **PC 한 대에 서버 폴더를 가져오는 단계**가 또 필요하고 구독료만 늡니다. 양방향이라 실수로 고친 노트가 서로 퍼지는 점도 ①의 한 방향보다 못합니다.

### 두 분께 권하는 순서

1. 이 저장소 주인이 서버에서 위 "서버" 블록을 한 번 실행하고 Syncthing 화면 설정(2~3번)을 합니다.
2. PC 설치와 폰 설치는 위 단계를 그대로 따라 하면 됩니다(각 10분 안팎).
3. 처음 열어 볼 노트: **홈** → **읽는 법** → **매매법 목록**.
4. 설치 전이거나 급할 때: 대안 ②(`scp`)로 PC에서 먼저 봅니다.

## 5. 서버 설치: `install.sh`, `launchcheck.py`, `failalert.py`에 더할 줄

다른 작업자가 `deploy/install.sh`와 `launchcheck.py`를 고치는 중이라 이 작업에서는 **건드리지 않았습니다.** 합칠 때 아래만 더하면 됩니다.

### `deploy/install.sh`

1. 유닛 설치 반복문(`for u in ... ; do install -m 644 ...`)의 목록에 `paperbot-obsidian.service paperbot-obsidian.timer` 를 더합니다.
2. 폴더 만들기(다른 `install -d` 줄 옆에):
   ```
   # 옵시디언 볼트(docs/obsidian-vault.md): 만드는 쪽은 paperbot, 두 분의 99 내 메모는 거기서 한 번만 만들어짐
   install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/obsidian
   ```
3. 타이머 켜기(`systemctl enable --now` 줄들 옆에): `systemctl enable --now paperbot-obsidian.timer`
4. 배포 때 도는 작업을 기다리는 목록(`systemctl is-active ... paperbot-rehearsal.service` 줄들)에 `paperbot-obsidian.service` 를 더합니다.
5. 설치된 유닛 파일 목록(`paperbot-rehearsal.service paperbot-rehearsal.timer \` 줄 옆)에 `paperbot-obsidian.service paperbot-obsidian.timer` 를 더합니다.

### `paperbot/launchcheck.py`

- 타이머: `EXTRA_TIMERS = ("paperbot-offsite.timer", "paperbot-obsidian.timer")` (설치돼 있으면 켜짐을 요구). 안 켜도 되는 선택으로 두려면 대신 `OPTIONAL_TIMERS = ("paperbot-rehearsal.timer", "paperbot-obsidian.timer")` (`[참고]`로만 표시).
- 작업: `JOBS = (..., "paperbot-obsidian.service")` 에 더하면 직전 실행 실패를 점검에 보입니다. `ALL_UNITS`는 위 두 줄을 따라 늘어납니다(`EXTRA_TIMERS`와 `JOBS`를 쓰므로 따로 안 더해도 됨).

### `paperbot/failalert.py`

`JOBS_KO`에 한 줄:

```python
"paperbot-obsidian.service": ("옵시디언 볼트 갱신(09:50)", "내일 09:50에 다시 돎\n지금 다시: sudo systemctl start paperbot-obsidian"),
```

### 같이 고칠 테스트(`tests/test_deploy.py`)

`deploy/paperbot-obsidian.service`에 `OnFailure=`가 있으므로 위 `JOBS_KO` 줄을 더하기 전에는 `test_failed_scheduled_jobs_send_one_korean_warning`이 실패합니다(훅이 있는 유닛 = `JOBS_KO`여야 합니다). 더한 뒤에는 `test_the_owners_check_of_the_units_shows_only_the_settings`의 개수가 바뀝니다: 훅 5개 → 6개(`== 5 == len(FA.JOBS_KO)` → `== 6 == len(FA.JOBS_KO)`)이고, 전체 줄 수 7 → 8입니다.

### 한 번 손으로 돌려 보기

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.obsidian_export build --out /var/lib/paperbot/obsidian --dry-run   # 무엇을 쓸지만 나열
sudo systemctl start paperbot-obsidian        # 진짜로 한 번
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.obsidian_export status --out /var/lib/paperbot/obsidian
```

- 기본 경로는 서버 표준(`/var/lib/paperbot/...`, `/opt/crypto-bot-research`)이라 옵션을 안 줘도 됩니다.
- **root로 돌리지 마세요**: 볼트 파일이 root 소유가 되면 밤 작업이 못 덮어씁니다(다른 작업과 같은 이유).
- DB 파일이 없으면 그 부분은 "아직 없음"으로 채워집니다(0일차도 동작). 단, **지난번에 읽은 DB가 이번에 사라졌다면 빈 노트로 덮지 않고 실패**합니다(`--allow-empty`로만 강제).
- 샌드박스(`deploy/paperbot-obsidian.service`): 쓰기는 코드가 `/var/lib/paperbot/obsidian`에만 하지만, 샌드박스 쓰기 허용은 `/var/lib/paperbot`입니다. 살아 있는 WAL 모드 DB를 읽기 전용으로 열 때도 SQLite가 옆의 `-shm` 파일이 필요하기 때문입니다(`paperbot-agents.service`와 같은 이유). DB 본 파일은 `ReadOnlyPaths`로 읽기 전용, 비밀과 키가 있는 `/etc/paperbot`는 보이지 않고, 네트워크는 없습니다.
- 타이머: 매일 00:50 UTC(= 09:50 KST), `Persistent=true`. 09:20 밤 점검과 에이전트 회의 뒤입니다.

## 6. 만드는 규칙

- **같은 입력이면 같은 파일**입니다(생성 시각 줄만 다름). 내용이 안 바뀐 노트는 다시 쓰지 않습니다(동기화 트래픽이 적게).
- 파일마다 임시 폴더(`.paperbot-obsidian-staging`)에 쓴 뒤 이름을 바꿔 넣습니다(옵시디언이나 Syncthing이 반쯤 쓴 파일을 볼 일이 없음).
- `.paperbot-obsidian-manifest.json`에 만든 파일과 해시를 적어 둡니다. 바꾸거나 지우는 것은 **그 목록에 있고 아직 내가 쓴 그대로인 파일뿐**입니다.
  - 두 분이 고친 자동 생성 노트: 고친 것을 지킵니다(다시 만들지 않음). 되돌리려면 그 파일을 지우세요. `status`가 목록을 보여줍니다.
  - 이름이 같은 두 분의 파일: 건드리지 않습니다.
  - 더는 만들지 않는 옛 노트: 안 고쳤으면 지우고, 고쳤으면 그대로 둡니다.
- `99 내 메모`와 목록에 없는 파일은 읽지도 지우지도 않습니다.
- 에이전트 글은 노트 하나당 700자, 하루 노트의 AI 글은 합쳐 36,000자까지만 넣고 잘렸다는 표시를 합니다. 거래마다 노트를 만들지 않고 숫자는 집계합니다.
- 읽는 자료(읽기 전용): `paper3.db`, `daily3.db`, `agents3.db`(회의·라운드·메모·시험·시험 결과·제안·낙관/비관 채점), `checkpoint.db`, `inbox.db`(두 분 글·승인), 저장소의 `docs/*.md`, `research/**/*.md`, `research/*/out/` 요약, `paperbot/agents/roster3.py`(역할·팀·한글 이름). 마크다운만 읽고 코드는 가져오지 않습니다.

### 정적 미리보기 (옵시디언 없이)

```bash
python3 -m paperbot.obsidian_export preview --vault /var/lib/paperbot/obsidian --out /tmp/preview
```

`index.html` 한 파일에 홈 노트, 매매법 카드 한 장, 실제 링크 구조로 그린 그래프가 같은 팔레트로 들어 있습니다. 브라우저에서 열면 됩니다(머메이드 그림은 인터넷이 있을 때만 그려지고, 없으면 글로 보임).

## 7. 나중에: 두 분의 메모를 에이전트가 읽게 하기 (지금은 만들지 않음)

바라는 것: `99 내 메모`에 쓴 글을 에이전트가 읽거나 두 분 글처럼 방에 올리는 것.

**왜 지금 안 만드나**

- `inbox.db`의 **쓰는 쪽은 대시보드 하나**입니다(`rooms_db.open_inbox_rw`). 에이전트 쪽은 읽기만 하고 "어디까지 읽었는지"를 자기 DB(`cursors`)에 적습니다. 폰과 PC에서 오는 파일을 받는 두 번째 쓰기 길을 열면 이 규칙이 깨지고, 파일을 서버로 올리려면 읽기 전용으로 둔 Syncthing에 쓰기 길도 열어야 합니다.
- 두 분 글은 `agents3.db`에서 지금 **두 분이 직접 입력한 글만 데이터로** 읽게 되어 있습니다(지시가 아님). 파일에서 온 글은 길이·형식·내용을 달리 믿어야 합니다.
- 30일 실험 중에는 에이전트의 입력을 늘리는 일(새 입력 = 새 변수)을 피하는 편이 안전합니다.

**안전한 설계(나중에 만든다면)**

1. 두 분이 `99 내 메모/에이전트에게/` 폴더에 쓴 노트만 대상입니다(다른 노트는 읽지 않음).
2. 서버에 **받는 전용 폴더**(예: `/var/lib/paperbot/obsidian-inbox`)를 두고, 그 폴더를 Syncthing의 한 방향(기기 → 서버) 폴더로 만듭니다. 볼트 폴더와 분리해 내보내기가 덮을 일이 없습니다.
3. **대시보드 프로세스가** 이 폴더를 주기적으로 읽어 `owner_messages`로 한 줄씩 넣습니다(`room_id`는 노트의 속성 `room: team:lead` 같은 값, 허용 목록에 없으면 `team:lead`). inbox.db의 쓰기는 계속 대시보드 하나입니다.
4. 글자 수 한도(`MAX_OWNER_TEXT` 1,000자), 비밀값 지우기, 같은 노트를 두 번 안 넣는 해시 기록(대시보드 쪽 DB).
5. 에이전트는 지금처럼 그 글을 **데이터로만** 읽고, 노트가 낸 지시를 실행하지 않습니다.
6. 먼저 `--dry-run` 같은 미리보기와 "승인 버튼" 한 번(대시보드)을 두어, 두 분이 올릴 글을 확인한 뒤에만 들어가게 합니다.

## 8. 문제가 생기면

| 증상 | 확인 |
|---|---|
| 볼트가 안 바뀜 | `systemctl status paperbot-obsidian.timer`, `journalctl -u paperbot-obsidian -n 50`. 한 번 `sudo systemctl start paperbot-obsidian` |
| `refusing to replace the vault with empty notes` | 지난번에 읽은 DB가 지금 없음. 경로와 복원 상태를 확인(`--allow-empty`는 마지막 수단) |
| 어떤 노트가 옛날 그대로 | 그 노트를 고친 적이 있음(`status`의 `edited_by_owners`). 파일을 지우면 다음 갱신 때 다시 만들어집니다 |
| 기기에 노트가 안 건너옴 | Syncthing 화면에서 서버 연결, Tailscale 켜짐, 폴더 유형(서버 Send Only, 기기 Receive Only) 확인 |
| 테마가 풀림 | 서버가 `appearance.json`을 덮은 것이 아니라(두 분이 바꾼 파일은 덮지 않음) 기기별 설치입니다. 3절 1번을 다시 |
| 그래프가 너무 복잡 | 그래프 화면 필터에 `-tag:#점검 -tag:#회의` 처럼 입력해 종류를 가립니다 |

## 9. 개발자용

- 만들기: `python -m paperbot.obsidian_export build ...` / `status` / `preview`. 코드는 `paperbot/obsidian_export.py`(쓰기와 CLI), `obsidian_sources.py`(읽기 전용 읽기), `obsidian_notes.py`, `obsidian_notes_b.py`, `obsidian_home.py`(노트), `obsidian_util.py`(팔레트, 비밀값 지우기, 표), `obsidian_preview.py`(정적 미리보기).
- 테스트: `tests/test_obsidian_export.py`: 폴더와 노트, 위키링크 전부 해석(깨진 링크 검사기), 속성이 유효한 YAML, 머메이드 형식, 캔버스와 `.obsidian` JSON, 사용자 파일 불변, 두 번째 실행 무변경, 비밀 패턴 없음, 드라이런, 빈/없는/깨진 DB, DB 파일 불변, 실행 시간.
- 모양을 바꾸려면 `paperbot/obsidian_vault/config/`의 파일을 고치세요. 팔레트 값은 `obsidian_util.py`의 `MOCHA`/`LATTE`와 CSS의 `--pb-*` 변수가 같아야 합니다.
