# Gap audit rows (one source for gap_audit.json and the table in gap_audit.md).
# status: 있음 / 일부 / 없음 ; block: 예 / 아니오 / 결정 ; days = rough agent-days incl. tests
R = []


def row(area, cap, status, where, build, size, days, block, risk):
    R.append(dict(area=area, capability=cap, status=status, where=where, build=build, effort=size, days=days,
                  blocks_1017=block, risk=risk))


A = "A 자료·화면"
row(A, "15m/30m/1h/4h 봉·지표 요약 (AI 화면)", "일부",
    "sigservice.SignalService.hist (5m deque, 최대 115,200개, 규칙 봇 프로세스 안) · recorder.build_frames · "
    "context.entry_context (한 단계 위 봉만) · paper3.db live_bars (1m, 10/06 시작부터)",
    "코인별 4개 봉 요약 + 매매법 지표값을 만드는 화면 생성기(같은 입력=같은 바이트, 크기 상한, 형성 중 봉 제외). "
    "별도 프로세스면 REST로 5m 기록 부트스트랩(live3.fetch_5m 방식) 필요", "M", 2, "예",
    "미래 자료 섞임, 화면 6~9천 토큰(비용), 비결정 출력")
row(A, "신호별 차트 상황 칸", "있음",
    "signal_log.data.ctx: regime, htf_regime, box_pos, adx, di±, ema20_dist_atr, trend_age, range_pct, sr(room/floor) "
    "+ strength(우리 36만). DeepSeek·5m은 strength 없음",
    "ctx를 화면에 그대로 옮김. 일봉 요약·매물대(POC)는 없음(선택)", "S", 0.5, "아니오",
    "PLAN은 '겨우/확실히 맞음'을 보여 주자고 하나 설계 6-1은 금지(연구 B 0/410)")
row(A, "펀딩 (정산값·예상값·다음 정산 시각)", "일부",
    "feed.py가 정산된 fundingRate를 매 poll 받아 엔진에 적용; market.db funding(recorder). "
    "예상 펀딩(premiumIndex)·nextFundingTime은 기록 안 함",
    "AI 서비스에서 premiumIndex 1분 poll, known_at 기록", "S", 0.5, "아니오", "REST 무게(같은 IP)")
row(A, "미결제약정·롱숏·테이커 비율", "일부",
    "flow.py → flow.db oi5m, ls_global5m, ls_top_account5m, ls_top_position5m, taker5m, premium5m. "
    "09/30 설치, 매시 :07 동기화(paperbot-flow.timer) → 판단 시점에 최대 약 67분 늦음",
    "5분 poll(또는 타이머 5분)과 '자료 시각+5분' 이후만 쓰는 읽기 함수", "S", 1, "아니오",
    "늦은 값을 최신처럼 보여 줌; H3A(2차)는 이것이 필수")
row(A, "강제청산", "일부",
    "liqstream.py → liq.db (!forceOrder@arr, 코인당 초당 1건만 → 적게 잡힘). 09/30 설치, 그러나 경로가 10/06 "
    "커밋 ab1c387에서야 /market로 고쳐짐(옛 경로는 '연결되지만 조용함') → 쓸 수 있는 기록은 약 10/06부터",
    "코인별 최근 N분 합계 읽기 + 15분 0건이면 자료 오류", "S", 0.5, "아니오", "과소 집계, 침묵 감지 필요")
row(A, "호가 (depth20 스냅숏·미끄러짐 함수)", "없음",
    "fillcost.py: 원래 계좌 진입·청산 때만 REST depth(기록용). data/bookdepth는 과거 5분 자료. 엔진 체결은 고정 2bp",
    "v1은 AI와 쌍둥이 모두 고정 2bp 유지 권장. 설계 5-3 #11을 지키려면 웹소켓 스냅숏+slip()", "M", 2, "아니오",
    "AI만 다른 체결 모델을 쓰면 AI−규칙 비교가 깨짐")
