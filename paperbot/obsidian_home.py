"""Home dashboard, system map (note + canvas), reading guide and vault status of the Obsidian vault exporter."""

from __future__ import annotations

import json
from collections import Counter

from .obsidian_notes import (FOLDERS, LEGEND, PERIOD_DAYS, Ctx, Vault, check_name, day_name, hero, initial_equity, stat_row,
                             strat_link, week_name)
from .obsidian_sources import split_account
from .obsidian_util import (MOCHA, TYPE_COLORS, badge, bar, callout, fnum, iso_week, kst_day, kst_dt, kst_min, link, mermaid,
                            pct, table, usd)

FLOW = """flowchart LR
  BN(["바이낸스 공개 시세"]) --> L3["live3 모의 매매 엔진<br/>(156개 계좌, 주문 없음)"]
  L3 --> P3[("paper3.db")]
  P3 --> D3["밤 점검 09:20"]
  D3 --> DB3[("daily3.db")]
  P3 --> CP["체크포인트 판정<br/>(30일마다)"]
  CP --> CPD[("checkpoint.db")]
  P3 --> AG["에이전트 회의 (15분마다)"]
  DB3 --> AG
  CPD --> AG
  AG --> A3[("agents3.db<br/>회의·메모·시험 장부")]
  DASH["대시보드 (두 분 글·승인)"] --> IN[("inbox.db")]
  IN --> AG
  P3 --> OB["옵시디언 내보내기 (읽기 전용)"]
  DB3 --> OB
  CPD --> OB
  A3 --> OB
  IN --> OB
  RP["저장소 문서·연구 요약"] --> OB
  OB --> V{{"이 볼트 (마크다운 파일)"}}
  V --> OWN(["두 분: 폰·PC에서 읽기"])
  OWN -.->|"메모는 99 내 메모에만"| V"""


