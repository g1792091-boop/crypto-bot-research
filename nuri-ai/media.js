// 유튜브·인스타그램·커뮤니티 리서치: 영상 검색·채널 새 영상·자막, 인스타 공개 게시물 검색, 국내 커뮤니티·블로그 글 검색
// 키 없이 쓰는 길이 기본이다: 유튜브는 검색 페이지 HTML 속 ytInitialData 를 읽고(구조가 바뀌면 깨질 수 있어 웹 검색으로 대체),
// 유튜브 Data API 키(opts.ytKey)가 있으면 공식 API 를 먼저 쓴다. 인스타그램은 공개 API 가 없어 검색엔진 결과만 쓴다.
// 결과는 인기·의견 자료다(사실 아님). 시험할 때는 opts.search · opts.fetchText · opts.fetchJson 을 주입한다.

/* ============ 공용 ============ */
let ENG = null;
const engine = async () => { if (ENG === null){ try { ENG = await import("./engine.js"); } catch(e){ ENG = false; } } return ENG || null; };
async function io(o = {}){
  const E = (o.search && o.fetchText && o.fetchJson) ? null : await engine();
  const need = n => { throw new Error(`${n} 를 쓸 수 없습니다 (엔진 없음 — 시험에서는 opts.${n} 를 주입)`); };
  return {
    search: o.search || (E ? E.webSearch : () => need("search")),
    fetchText: o.fetchText || (E ? u => E.webGet(u, "text") : () => need("fetchText")),
    fetchJson: o.fetchJson || (E ? u => E.webGet(u, "json") : () => need("fetchJson"))
  };
}
let SETTINGS = null;
export function setMediaSettings(s){ SETTINGS = s; }
const ytKeyOf = o => o.ytKey || SETTINGS?.keys?.youtube || SETTINGS?.youtubeKey || "";
async function pool(items, k, fn){
  const out = new Array(items.length); let i = 0;
  await Promise.all(Array.from({length: Math.min(k, items.length)}, async () => { while (i < items.length){ const j = i++; try { out[j] = await fn(items[j], j); } catch(e){ out[j] = {error: e}; } } }));
  return out;
}
const DAY = 864e5;
// 날짜 글자 → "YYYY-MM-DD" ("3일 전", "2026.09.12", ISO 모두)
export function parseDate(s, now = Date.now()){
  s = String(s || "").trim(); if (!s) return "";
  let m = s.match(/(20\d\d)\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})/);
  if (m) return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
  m = s.match(/(\d+)\s*(분|시간|일|주|개월|달|년)\s*전/) || s.match(/(\d+)\s*(minute|hour|day|week|month|year)s?\s*ago/i);
  if (m){ const u = {분: 6e4, minute: 6e4, 시간: 36e5, hour: 36e5, 일: DAY, day: DAY, 주: 7 * DAY, week: 7 * DAY, 개월: 30 * DAY, 달: 30 * DAY, month: 30 * DAY, 년: 365 * DAY, year: 365 * DAY}[m[2].toLowerCase()]; return new Date(now - m[1] * u).toISOString().slice(0, 10); }
  return "";
}
const unxml = s => String(s ?? "").replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16))).replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(+d)).replace(/&amp;/g, "&");
const host = u => { try { return new URL(u).hostname.replace(/^www\.|^m\./, ""); } catch(e){ return ""; } };
// 문자열 안을 건너뛰며 짝 맞는 중괄호까지 자른다
function sliceBalanced(s, start){
  let depth = 0, inStr = false;
  for (let i = start; i < s.length; i++){
    const c = s[i];
    if (inStr){ if (c === "\\"){ i++; continue; } if (c === '"') inStr = false; continue; }
    if (c === '"') inStr = true; else if (c === "{") depth++; else if (c === "}" && --depth === 0) return s.slice(start, i + 1);
  }
  return null;
}
// HTML 속 `var ytInitialData = {...};` 같은 JSON 덩어리를 꺼낸다
export function extractJsonVar(html, name){
  html = String(html || "");
  for (const re of [new RegExp(`var\\s+${name}\\s*=\\s*\\{`), new RegExp(`window\\[["']${name}["']\\]\\s*=\\s*\\{`), new RegExp(`${name}\\s*=\\s*\\{`)]){
    const m = re.exec(html); if (!m) continue;
    const chunk = sliceBalanced(html, m.index + m[0].length - 1);
    if (chunk){ try { return JSON.parse(chunk); } catch(e){} }
  }
  return null;
}