row(A, "경제 발표 일정 + 깨움·진입 금지 시간", "일부",
    "data/macro_events.csv 11줄(NFP·CPI·FOMC·PCE 4종, 10월은 4줄) · events.py upcoming()/near()/et_to_utc "
    "(KINDS가 4종으로 고정)",
    "종류 확장(PPI, 매주 목 실업수당, 소매판매, ISM, JOLTS, GDP, FOMC 의사록, 의장 발언, 옵션 만기)+중요도, "
    "진입 금지(CPI·PCE·NFP ±15분, FOMC −15~+90분), 30분 전·직후 깨움 스케줄러", "S", 1, "예",
    "10/14 CPI가 0차 시험, 10/28 FOMC·10/29 PCE가 1차 기간 안")
row(A, "충격 표시 (BTC 5분 ±2% 등)", "없음", "—", "1m 피드에서 계산하는 플래그 + 문턱 k 사전 고정", "S", 0.5,
    "아니오", "k를 결과 보고 고르면 안 됨")

B = "B 기록·짝 비교"
row(B, "판단 기록표 (원문·의도·위험 결과·체결 4층, 화면 지문, 모델·토큰·지연)", "없음",
    "store3에 AI 표 없음. 비슷한 틀: agents/debate.py debate_rounds(토큰·비용·상태)",
    "aibot.db: requests / answers(raw) / intents / risk_results / fills, 신호 id·ref_time·호출 시작·응답 시각",
    "M", 1.5, "예", "빠진 행 = 판정 불가")
row(B, "보여 준 모든 신호의 규칙 단독 결과 (신호 시각 쌍둥이)", "일부",
    "daily3 'skipped' 그림자(계좌가 건너뛴 신호만, 밤마다, 안 끝난 행 빠짐), obsshadows 변형(끝난 거래만), "
    "analyze.py replay(오프라인, 모든 SUBMITTED). 부품: daily3._alone, make_signal, obsshadows.symbol_steps",
    "AI에게 보여 준 신호마다 AI와 같은 크기·청산 규칙으로 단독 재생, 열린 것은 시가 평가", "M", 1.5, "예",
    "규칙 계좌 손익과 직접 비교하면 틀림(한 번에 하나라 다른 신호를 들고 있음)")
row(B, "AI 체결 시각 쌍둥이 + 행동별 '원래대로' 쌍둥이", "없음", "—",
    "같은 작업에서 AI 체결 시각·가격으로 재생; 빠른 청산·손절 이동·스위칭마다 '원래대로' 재생", "M", 1.5, "예",
    "없으면 지연 잡음(15m 결정당 sd 0.57R)이 판단 효과에 섞임")
row(B, "방향 뒤집기 동전 (같은 순간 반대 방향)", "일부",
    "analyze.sideflip_test(오프라인, 묶음 = run×bar_close 1h 내림). 실시간 없음",
    "쌍둥이 작업에 반대 방향 재생 추가", "S", 0.5, "아니오", "묶음 정의를 D0 전에 고정해야 함")
row(B, "같은 방향·무작위 시각 동전", "일부",
    "checkpoint.py 동전 봇(계좌마다 10,000개, 롱 비율·코인·세션 복사; 규칙 봇 판정용). lens/luck_flow/luck.py(1회용). "
    "실시간 RANDOM_k 계좌는 트레이더와 맞춰지지 않음",
    "AI 실제 빈도·롱 비율·코인·봉 비율을 복사하는 동전 생성기, 뽑는 범위는 D0 전 고정", "M", 1.5, "아니오",
    "범위 정의에 따라 결과가 달라짐(N17 예 +0.39 vs +0.52)")

