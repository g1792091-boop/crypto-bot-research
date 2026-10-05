// 서버·비용 › 가동 기록 (wave 3, ranked #14): 7 or 30 Korea-time days x 24 hours of pixel cells, each one coloured by
// how many of that hour's minutes the bot really stepped (paper3.db live_bars, GET /api/v4/uptime, dash/more/uptime.py),
// with the restarts (runs) and each night's check (daily3 reports) marked. One line on top: '7일 가동 99.6% · 멈춤 2번
// (총 14분)'. Nothing is drawn for hours before the run or still ahead. Asked every 2 minutes while shown (paused while
// hidden); its look: server-uptime.css.
import {h, put, ui, fmt, motion} from "../core/pb.js";

const API = "/api/v4/uptime";
const REFRESH_MS = 120000;
const WD = ["일", "월", "화", "수", "목", "금", "토"];

function ensureCss() {
  if (document.querySelector("link[data-up-kit]")) return;
  document.head.append(h("link", {rel: "stylesheet", href: "/static/v4/screens/server-uptime.css", dataset: {upKit: "1"}}));
}

const dayLabel = (ts) => { const k = new Date(ts + 9 * 3600000); return `${k.getUTCMonth() + 1}/${k.getUTCDate()} ${WD[k.getUTCDay()]}`; };
const pctKo = (x) => (x == null ? "—" : `${(Math.floor(x * 1000) / 10).toFixed(1)}%`);      // floored: never rounds up to 100 %

export function uptimeCard(ctx) {
  ensureCss();
  let days = 7;
  const headline = h("p", {class: "up-line"}, motion.shimmer(1));
  const grid = h("div", {class: "up-grid", role: "table", "aria-label": "날짜별 시간마다 봇이 처리한 분"});
  const detail = h("p", {class: "up-detail"}, "칸을 누르면 그 시간의 숫자가 나옵니다.");
  const stops = h("div", {class: "up-stops"});
  const seg = ui.seg([{id: "7", label: "7일"}, {id: "30", label: "30일"}], "7", (id) => { days = +id; load(true); }, {label: "기간"});
  const card = ui.card({plate: "가동 기록", cls: "up-card", sub: "시간마다 봇이 실제로 처리한 분"}, seg, headline,
    h("div", {class: "up-scroll"}, grid), detail,
    h("p", {class: "up-legend"}, h("span", null, h("i", {class: "up-sw full"}), " 60분 다 처리"), h("span", null, h("i", {class: "up-sw part"}), " 일부 빠짐"),
      h("span", null, h("i", {class: "up-sw zero"}), " 멈춤"), h("span", null, h("i", {class: "up-sw rs"}), " 재시작"), h("span", null, h("i", {class: "up-sw nt"}), " 밤 점검"),
      h("span", null, h("i", {class: "up-sw na"}), " 시작 전·아직")),
    stops,
    ui.note("1분봉을 실제로 처리한 기록(live_bars)으로 셉니다. 꾸민 숫자는 없습니다. 밤 점검 = 그날 거래를 다시 계산해서 계좌가 모두 같은지 본 결과."));

  function render(d) {
    if (!d || !d.ready) { put(headline, h("span", {class: "muted"}, (d && d.why) || "아직 기록이 없습니다.")); put(grid); put(stops); return; }
    const sh = d.share;
    const tone = sh == null ? "" : sh >= 0.995 ? "up" : sh >= 0.95 ? "warn" : "down";
    put(headline, h("b", {class: "up-big " + tone}, `${d.days}일 가동 ${pctKo(sh)}`),
      h("span", null, d.stops_n ? ` · 멈춤 ${fmt.int(d.stops_n)}번 (총 ${fmt.int(d.stops.reduce((a, x) => a + x.min, 0))}분)` : " · 멈춤 없음"),
      d.missing_min && d.missing_min > (d.stops || []).reduce((a, x) => a + x.min, 0) ? h("span", {class: "muted"}, ` · 그 밖에 빠진 분 ${fmt.int(d.missing_min - d.stops.reduce((a, x) => a + x.min, 0))}분`) : null,
      d.restarts && d.restarts.length ? h("span", {class: "muted"}, ` · 재시작 ${fmt.int(d.restarts.length)}번`) : null);
    const rsHours = new Set((d.restarts || []).map((r) => Math.floor((r.ts - d.first_day) / 3600000)));
    const nights = new Map((d.nightly || []).map((n) => [n.day, n]));
    const head = h("div", {class: "up-row up-hrs", role: "row", "aria-hidden": "true"}, h("span", {class: "up-k"}),
      Array.from({length: 24}, (_, hr) => h("span", {class: "up-hr"}, hr % 6 === 0 ? String(hr) : "")), h("span", {class: "up-nk"}, "밤"));
    const rows = d.rows.slice().reverse().map((r) => {
      const di = d.rows.indexOf(r);
      const night = nights.get(r.day);
      const ntxt = night ? `${r.day} 밤 점검: ${night.accounts != null ? `${fmt.int(night.accounts - (night.mismatched || 0))}/${fmt.int(night.accounts)} 일치` : "기록 있음"}` : `${r.day} 밤 점검 기록 없음`;
      return h("div", {class: "up-row", role: "row"}, h("span", {class: "up-k", role: "rowheader"}, dayLabel(r.ts)),
        r.h.map((c, hr) => {
          const rs = rsHours.has(di * 24 + hr);
          let cls = "na", txt = `${dayLabel(r.ts)} ${String(hr).padStart(2, "0")}시 · `;
          if (c === -1) txt += "아직";
          else if (!Array.isArray(c)) txt += "시작 전";
          else {
            const [got, exp] = c;
            cls = exp === 0 ? "na" : got >= exp ? "full" : got === 0 ? "zero" : "part";
            txt += exp ? `${fmt.int(got)}/${fmt.int(exp)}분 처리` : "시작 전";
          }
          if (rs) txt += " · 재시작";
          return h("button", {type: "button", class: `up-c ${cls}${rs ? " rs" : ""}`, role: "cell", title: txt, "aria-label": txt,
            onclick: (e) => { detail.textContent = txt; for (const b of grid.querySelectorAll(".up-c.sel")) b.classList.remove("sel"); e.currentTarget.classList.add("sel"); }});
        }),
        h("button", {type: "button", class: `up-c up-n ${night ? (night.mismatched ? "part" : "nt") : "na"}`, role: "cell", title: ntxt, "aria-label": ntxt,
          onclick: () => { detail.textContent = ntxt; }}));
    });
    put(grid, head, ...rows);
    const st = (d.stops || []).slice(-5).reverse();
    put(stops, st.length ? [h("b", null, "최근 멈춤"), h("ul", {class: "up-list"}, st.map((x) => h("li", null, `${fmt.kst(x.from)} ~ ${fmt.hm(x.to)} · ${fmt.int(x.min)}분`)))]
      : null);
  }

  let gen = 0;
  async function load(user) {
    const g = ++gen;
    if (user) motion.swap(grid);
    try {
      const d = await ctx.api(`${API}?days=${days}`);
      if (!ctx.alive() || g !== gen) return;
      render(d);
    } catch (e) {
      if (!ctx.alive() || g !== gen) return;
      put(headline, h("span", {class: "muted"}, e && e.status === 404 ? "가동 기록 준비 전 (서버 업데이트 뒤에 보입니다)" : "가동 기록을 불러오지 못했습니다 (잠시 뒤 다시)."));
    }
  }
  ctx.every(REFRESH_MS, () => load(false), {now: true});
  return card;
}