def build_home(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    ini = initial_equity(ctx)
    start, ref = ctx.run_start_ms, (d.snapshot_ms or ctx.now_ms)
    day_no = min(ctx.day_no, PERIOD_DAYS)
    n_acc = len(d.accounts)
    n_tr = sum(s["n"] for a, s in d.trade_stats.items() if d.accounts.get(a, {}).get("kind") == "strategy")
    strat_eq = [e for a, (e, _) in d.equity.items() if d.accounts.get(a, {}).get("kind") == "strategy" and e is not None]
    busts = sum(1 for a, e in d.engines.items() if e.get("bust") and d.accounts.get(a, {}).get("kind") == "strategy")
    obs_left = max(0, int((ctx.obs_end_ms - ref) // 86_400_000))
    cp_left = max(0, int((ctx.cp1_ms - ref) // 86_400_000))
    last_day = ctx.days[-1] if ctx.days else None
    last_check = d.daily[-1]["day"] if d.daily else None
    # equity histogram of strategy accounts (information, not a ranking)
    bins = [("$4,000 미만", lambda e: e < 4000), ("$4,000~5,000", lambda e: 4000 <= e < 5000),
            ("$5,000~6,000", lambda e: 5000 <= e < 6000), ("$6,000 이상", lambda e: e >= 6000)]
    hist = [[name, sum(1 for e in strat_eq if f(e))] for name, f in bins]
    reasons = Counter()
    for a, s in d.trade_stats.items():
        if d.accounts.get(a, {}).get("kind") == "strategy":
            reasons["익절 잠금"] += s["lock"]
            reasons["손절"] += s["sl"]
            reasons["강제청산"] += s["liq"]
    pie = ""
    if sum(reasons.values()) > 0:
        pie = mermaid('pie showData title 끝난 거래의 마감 이유 (매매법 계좌)\n' +
                      "\n".join(f'  "{k}" : {c}' for k, c in reasons.items() if c))
    def g(ms):
        return kst_dt(ms).strftime("%Y-%m-%d %H:%M")
    gantt = f"""gantt
  title 30일 고정 실험 (한국 시간)
  dateFormat YYYY-MM-DD HH:mm
  axisFormat %m-%d
  section 실험
  관찰 기간 21일 :{'done' if ref >= ctx.obs_end_ms else 'active'}, obs, {g(start)}, {g(ctx.obs_end_ms)}
  규칙·코드 고정 30일 :{'done' if ref >= ctx.cp1_ms else 'active'}, frz, {g(start)}, {g(ctx.cp1_ms)}
  section 판정
  1차 체크포인트 :milestone, cp1, {g(ctx.cp1_ms)}, 0d"""
    body = [
        hero("Paper v3 연구실", "36개 매매법 · 156개 모의 계좌 · 72명의 AI 직원 — 두 분을 위한 지식 볼트"),
        LEGEND + "\n",
        callout("pb-stat", f"지금 {min(day_no + 1, PERIOD_DAYS)}일째 / 30일 " + badge("code").replace("\n", ""),
                f"<progress value=\"{day_no}\" max=\"{PERIOD_DAYS}\"></progress> `{bar(day_no / PERIOD_DAYS)}`\n\n" +
                stat_row([("실험 시작", kst_day(start)), ("관찰 기간 끝", f"{kst_day(ctx.obs_end_ms)} (D-{obs_left})"),
                          ("1차 체크포인트", f"{kst_day(ctx.cp1_ms)} (D-{cp_left})"), ("계좌", str(n_acc or "-")),
                          ("끝난 거래", f"{n_tr}건"), ("파산 계좌", str(busts))]).rstrip()),
        callout("warning", "30일 전에는 결론이 없습니다",
                "아래 숫자는 모두 중간 기록입니다. 매매법이 실력이 있는지는 첫 체크포인트에서 코드가 동전 봇 2,000개와 비교해 "
                "판정합니다. 표본이 10건 미만이면 '표본 적음', 30건 미만이면 판정 보류 수준으로 표시합니다."),
        "## 바로가기",
        table(["바로가기", "무엇이 있나요"], [
            [link("실험 개요", "01 실험"), "규칙 한눈에 · 타임라인 · 레버리지 계단 · 체크포인트 판정"],
            [link("매매법 목록", "02 매매법"), "36개 매매법 카드 (실전 기록·좋은 자리 vs 보통·그림자·5년 성격)"],
            [link("직원 목록", "03 직원"), "조직도 · 팀 12개 · 역할 36명 · 성적표"],
            [link("회의 목록", "04 회의"), "하루 한 장의 회의 기록 · 주간 · 손실 복기 · 시세 급변"],
            [link("교훈과 가설", "05 교훈·가설"), "교훈 · 가설 장부(채점) · 시험 장부(우연 보정)"],
            [link("연구 지도", "06 연구"), "5년 연구 · 익절/레버리지/손절 · DeepSeek 200개 분류"],
            [link("매일 점검 목록", "07 매일 점검"), "밤마다 paper와 재계산 일치 · 데이터 · 비용 · 그림자"],
            [link("규칙 문서 목록", "08 규칙·문서"), "고정 규칙 원문 사본과 해시"],
            ["99 내 메모", "두 분이 직접 쓰는 곳. 이 폴더는 자동 갱신이 절대 건드리지 않습니다"],
            [link("읽는 법"), "처음 보시는 분은 이것부터 (용어 풀이 · 그래프 색 · 폰에서 쓰는 법)"],
            [link("시스템 지도"), "자료가 어디서 어디로 흐르는지 그림"],
        ]),
        "## 최근",
        "- 회의: " + (link(day_name(last_day), last_day) if last_day else "아직 없음")
        + "\n- 밤 점검: " + (link(check_name(last_check), last_check) if last_check else "아직 없음")
        + "\n- 이번 주: " + (link(week_name(iso_week(last_day)), iso_week(last_day)) if last_day else "-"),
        "## 계좌 평가금 분포 " + badge("code"),
        (table(["구간", "매매법 계좌 수"], hist, ["l", "r"]) +
         f"\n시작 금액 {usd(ini)}. 순위가 아니라 분포입니다.\n") if strat_eq else "아직 계좌 자료가 없습니다.\n",
        pie,
        "## 30일 일정\n" + mermaid(gantt),
        "## 자료는 이렇게 흐릅니다\n" + mermaid(FLOW),
        callout("info", "이 볼트는 어떻게 만들어지나요",
                "매일 09:50(KST) 서버가 에이전트의 DB와 저장소 문서를 **읽기만 해서** 이 마크다운 파일들을 새로 만듭니다. "
                "원본 기억(DB)은 그대로이고, 여기서 고친 것은 원본에 반영되지 않습니다. 직접 쓰는 메모는 `99 내 메모`에 두세요. "
                "갱신 시각과 자료 기준 시각은 각 노트 맨 위의 작은 글씨에 있습니다."),
        "\n" + link("볼트 상태"),
    ]
    v.add(FOLDERS["home"], "홈", "\n".join(x for x in body if x), type="허브", tags=["허브", "홈"], css=("pb-home",), source="mixed",
          props={"date": kst_day(ref), "n_trades": n_tr, "small_sample": n_tr < 10})


def build_guide(v: Vault) -> None:
    ctx = v.ctx
    legend_rows = [["허브 (목록·지도)", "노랑", "tag:#허브"], ["전략 (매매법)", "보라", "tag:#전략"], ["회의", "파랑", "tag:#회의"],
                   ["교훈", "초록", "tag:#교훈"], ["가설", "주황", "tag:#가설"], ["연구", "청록", "tag:#연구"],
                   ["규칙·문서", "빨강", "tag:#규칙"], ["직원", "분홍", "tag:#직원"], ["밤 점검", "하늘", "tag:#점검"],
                   ["시험 장부", "적갈", "tag:#시험"], ["실험", "연보라", "tag:#실험"]]
    gloss = [
        ["ROE", "투자한 증거금 대비 수익률. 레버리지가 크면 같은 가격 움직임에도 ROE가 크게 움직입니다."],
        ["ATR", "최근 가격이 보통 얼마나 출렁이는지의 크기. 손절 거리를 2 × ATR로 정합니다."],
        ["레버리지", "빌려서 크게 거는 배수. 클수록 이기면 크게, 지면 크게 잃고 청산(강제 종료) 위험이 커집니다."],
        ["파산", "계좌 평가금이 $10 아래로 떨어져 그 계좌를 멈춘 것."],
        ["동전 던지기 봇", "신호와 방향을 우연으로 정하는 봇. 실력이 없는 쪽의 기준선입니다."],
        ["p값", "실력이 없어도 이만큼 나올 확률. 작을수록 우연이 아닐 가능성이 큽니다."],
        ["FDR 10%", "여러 계좌를 한꺼번에 볼 때 우연히 합격하는 것을 걸러내는 보정."],
        ["체크포인트", "시작 후 30일마다 코드가 모든 계좌를 한 번에 판정하는 날."],
        ["그림자", "계좌 없이 '만약 이렇게 했다면'을 기록만 하는 것. 규칙은 바꾸지 않습니다."],
        ["표본 적음", "거래가 10건 미만이라 우연이 결과를 설명할 수 있다는 표시(30건 미만은 판정 보류 수준)."],
    ]
    body = [hero("읽는 법", "처음 보시는 분을 위한 안내"), LEGEND + "\n",
            "## 이 볼트는\n- 에이전트(AI 직원)가 쌓은 지식을 읽기 쉽게 옮긴 것입니다. **원본이 아닙니다.**\n"
            "- 숫자는 코드가 계산한 것만 믿으세요. 회의 글은 AI가 썼고 틀릴 수 있습니다(`AI 작성` 표시).\n"
            "- 30일 체크포인트 전에는 어떤 것도 결론이 아닙니다.\n",
            "## 폰·PC에서 쓰는 법\n1. 왼쪽(폰은 왼쪽 가장자리 스와이프)에서 **홈**을 엽니다.\n"
            "2. 검색: 돋보기에서 매매법 이름(예: 슈퍼트렌드)이나 날짜를 입력합니다.\n"
            "3. 그래프: 왼쪽 메뉴의 그래프 아이콘. 점 하나가 노트 하나이고, 색은 종류입니다. 큰 점은 연결이 많은 목록입니다.\n"
            "4. 내 메모: `99 내 메모` 폴더에 새 노트를 만드세요. 자동 갱신이 절대 지우지 않습니다.\n"
            "5. 다른 폴더의 노트를 고치면 다음 갱신 때 되돌아오거나(원본이 바뀐 경우) 그대로 남습니다(고친 경우). "
            "남기고 싶은 글은 `99 내 메모`로 복사하세요.\n",
            "## 그래프 색\n" + table(["종류", "색", "그래프 필터"], legend_rows),
            "## 용어 풀이\n" + table(["말", "뜻"], gloss),
            callout("danger", "실제 돈이 아닙니다", "모의(paper) 계좌입니다. 에이전트는 주문을 낼 수 없고 규칙과 계좌를 바꿀 수 없습니다."),
            "\n" + link("홈") + " · " + link("볼트 상태")]
    v.add(FOLDERS["home"], "읽는 법", "\n".join(body), type="허브", tags=["허브", "안내"], css=("pb-hub",), source="doc")


def build_system_map(v: Vault) -> None:
    body = [hero("시스템 지도", "자료가 어디서 만들어져 어디로 가는지. 이 볼트는 맨 끝의 읽기 전용 사본입니다"),
            mermaid(FLOW),
            "## 한 줄씩\n- **live3**: 바이낸스 공개 시세로 156개 모의 계좌를 돌립니다. 주문은 없습니다.\n"
            "- **밤 점검 / 체크포인트**: 어제를 다시 계산해 맞춰 보고, 30일마다 공식 판정을 합니다.\n"
            "- **에이전트 회의**: 15분마다 한 번, 회의가 필요한 방만 엽니다. 기억은 agents3.db에 쌓입니다.\n"
            "- **대시보드**: 두 분이 글을 쓰고 승인을 누르는 곳. inbox.db의 유일한 기록자입니다.\n"
            "- **옵시디언 내보내기**: 위 DB와 저장소 문서를 읽기만 하고 이 볼트를 새로 만듭니다.\n",
            "캔버스 버전: `시스템 지도.canvas`\n\n" + link("홈") + " · " + link("읽는 법")]
    v.add(FOLDERS["home"], "시스템 지도", "\n".join(body), type="허브", tags=["허브", "그림"], css=("pb-hub",), source="doc")
    nodes = [
        ("bn", "text", "**바이낸스**\n공개 시세(읽기)", 0, 0, "1"), ("l3", "text", "**live3 엔진**\n156개 모의 계좌\n주문 없음", 320, 0, "4"),
        ("p3", "text", "`paper3.db`\n거래·평가금", 640, 0, "3"), ("d3", "text", "**밤 점검**\n09:20 KST\n`daily3.db`", 640, 180, "5"),
        ("cp", "text", "**체크포인트**\n30일마다\n`checkpoint.db`", 640, 360, "5"), ("ag", "text", "**에이전트 회의**\n15분마다\n`agents3.db`", 960, 180, "6"),
        ("ds", "text", "**대시보드**\n두 분 글·승인\n`inbox.db`", 960, 400, "2"), ("ob", "text", "**옵시디언 내보내기**\n읽기 전용\n매일 09:50", 1280, 180, "4"),
        ("home", "file", f"{FOLDERS['home']}/홈.md", 1600, 60, "6"), ("memo", "text", "**99 내 메모**\n두 분이 쓰는 곳\n(내보내기가 안 건드림)", 1600, 300, "3"),
    ]
    cn, ce = [], []
    for nid, typ, val, x, y, col in nodes:
        n = {"id": nid, "type": typ, "x": x, "y": y, "width": 260, "height": 110, "color": col}
        n["text" if typ == "text" else "file"] = val
        cn.append(n)
    edges = [("bn", "l3"), ("l3", "p3"), ("p3", "d3"), ("p3", "cp"), ("p3", "ag"), ("d3", "ag"), ("cp", "ag"), ("ds", "ag"),
             ("ag", "ob"), ("p3", "ob"), ("ob", "home"), ("ob", "memo")]
    for i, (a, b) in enumerate(edges):
        ce.append({"id": f"e{i}", "fromNode": a, "fromSide": "right", "toNode": b, "toSide": "left"})
    v.canvases[f"{FOLDERS['home']}/시스템 지도.canvas"] = json.dumps({"nodes": cn, "edges": ce}, ensure_ascii=False, indent=1)


def build_status(v: Vault) -> None:
    """Last: counts what the others made."""
    ctx, d = v.ctx, v.ctx.data
    by_folder = Counter(p.split("/")[0] for p in v.files)
    rows = [[name, "있음" if d.present.get(k) else "없음(비어 있는 것으로 처리)"] for k, name in
            (("paper3", "paper3.db (거래·평가금)"), ("daily3", "daily3.db (밤 점검)"), ("agents3", "agents3.db (회의·시험 장부)"),
             ("checkpoint", "checkpoint.db (판정)"), ("inbox", "inbox.db (두 분 글)"))]
    frows = [[f, by_folder.get(f, 0)] for f in sorted(by_folder)]
    body = [hero("볼트 상태", "마지막 갱신과 자료 상태"), LEGEND + "\n",
            stat_row([("노트 수", str(len(v.files) + 1)), ("자료 있음", f"{sum(1 for x in d.present.values() if x)}/5")]),
            "## 자료 " + badge("code"), table(["자료", "상태"], rows),
            "## 폴더별 노트 수\n" + table(["폴더", "노트"], frows, ["l", "r"]),
            callout("info", "자동 갱신 규칙", "- 이 볼트의 노트는 매일 서버가 새로 만듭니다 (내용이 바뀐 노트만 다시 씁니다).\n"
                    "- `99 내 메모`와 직접 만든 파일은 절대 지우거나 고치지 않습니다.\n"
                    "- 자동 생성 노트를 직접 고치면 그 파일은 더 이상 덮어쓰지 않습니다(고친 것을 지키기 위해). 되돌리려면 그 파일을 지우세요.\n"
                    "- `.obsidian` 설정도 직접 바꾸신 파일은 건드리지 않습니다."),
            "\n" + link("홈") + " · " + link("읽는 법")]
    v.add(FOLDERS["home"], "볼트 상태", "\n".join(body), type="허브", tags=["허브", "상태"], css=("pb-hub",), source="code")