C = "C 체결·청산·크기·한도"
row(C, "규칙 계좌 체결 방식 (확인용)", "있음",
    "sigservice.compute: ref = 계산 직후 bookTicker ask(롱)/bid(숏); engine._try_enter: ref×(1±0.0002), "
    "entry_time = 다음 1분봉 open_time. 진입 1,430건 모두 일치(v3b 296, v4 1,134)",
    "AI 경로도 같은 함수 사용", "S", 0, "아니오", "설계 문서의 '다음 1분봉 시가'와 다름")
row(C, "AI 진입 체결 경로 (답 받은 시각 가격)", "없음", "—",
    "답 → Signal(ref = 받은 시각 bookTicker, ref_time = 받은 시각) → AI 엔진 pending; 마감 넘으면 '늦음'", "S", 0.5,
    "예", "다음 분 시가로 하면 엔진 차이로 지연 비용이 생김")
row(C, "R 기준 청산 (계단 R 단위, 자기 봉 마감에만 올림, +1R 뒤 본전, 잠금 즉시 손절 주문)", "없음",
    "ladder.py는 순 ROE(레버리지 곱) 기준, 매 1분봉마다 올림. tp1R~3R·ladder_cap2R는 obsshadows 그림자에만",
    "reel_engine.ReelEngine처럼 PaperEngine 하위 클래스 + 재생 일치 시험", "M", 2, "예",
    "1% 위험 크기에서 ROE 계단을 쓰면 낮은 레버리지에서 계단이 사실상 안 걸림")
row(C, "신호별 20배·강제청산 검사 + 레버리지 구간표", "일부",
    "sizing.size_position(손절이 청산가 안쪽 max(1 ATR, 0.2%)), margin.liquidation_price, "
    "live3가 시작마다 Binance leverageBracket을 읽기 전용 키로 받음(runs: 'Binance leverageBracket (live)', 7dec81ab…)",
    "feasible_20x(entry, stop, atr, brackets) 함수 + 4h 진입 관문 + AI 쪽 구간표 사본", "S", 0.5, "예",
    "4h 실시간 신호 207개 중 20배 가능 58%")
row(C, "크기 규칙 하나 (policy)", "일부",
    "OwnerPolicy(증거금=레버리지%, quality_v1 50/40/30/20배; Settings가 20배 미만·증거금 20% 미만을 거부), "
    "RecommendedPolicy(1%, 맞는 것 중 가장 낮은 레버리지 ≤10배, 3 ATR; 옛 live.py v2에서만 씀)",
    "두 분이 (다) RecommendedPolicy 그대로 / (라) 1% + 가장 높은 가능 레버리지(≤50, 최저 3, 1 ATR) 중 택일. "
    "(라)면 새 클래스 하나", "S", 0.5, "결정",
    "세 번째 크기 규칙이 생기면 쌍둥이·동전도 따라 바꿔야 함")
row(C, "트레이더 간 노출 한도 (코인·방향 3, 같은 묶음 1, 책 같은 방향 8) + REJECTED_CAP 그림자", "없음",
    "엔진은 각자 single_position만. 계좌 사이 한도 없음",
    "AI 서비스 위험 관리자(제출 전), 막힌 진입은 REJECTED_CAP + 쌍둥이", "S", 1, "예",
    "한 사건에 1%가 3~5%가 됨")
row(C, "손실 제한: 트레이더 하루 −3R, 1% 곡선 −15% 중지, 책 하루 −12R", "일부",
    "policy.RiskGuards: UTC 하루 시작 잔고 대비 %, N연패 쉬기(엔진별). risk.py는 실전 주문기용",
    "R 단위 하루 한도, 책 전체 한도(계좌 사이), −15% 가망 없음 중지 기록", "S", 1, "예",
    "하루 기준 09:00 KST(UTC)로 통일")
row(C, "기존 규칙: 3연패 1시간 쉼, 손절 뒤 2봉 재진입 금지, 발표 진입 금지, 파산선", "일부",
    "RiskGuards(연패 쉬기, 기본 5연패 24시간), bust_below(v4 10 USDT; 설계 1,000). 재진입 금지·발표 금지 없음",
    "설정값 + 재진입 금지 + events.near 기반 금지", "S", 0.5, "예", "—")
