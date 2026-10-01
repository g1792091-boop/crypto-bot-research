# 경제지표 발표 전후 표시 (손실 카드)

## 무엇인가

손실 카드에 붙는 태그 **"경제지표 발표 전후"** 는 거래의 **진입 시각 또는 청산 시각**이
미국 경제지표 발표 시각 근처였다는 뜻입니다. 대상 발표는 네 가지입니다.

| 종류 | 내용 | 보통 발표 시각 (미국 동부 시간) |
|---|---|---|
| CPI | 소비자물가지수 | 08:30 |
| FOMC | 연준 금리 결정(성명 발표) | 14:00 |
| NFP | 고용보고서(Employment Situation) | 08:30 |
| PCE | 개인소득·지출(PCE 물가) | 08:30 |

이 시간대에는 코인 가격이 크게 흔들리는 일이 많아서, 손실이 발표 때문에 생긴 것인지 따로 볼 수
있게 표시만 합니다. 다른 태그와 마찬가지로 **설명용 표시이며 매매 규칙이 아닙니다.**

## 기준 구간

- 발표 **30분 전부터 2시간 후까지** (양 끝 포함).
- 진입이나 청산 중 **하나라도** 이 구간에 들어가면 태그가 붙습니다.
  진입은 발표 한참 전, 청산은 발표 한참 뒤라서 둘 다 구간 밖이면, 보유 중에 발표가 있었어도
  태그는 붙지 않습니다.
- 카드 데이터 `card["macro"]`에 걸린 발표의 종류, UTC 시각, 출처 주소, 그리고 진입 쪽(`entry`)인지
  청산 쪽(`exit`)인지가 들어갑니다.
- 구간 값은 `paperbot/cards.py`의 `MACRO_BEFORE_MS`, `MACRO_AFTER_MS`입니다.

## 일정 파일

`data/macro_events.csv` 한 줄이 발표 한 건입니다.

```
ts_utc,kind,source_url
2027-03-17T18:00:00Z,FOMC,https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
```

(위 줄은 형식 예시입니다. 실제 날짜는 아래 "출처"에서 확인한 것만 넣습니다.)

- `ts_utc`: **UTC** 시각. 끝에 `Z`를 붙입니다.
- `kind`: `CPI`, `FOMC`, `NFP`, `PCE` 중 하나.
- `source_url`: 날짜를 확인한 공식 페이지 주소 (필수).
- `#`으로 시작하는 줄과 빈 줄은 무시됩니다.

파일이 없거나 비어 있으면 태그는 절대 붙지 않습니다(오류도 나지 않음). 형식이 틀린 줄은 건너뜁니다.

### 추가하는 방법

미국 서머타임 때문에 같은 08:30이라도 UTC로는 12:30(여름) 또는 13:30(겨울)입니다. 손으로 계산하지
말고 아래 명령으로 줄을 만들어 붙여 넣으세요. 시각을 생략하면 종류별 보통 시각(위 표)을 씁니다.
(아래 날짜는 형식 예시이며 실제 발표일로 확인한 것이 아닙니다.)

```
python -m paperbot.events line CPI 2026-10-14 https://www.bls.gov/schedule/news_release/cpi.htm
python -m paperbot.events line FOMC 2027-03-17 https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
python -m paperbot.events line PCE 2026-10-30 10:00 https://www.bea.gov/news/schedule   # 보통과 다른 시각일 때 (ET)
```

FOMC는 이틀 회의의 **둘째 날**(성명 발표일) 날짜를 넣습니다.

붙여 넣은 뒤 확인:

```
python -m paperbot.events check
```

문제가 있는 줄 번호와 이유, 종류별 건수가 나옵니다. 파일은 프로그램이 처음 쓸 때 한 번 읽으므로,
고친 뒤에는 대시보드/봇을 다시 시작해야 반영됩니다.

일정이 바뀌면(정부 셧다운 등으로 발표 연기) 해당 줄을 고치고 출처 주소도 바뀐 공지로 바꿉니다.

## 출처 (공식 페이지만)

- FOMC: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- CPI: https://www.bls.gov/schedule/news_release/cpi.htm
- 고용보고서(NFP): https://www.bls.gov/schedule/news_release/empsit.htm
- PCE(개인소득·지출): https://www.bea.gov/news/schedule

뉴스, 블로그, 경제 캘린더 사이트의 날짜는 넣지 않습니다.

## 아직 비어 있는 것 (2026-10-01 기준)

**현재 `data/macro_events.csv`에는 머리글만 있고 일정이 한 건도 없습니다.** 그래서 지금은 이 태그가
어떤 카드에도 붙지 않습니다.

이유: 작업 환경의 네트워크에서 위 공식 사이트 세 곳(federalreserve.gov, bls.gov, bea.gov)이 모두
차단되어 페이지를 직접 열 수 없었습니다. 검색 결과 요약에 일부 날짜가 보였지만 공식 페이지를 직접
확인한 것이 아니고 빠진 날짜도 있어서 넣지 않았습니다.

채워야 할 범위:

| 종류 | 확인용 과거 구간 | 앞으로 구간 |
|---|---|---|
| CPI | 2025-01 ~ 2026-09 | 2026-10 ~ 2027-12 (BLS가 2027년 일정을 공개한 만큼) |
| FOMC | 2025-01 ~ 2026-09 | 2026-10 ~ 2027-12 |
| NFP | 2025-01 ~ 2026-09 | 2026-10 ~ 2027-12 (공개된 만큼) |
| PCE | 2025-01 ~ 2026-09 | 2026-10 ~ 2027-12 (공개된 만큼) |

주의할 점:
- 2025년 10~11월 미국 정부 셧다운으로 BLS 발표 일부가 연기·취소되었습니다. 과거 구간은 원래
  일정표가 아니라 **실제 발표일**(BLS 보도자료 보관 페이지, 예: `https://www.bls.gov/bls/news-release/cpi.htm`)
  기준으로 넣어야 합니다.
- FOMC 일정은 "직전 회의에서 확정될 때까지 잠정"입니다. 임시 회의는 공지가 나오면 추가합니다.
- 공식 사이트에 접속할 수 있는 컴퓨터에서 위 "추가하는 방법"대로 한 줄씩 넣으면 됩니다. 넣은 뒤에는
  `check`로 확인하고, 한 사람이 더 출처와 대조하는 것을 권합니다(docs/trade-review-system.md의
  "고영향 일정은 사람이 승인" 원칙).