/* ============ 유튜브: 검색 ============ */
const tx = t => t == null ? "" : typeof t === "string" ? t : t.simpleText ?? t.content ?? (t.runs || []).map(r => r.text).join("") ?? "";
// "조회수 1.2만회" · "1,234,567 views" · "12K views" → 숫자 (모르면 null)
export function parseViews(s){
  s = String(s || "").replace(/,/g, "").trim(); if (!s) return null;
  if (/조회수\s*없음|no views/i.test(s)) return 0;
  const m = s.match(/(\d+(?:\.\d+)?)\s*(억|만|천|[KMB])?/i); if (!m) return null;
  const mul = {억: 1e8, 만: 1e4, 천: 1e3, k: 1e3, m: 1e6, b: 1e9}[(m[2] || "").toLowerCase()] || 1;
  return Math.round(+m[1] * mul);
}
// ytInitialData 안의 영상 항목을 모두 찾는다 (videoRenderer · 새 lockupViewModel · 쇼츠)
export function parseYtInitialData(data, n = 20){
  const out = [], seen = new Set();
  const push = it => { if (it.videoId && !seen.has(it.videoId) && it.title){ seen.add(it.videoId); out.push({...it, url: it.short ? `https://www.youtube.com/shorts/${it.videoId}` : `https://www.youtube.com/watch?v=${it.videoId}`, viewCount: parseViews(it.views)}); } };
  const walk = (o, d = 0) => {
    if (!o || typeof o !== "object" || d > 40 || out.length >= n) return;
    if (Array.isArray(o)){ for (const x of o) walk(x, d + 1); return; }
    if (o.videoRenderer){ const v = o.videoRenderer; push({videoId: v.videoId, title: tx(v.title), channel: tx(v.ownerText || v.longBylineText || v.shortBylineText), views: tx(v.viewCountText) || tx(v.shortViewCountText), published: tx(v.publishedTimeText), length: tx(v.lengthText)}); return; }
    if (o.reelItemRenderer){ const v = o.reelItemRenderer; push({videoId: v.videoId, title: tx(v.headline), channel: "", views: tx(v.viewCountText), published: "", length: "쇼츠", short: true}); return; }
    if (o.shortsLockupViewModel){ const v = o.shortsLockupViewModel, id = v.onTap?.innertubeCommand?.reelWatchEndpoint?.videoId || String(v.entityId || "").replace(/^shorts-shelf-item-/, ""); push({videoId: id, title: tx(v.overlayMetadata?.primaryText), channel: "", views: tx(v.overlayMetadata?.secondaryText), published: "", length: "쇼츠", short: true}); return; }
    if (o.lockupViewModel && /VIDEO/.test(o.lockupViewModel.contentType || "")){
      const v = o.lockupViewModel, md = v.metadata?.lockupMetadataViewModel || {};
      const parts = (md.metadata?.contentMetadataViewModel?.metadataRows || []).flatMap(r => (r.metadataParts || []).map(p => tx(p.text)));
      push({videoId: v.contentId, title: tx(md.title), channel: parts[0] || "", views: parts.find(p => /조회|view/i.test(p)) || "", published: parts.find(p => /전|ago/.test(p)) || "", length: ""}); return;
    }
    for (const k in o) walk(o[k], d + 1);
  };
  walk(data);
  return out.slice(0, n);
}
const isoDur = s => { const m = String(s || "").match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/); if (!m) return ""; const [h, mi, se] = [+m[1] || 0, +m[2] || 0, +m[3] || 0]; return (h ? h + ":" + String(mi).padStart(2, "0") : mi) + ":" + String(se).padStart(2, "0"); };
// 영상 검색: API 키 → 검색 페이지 HTML → 웹 검색 순서로 시도. 반환 {items, via, note}
export async function youtubeSearch({query, n = 10, ...o} = {}){
  const {fetchText, fetchJson, search} = await io(o), q = String(query || "").trim(), key = ytKeyOf(o), notes = [];
  if (!q) throw new Error("검색어가 필요합니다");
  n = Math.max(1, Math.min(25, +n || 10));
  if (key){
    try {
      const s = await fetchJson(`https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&maxResults=${n}&regionCode=KR&relevanceLanguage=ko&q=${encodeURIComponent(q)}&key=${encodeURIComponent(key)}`);
      const ids = (s.items || []).map(x => x.id?.videoId).filter(Boolean);
      const st = ids.length ? await fetchJson(`https://www.googleapis.com/youtube/v3/videos?part=statistics,contentDetails&id=${ids.join(",")}&key=${encodeURIComponent(key)}`).catch(() => ({items: []})) : {items: []};
      const by = Object.fromEntries((st.items || []).map(v => [v.id, v]));
      const items = (s.items || []).filter(x => x.id?.videoId).map(x => { const v = by[x.id.videoId], vc = v?.statistics?.viewCount != null ? +v.statistics.viewCount : null;
        return {videoId: x.id.videoId, title: unxml(x.snippet?.title), channel: unxml(x.snippet?.channelTitle), views: vc != null ? `조회수 ${vc.toLocaleString("ko-KR")}회` : "", viewCount: vc, published: String(x.snippet?.publishedAt || "").slice(0, 10), length: isoDur(v?.contentDetails?.duration), url: `https://www.youtube.com/watch?v=${x.id.videoId}`}; });
      if (items.length) return {items, via: "YouTube Data API"};
    } catch(e){ notes.push("API 실패: " + e.message); }
  }
  try {
    const html = await fetchText(`https://www.youtube.com/results?search_query=${encodeURIComponent(q)}&hl=ko&gl=KR`);
    const data = extractJsonVar(html, "ytInitialData"), items = data ? parseYtInitialData(data, n) : [];
    if (items.length) return {items, via: "유튜브 검색 페이지", note: notes.join(" ")};
    notes.push("검색 페이지에서 영상 목록을 못 읽음(구조 변경·동의 페이지 가능)");
  } catch(e){ notes.push("검색 페이지 실패: " + e.message); }
  const r = await search("site:youtube.com " + q, n + 4).catch(() => ({results: []}));
  const items = (r.results || []).filter(x => /youtube\.com\/(watch|shorts\/)|youtu\.be\//.test(x.url || "")).slice(0, n)
    .map(x => ({videoId: videoIdOf(x.url), title: String(x.title || "").replace(/\s*-\s*YouTube\s*$/i, ""), channel: "", views: "", viewCount: parseViews((String(x.snippet || "").match(/조회수\s*[\d.,]+\s*[만천억]?회?|[\d.,]+[KMB]?\s*views/i) || [])[0] || ""), published: x.date || parseDate(x.snippet) || "", url: x.url, snippet: x.snippet || ""}));
  return {items, via: "웹 검색(site:youtube.com)", note: [...notes, "웹 검색 대체라 조회수·채널이 빠질 수 있음"].join(" ")};
}
// 주소·ID → 11자리 영상 ID
export function videoIdOf(s){
  s = String(s || "").trim();
  const m = s.match(/(?:v=|youtu\.be\/|shorts\/|embed\/|live\/)([\w-]{11})/) || s.match(/^([\w-]{11})$/);
  return m ? m[1] : "";
}

/* ============ 유튜브: 채널 새 영상 (RSS, 키 없음) ============ */
export function parseChannelFeed(xml){
  xml = String(xml || "");
  const channel = unxml((xml.match(/<author>\s*<name>([\s\S]*?)<\/name>/) || xml.match(/<title>([\s\S]*?)<\/title>/) || [])[1] || "").trim();
  const items = [...xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)].map(([, e]) => {
    const g = re => unxml((e.match(re) || [])[1] || "").trim(), id = g(/<yt:videoId>([\s\S]*?)<\/yt:videoId>/), views = g(/<media:statistics[^>]*views="(\d+)"/);
    return {videoId: id, title: g(/<title>([\s\S]*?)<\/title>/), channel: g(/<name>([\s\S]*?)<\/name>/) || channel, published: g(/<published>([\s\S]*?)<\/published>/).slice(0, 10),
      views: views ? `조회수 ${(+views).toLocaleString("ko-KR")}회` : "", viewCount: views ? +views : null, url: g(/<link[^>]*href="([^"]+)"/) || `https://www.youtube.com/watch?v=${id}`,
      snippet: g(/<media:description>([\s\S]*?)<\/media:description>/).replace(/\s+/g, " ").slice(0, 200)};
  }).filter(x => x.videoId);
  return {channel, items};
}
export async function youtubeChannelFeed(channelId, o = {}){
  const id = String(channelId || "").trim();
  if (!/^UC[\w-]{22}$/.test(id)) throw new Error("채널 ID(UC로 시작하는 24자)가 필요합니다");
  const {fetchText} = await io(o);
  return {...parseChannelFeed(await fetchText(`https://www.youtube.com/feeds/videos.xml?channel_id=${id}`)), via: "채널 RSS(최근 15개)"};
}