row(C, "보유 중 깨움 (자기 봉 마감, ±1.0R, 반대 신호, 발표)", "없음", "—",
    "감시 루프(1분) → 깨움 큐, 허용 행동 검사(손절은 수익 쪽만)", "M", 1.5, "예",
    "포함한다면 D0부터(중간 추가 = 잠금 변경)")

D = "D AI 서비스·비용"
row(D, "규칙 봇 → AI 신호 전달", "없음",
    "extras.post_boundary 훅은 러너 루프 안에서 동기 실행(여기서 AI를 부르면 331계좌 손절 처리가 멈춤, WatchdogSec=600). "
    "signal_log는 경계의 DeepSeek 계산 뒤 커밋(15m 평균 27.2초, 4h 38.8초, 최대 46.3초)",
    "별도 프로세스가 paper3.db signal_log를 읽기 전용으로 따라 읽음(권장) 또는 훅에서 큐에 넣기만", "S", 1, "예",
    "설계 15-3은 AI 경로에서 paper3.db를 열지 말라고 함(초기화 거부)")
row(D, "별도 AI 판단 프로그램 (20초 마감, 무응답 이유별 기록, 구조화 출력, 재시도 0~1, 캐시)", "없음",
    "본보기: agents/debate.py call_api(urllib Messages API, 재시도, 오류 분류, 키 가림, effort·thinking), "
    "paperbot-debate.service(전용 사용자·env·MemoryMax)",
    "aibot 서비스: 큐, 호출당 timeout ≤20초, max_retries 0, output_config.format 스키마, response.model 확인", "L", 3,
    "예", "20초 안 답 비율 미측정(7~9천 토큰+생각)")
row(D, "비용 계산기·상한 (두 단계 예산, 트레이더별 하루 몫)", "일부",
    "debate.cost_of(usage → USD, 캐시 읽기·쓰기 포함), 하루·달·시간 상한, 최악 비용 사전 검사, 80% 경고/95% 중지. "
    "단 하루 = KST 00:00, 토론방 전용",
    "복사(vendor)해서 09:00 KST 하루, 트레이더 몫, 1차/2차 단계표, '예산 건너뜀'은 무응답과 따로", "S", 1, "예",
    "상한 없이 유료 호출 금지")
row(D, "키·작업 공간 분리", "일부", "debate.env 방식(키는 env 파일만, 전용 사용자, 로그에서 가림)",
    "aibot.env, 전용 작업 공간·한도(두 분)", "S", 0.25, "예", "키를 채팅에 붙이지 않기")
row(D, "0차 재생 시험 도구 + 무료 토큰 세기", "없음", "본보기: debate once --dry-run(비용 추정)",
    "저장된 v4 신호로 화면 만들고 호출, 비용·지연·형식 오류 측정", "S", 1, "예", "10/14~15에 필요")
row(D, "'판단만' 24시간 모드", "없음", "—", "계좌 반영 없이 판단·기록만 하는 스위치", "S", 0.25, "예", "—")
row(D, "화면 결정성·미래 자료 감사", "없음", "—", "같은 입력 두 번 = 같은 바이트, known_at ≤ 판단 시각 검사", "S", 0.5,
    "예", "미래 15분만 보여도 가짜 효과(보고서 12-2)")

E = "E 계좌·복구·판정·운영"
row(E, "AI 계좌 종류 + 재시작 복구", "없음",
    "engine_state/restore_engine, AccountBook.load, extras GuardedEngine/HeldEngine는 있음. "
    "paper3.db에 새 kind를 넣으면 kind로 나누는 모듈 17개 이상(checkpoint, daily3, resetrun, dash, …)이 영향",
    "aibot.db에 별도 AccountBook(같은 엔진 코드), 재시작 때 진행 중 요청 = '오류(중단)', 빠진 분은 live_bars로 되감기",
    "M", 2, "예", "같은 DB에 넣으면 규칙 봇 판정·초기화에 섞임")