/* ============ 유튜브: 자막 (최선 노력) ============ */
// 자막 XML(srv1 <text> · srv3 <p>) 또는 json3 → 평문
export function parseTimedText(body){
  body = String(body || "").trim(); if (!body) return "";
  if (body[0] === "{"){ try { return (JSON.parse(body).events || []).flatMap(e => (e.segs || []).map(s => s.utf8 || "")).join("").replace(/\s+/g, " ").trim(); } catch(e){ return ""; } }
  const parts = [...body.matchAll(/<(text|p)\b[^>]*>([\s\S]*?)<\/\1>/g)].map(m => unxml(unxml(m[2].replace(/<[^>]+>/g, ""))).replace(/\s+/g, " ").trim()).filter(Boolean);
  return parts.join(" ").replace(/\s+/g, " ").trim();
}
// 자막 트랙 고르기: 한국어(직접 작성) → 한국어(자동) → 영어(직접) → 영어(자동) → 첫 번째
export function pickCaptionTrack(tracks){
  const t = tracks || [], f = (lang, asr) => t.find(x => String(x.languageCode || "").startsWith(lang) && (x.kind === "asr") === asr);
  return f("ko", false) || f("ko", true) || f("en", false) || f("en", true) || t[0] || null;
}
// 영상 자막 평문 {videoId, title, lang, auto, text, truncated}. 자막이 없거나 막히면 null
export async function youtubeTranscript(videoId, {max = 8000, ...o} = {}){
  const id = videoIdOf(videoId); if (!id) return null;
  const {fetchText} = await io(o);
  try {
    const html = await fetchText(`https://www.youtube.com/watch?v=${id}&hl=ko`);
    const pr = extractJsonVar(html, "ytInitialPlayerResponse");
    const tr = pickCaptionTrack(pr?.captions?.playerCaptionsTracklistRenderer?.captionTracks);
    if (!tr?.baseUrl) return null;
    const url = tr.baseUrl.startsWith("/") ? "https://www.youtube.com" + tr.baseUrl : tr.baseUrl;
    const text = parseTimedText(await fetchText(url));
    if (!text) return null;                               // 최근 유튜브는 토큰(pot) 없는 자막 요청에 빈 응답을 주기도 한다
    return {videoId: id, title: tx(pr.videoDetails?.title) || pr.videoDetails?.title || "", channel: pr.videoDetails?.author || "", lang: tr.languageCode, auto: tr.kind === "asr", text: text.slice(0, max), truncated: text.length > max, chars: text.length};
  } catch(e){ return null; }
}