row(E, "규칙 봇 11/04 판정·초기화에서 AI 분리", "없음",
    "checkpoint.account_family: 모르는 kind는 'core' 묶음으로(572행). resetrun은 paper3.db를 통째로 보관 이동",
    "별도 DB면 자동 해결; 같은 DB면 checkpoint·daily3·resetrun 수정", "S", 0.5, "예",
    "AI 계좌가 규칙 봇 BH 묶음에 몰래 들어감")
row(E, "사전 등록 파일 + 지문", "일부",
    "runinfo.run_record(trading_code·settings·rules·signal_code·brackets·packages 지문 → runs), "
    "docs/paper-v4-verdict.md가 checkpoint.py sha256 기록",
    "docs/aibot-v1-prereg.md(트레이더·봉·동전 범위·판정식·한도·지시문) + LOCK_MANIFEST.json + 시작 때 지문 검사",
    "S", 1, "예", "D0 뒤에 쓰면 사전 등록이 아님")
row(E, "판정 코드 (AI−규칙 짝, 두 동전, 날짜·주 묶음, BH(K), 100건·반 40건, 30일째 가망 없음)", "없음",
    "checkpoint.py는 규칙 봇용(30/60/90일, 동전 봇, 묶음). 재사용: 스냅숏·지문, BH, 동전 봇, analyze.bh/boot_mean",
    "aibot/verdict.py + 이기는/지는/무작위를 심은 가짜 자료 시험", "M", 2, "아니오",
    "판정식은 D0 전에 문서로 잠가야 함(코드는 첫 리허설 전까지)")
row(E, "분석 보고서 (R 먼저, 날짜 묶음 CI, BH, 최소 검출 크기, 짝 분해, 다시 묻기, 확신 눈금, 판단 일관성)", "일부",
    "analyze.py: R·cost_R 표, BH, MDE(동전·뒤집기), 묶음 부호 뒤집기 검정(1h 묶음), 동전 풀. "
    "lens 1회용: 날짜 묶음(context_filters/stats_util.py), 무작위 시각(luck_flow/luck.py). "
    "없음: 짝 분해, 다시 묻기 분석, 브라이어·스피어만, 일관성, 트레이더별 MDE 표",
    "aibot/report.py (기록에서 소급 계산 가능)", "M", 3, "아니오", "2주째 sd 재측정(약 10/27) 전에 필요")
row(E, "대시보드 AI 탭", "없음", "dash/app.py(FastAPI, 읽기 전용, 그룹 보기)", "AI 탭 또는 :8081 복사본", "M", 2,
    "아니오", "—")
row(E, "텔레그램 (AI 전용 봇·방)", "일부", "notify.py TelegramNotifier/Router/Digest, tgsends 카운터",
    "AI 전용 토큰·방, 비용·무응답·지문 경고", "S", 0.5, "예(경고만)", "규칙 봇 알림이 밀림")
row(E, "백업", "일부", "deploy/paperbot-backup.sh(VACUUM INTO, 14일) + offsite.py DB_NAMES(시험이 같음을 확인)",
    "aibot.db와 압축 화면을 두 목록에 추가", "S", 0.25, "예", "판단 원문은 다시 만들 수 없음")
row(E, "되돌리기 스위치", "일부", "extras.json pause_activation, --no-extras, 실전 주문기 kill_file 방식",
    "AI_ENABLED 파일(매 poll 다시 읽음): 끄면 호출 0, AI 계좌는 'AI 꺼짐'으로 기록; 트레이더별 정지", "S", 0.5, "예",
    "—")
row(E, "시험 (pytest)", "일부", "tests 254개(엔진, extras 격리·일치, 토론방 등)",
    "스키마·마감·예산·쌍둥이 일치·한도·재시작·판정 가짜 자료", "M", 2, "예", "—")