/* ============ 인스타그램 (공개 API 없음 → 검색엔진) ============ */
const igKind = u => /\/reels?\//.test(u) ? "릴스" : /\/p\//.test(u) ? "게시물" : /\/explore\/tags\//.test(u) ? "해시태그" : "계정";
export async function instagramSearch({query, n = 10, ...o} = {}){
  const {search} = await io(o), q = String(query || "").trim(); if (!q) throw new Error("검색어가 필요합니다");
  const tag = q.replace(/^#/, "").replace(/\s+/g, "");
  const qs = [`site:instagram.com ${q}`, `site:instagram.com "#${tag}"`, ...(q.includes(" ") ? [] : [`site:instagram.com/explore/tags ${tag}`])];
  const rs = await pool(qs, 2, x => search(x, Math.min(12, n + 2)));
  const seen = new Set(), items = [];
  for (const r of rs) for (const x of r?.results || []){
    if (host(x.url) !== "instagram.com" || seen.has(x.url.replace(/[?#].*$/, ""))) continue;
    seen.add(x.url.replace(/[?#].*$/, ""));
    items.push({title: String(x.title || "").replace(/\s*[•|·]\s*Instagram.*$/i, "").slice(0, 140), url: x.url, snippet: String(x.snippet || "").replace(/\s+/g, " ").slice(0, 220), date: x.date || parseDate(x.snippet), kind: igKind(x.url)});
  }
  return {items: items.slice(0, n), via: "웹 검색(site:instagram.com)", note: "인스타그램은 공개 API가 없어 검색엔진이 색인한 공개 게시물·계정만 보인다. 최신순·좋아요 수·전체 해시태그 피드는 알 수 없다."};
}

/* ============ 국내 커뮤니티·블로그 ============ */
export const COMMUNITY_SITES = {
  naverblog: {label: "네이버 블로그", site: "blog.naver.com"}, tistory: {label: "티스토리", site: "tistory.com"}, navercafe: {label: "네이버 카페", site: "cafe.naver.com"},
  clien: {label: "클리앙", site: "clien.net"}, ppomppu: {label: "뽐뿌", site: "ppomppu.co.kr"}, dcinside: {label: "디시인사이드", site: "dcinside.com"}, theqoo: {label: "더쿠", site: "theqoo.net"}
};
export async function communitySearch({query, sites, n = 4, ...o} = {}){
  const {search} = await io(o), q = String(query || "").trim(); if (!q) throw new Error("검색어가 필요합니다");
  const keys = (sites?.length ? sites : Object.keys(COMMUNITY_SITES)).filter(k => COMMUNITY_SITES[k]);
  const rs = await pool(keys, o.concurrency || 3, k => search(`site:${COMMUNITY_SITES[k].site} ${q}`, n + 2));
  const seen = new Set(), items = [], failed = [];
  rs.forEach((r, i) => {
    const S = COMMUNITY_SITES[keys[i]];
    if (!r || r.error){ failed.push(S.label); return; }
    for (const x of (r.results || []).filter(x => host(x.url).endsWith(S.site)).slice(0, n)){
      if (seen.has(x.url)) continue; seen.add(x.url);
      items.push({source: S.label, title: String(x.title || "").slice(0, 140), url: x.url, snippet: String(x.snippet || "").replace(/\s+/g, " ").slice(0, 220), date: x.date || parseDate(x.snippet)});
    }
  });
  return {items, via: "웹 검색(사이트 지정)", failed, note: "검색엔진에 색인된 공개 글만 보인다. 네이버 카페는 회원 전용 글이 많아 제목·요약만 나올 수 있다."};
}

/* ============ 요약 글 ============ */
const fmtV = it => it.viewCount != null ? (it.viewCount >= 1e4 ? `${(it.viewCount / 1e4).toFixed(it.viewCount >= 1e5 ? 0 : 1)}만회` : `${it.viewCount.toLocaleString("ko-KR")}회`) : (it.views || "");
// 짧은 한국어 요약 (1,800자 미만). kind: youtube | channel | instagram | community | transcript
export function mediaText(items, kind = "youtube", note = ""){
  const head = {youtube: "[유튜브 영상]", channel: "[유튜브 채널 새 영상]", instagram: "[인스타그램 공개 게시물]", community: "[커뮤니티·블로그 글]", transcript: "[유튜브 자막]"}[kind] || "[미디어]";
  const warn = "※ 조회수·게시글은 인기·개인 의견이지 사실 확인이 아니다. 내용을 인용할 때는 원 출처로 확인할 것.";
  if (kind === "transcript"){
    const t = items; if (!t?.text) return `${head} 자막을 가져오지 못했습니다(자막 없음 또는 유튜브 차단).`;
    return `${head} ${t.title || t.videoId} · ${t.lang}${t.auto ? " 자동생성" : ""}${t.truncated ? ` · 앞 ${t.text.length.toLocaleString()}자(전체 ${t.chars.toLocaleString()}자)` : ""}\n${warn}\n${t.text}`.slice(0, 1790);
  }
  if (!items?.length) return `${head} 결과가 없습니다.${note ? " " + note : ""}`;
  let out = `${head} ${items.length}건${note ? " · " + note : ""}\n${warn}\n`;
  for (let i = 0; i < items.length; i++){
    const it = items[i], meta = [it.source || it.kind, it.channel, fmtV(it), it.published || it.date, it.length].filter(Boolean).join(" · ");
    const line = `${i + 1}. ${it.title}${meta ? " (" + meta + ")" : ""}${it.snippet && kind !== "youtube" ? " — " + it.snippet.slice(0, 110) : ""}\n   ${it.url}\n`;
    if (out.length + line.length > 1790){ out += `…(나머지 ${items.length - i}건 생략)`; break; }
    out += line;
  }
  return out.trim();
}

/* ============ 도구 (agent.js 모양) ============ */
const srcOf = items => items.slice(0, 10).map(x => ({title: x.title, url: x.url}));
export const MEDIA_TOOLS = {
  youtube_search: {mode: "both", label: "유튜브 검색", args: '{"query":"검색어","n":10,"sort":"relevance|views","channel_id":"선택: UC로 시작하는 채널 ID"}', act: a => a.channel_id ? "유튜브 채널 새 영상 보기" : `유튜브에서 ‘${a.query}’ 검색`,
    desc: "유튜브 영상을 검색해 제목·채널·조회수·올린 때·길이를 준다(키 없이 동작, 유튜브 API 키가 있으면 공식 API). channel_id 를 주면 그 채널의 최근 영상 15개. 무엇이 화제인지 보는 용도이고 내용은 youtube_transcript 로 확인한다",
    async run(a, ctx = {}){
      const o = ctx.io || {};
      const r = a.channel_id ? await youtubeChannelFeed(a.channel_id, o) : await youtubeSearch({query: a.query, n: a.n || 10, ...o});
      let items = r.items; if (a.sort === "views") items = [...items].sort((x, y) => (y.viewCount ?? -1) - (x.viewCount ?? -1));
      return {text: mediaText(items, a.channel_id ? "channel" : "youtube", [r.via, r.note].filter(Boolean).join(" · ")), summary: `${r.via} · ${items.length}개`, sources: srcOf(items)};
    }},
  youtube_transcript: {mode: "both", label: "유튜브 자막", args: '{"video":"https://www.youtube.com/watch?v=... 또는 영상 ID","max":6000}', act: () => "유튜브 영상 자막 읽기",
    desc: "유튜브 영상의 자막(한국어 우선, 없으면 영어·자동 생성)을 평문으로 가져와 영상 내용을 요약·검증하는 데 쓴다. 자막이 없거나 막히면 알려준다",
    async run(a, ctx = {}){
      const id = videoIdOf(a.video || a.url || a.id); if (!id) throw new Error("유튜브 주소나 11자리 영상 ID가 필요합니다");
      const t = await youtubeTranscript(id, {max: Math.min(20000, a.max || 6000), ...(ctx.io || {})});
      const url = `https://www.youtube.com/watch?v=${id}`;
      if (!t) return {text: "이 영상의 자막을 가져오지 못했습니다(자막 없음, 연령 제한, 또는 유튜브의 자막 요청 차단). 제목·설명은 youtube_search 나 web_fetch 로 확인하세요.", summary: "자막 없음", sources: [{title: "유튜브 영상", url}]};
      return {text: `[유튜브 자막] ${t.title || id} · ${t.channel || ""} · ${t.lang}${t.auto ? " 자동생성" : ""}${t.truncated ? ` · 앞 ${t.text.length.toLocaleString()}자(전체 ${t.chars.toLocaleString()}자)` : ""}\n※ 영상 속 주장은 출연자 의견이다. 사실처럼 단정하지 말 것.\n${t.text}`, summary: `${t.lang}${t.auto ? " 자동" : ""} 자막 ${t.chars.toLocaleString()}자`, sources: [{title: t.title || "유튜브 영상", url}]};
    }},
  instagram_search: {mode: "both", label: "인스타그램 검색", args: '{"query":"성수동 팝업","n":10}', act: a => `인스타그램에서 ‘${a.query}’ 찾기`,
    desc: "인스타그램 공개 게시물·릴스·계정·해시태그를 검색엔진으로 찾는다(공식 API 없음: 색인된 공개 글만, 좋아요 수·최신순 불가). 유행·분위기 파악용",
    async run(a, ctx = {}){
      const r = await instagramSearch({query: a.query, n: Math.min(15, a.n || 10), ...(ctx.io || {})});
      return {text: mediaText(r.items, "instagram", r.note), summary: `인스타 ${r.items.length}건`, sources: srcOf(r.items)};
    }},
  community_search: {mode: "both", label: "커뮤니티 검색", args: '{"query":"검색어","sites":["naverblog","tistory","navercafe","clien","ppomppu","dcinside","theqoo"]}', act: a => `커뮤니티·블로그에서 ‘${a.query}’ 찾기`,
    desc: "네이버 블로그·티스토리·네이버 카페·클리앙·뽐뿌·디시인사이드·더쿠에서 관련 글을 찾아 사람들이 무슨 얘기를 하는지 보여준다(검색엔진 기반, 개인 의견)",
    async run(a, ctx = {}){
      const r = await communitySearch({query: a.query, sites: a.sites, n: Math.min(6, a.n || 4), ...(ctx.io || {})});
      const by = {}; r.items.forEach(x => by[x.source] = (by[x.source] || 0) + 1);
      return {text: mediaText(r.items, "community", r.failed.length ? `검색 실패: ${r.failed.join(", ")}` : ""), summary: Object.entries(by).map(([k, v]) => `${k} ${v}`).join(" · ") || "결과 없음", sources: srcOf(r.items)};
    }}
};
