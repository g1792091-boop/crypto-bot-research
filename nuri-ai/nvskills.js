// NVIDIA 공식 스킬 라이브러리 (github.com/NVIDIA/skills 전체를 앱에 내장)
// skills/nvidia/index.json(목록) + 스킬별 .json.gz(SKILL.md·참고문서·스크립트)를 필요할 때만 읽는다.
let IDX = null;
const cache = new Map();
export function nvIndex(){
  if (!IDX) IDX = fetch(new URL("./skills/nvidia/index.json", import.meta.url)).then(r => { if (!r.ok) throw new Error("스킬 목록을 읽지 못했습니다"); return r.json(); }).catch(e => { IDX = null; throw e; });
  return IDX;
}
export function nvSkill(name){
  name = String(name || "").trim().replace(/[^\w.-]/g, "");
  if (!cache.has(name)) cache.set(name, (async () => {
    const r = await fetch(new URL(`./skills/nvidia/${name}.json.gz`, import.meta.url));
    if (!r.ok) throw new Error("그런 NVIDIA 스킬이 없습니다: " + name);
    const text = await new Response(r.body.pipeThrough(new DecompressionStream("gzip"))).text();
    return JSON.parse(text);
  })().catch(e => { cache.delete(name); throw e; }));
  return cache.get(name);
}
export const GROUP_KO = {"Vision AI": "비전 AI", "Training AI": "AI 학습", "Networking": "네트워킹", "Physical AI": "피지컬 AI", "Agentic AI": "에이전트 AI", "GPU Development": "GPU 개발",
  "Infrastructure": "인프라", "Robotics": "로보틱스", "Inference AI": "추론·서빙", "Simulation and Modeling": "시뮬레이션", "Decision Optimization": "최적화", "Conversational AI": "대화·음성 AI",
  "Robotics Simulation": "로봇 시뮬레이션", "Data Science": "데이터 과학", "AI Storage": "AI 스토리지", "Quantum Computing": "양자 컴퓨팅", "Cybersecurity": "보안", "Gaming": "게임", "기타": "기타"};
// 한국어 질문도 찾을 수 있게 영어 검색어를 덧붙인다
const KO = {"로봇": "robot robotics isaac", "자율주행": "autonomous vehicle drive", "의료": "medical health clinical", "병원": "medical clinical", "영상": "video vss deepstream", "카메라": "camera video", "동영상": "video",
  "음성": "speech asr tts riva", "받아쓰기": "asr speech", "번역": "translation", "학습": "train training finetune", "파인튜닝": "finetune lora sft", "미세조정": "finetune lora", "최적화": "optimization cuopt",
  "경로": "routing cuopt", "배송": "routing cuopt", "포트폴리오": "portfolio optimization", "주식": "portfolio stock", "데이터": "data dataset", "합성": "synthetic data designer", "검색": "retrieval rag search",
  "문서": "rag retrieval document", "추론": "inference serving", "서빙": "serve serving inference dynamo", "배포": "deploy deployment", "날씨": "weather earth2 forecast", "기후": "climate earth2 weather",
  "단백질": "protein bionemo", "신약": "drug molecular bionemo", "분자": "molecular bionemo", "유전체": "genomics", "시뮬레이션": "simulation omniverse warp", "디지털트윈": "omniverse digital twin",
  "젯슨": "jetson", "쿠다": "cuda", "양자": "quantum cuda-q", "네트워크": "network doca", "보안": "security", "데이터프레임": "cudf dataframe", "판다스": "pandas cudf", "커널": "kernel cuda tile",
  "게임": "rtx remix gaming", "모드": "remix modding", "물리": "physics physicsnemo warp", "3d": "3d usd omniverse", "캐드": "cad simready omniverse", "강화학습": "rl reinforcement nemo-rl",
  "평가": "evaluation eval", "벤치마크": "benchmark", "멀티gpu": "distributed multi-gpu", "분산": "distributed", "엣지": "jetson edge", "의료영상": "monai ct mri segmentation", "ct": "ct segment", "mri": "mri"};
// 제품 이름(한글) → 영어 이름: 이건 사용자가 직접 말한 것으로 본다
const PRODUCT_KO = {"젯슨": "jetson", "쿠다": "cuda", "옴니버스": "omniverse", "아이작": "isaac", "리바": "riva", "네모": "nemo", "딥스트림": "deepstream", "홀로스캔": "holoscan",
  "모나이": "monai", "바이오네모": "bionemo", "다이나모": "dynamo", "코스모스": "cosmos", "쿠옵트": "cuopt", "네모트론": "nemotron", "도카": "doca", "텐서알티": "tensorrt", "워프": "warp"};
const STOP = new Set(["the", "and", "for", "with", "use", "using", "how", "what", "nvidia", "skill", "skills", "해줘", "어떻게", "알려줘", "방법", "하는", "하고", "있는"]);
const tok = s => (String(s || "").toLowerCase().match(/[a-z0-9+]+|[가-힣]+/g) || []).filter(w => w.length > 1 && !STOP.has(w));
export async function nvSearch(q, n = 6){
  const idx = await nvIndex();
  const raw = tok(q), base = [...raw], extra = [];
  for (const w of raw) for (const [k, v] of Object.entries(PRODUCT_KO)) if (w.includes(k)) base.push(v);
  for (const w of raw) for (const [k, v] of Object.entries(KO)) if (w.includes(k)) extra.push(...v.split(" "));
  const direct = new Set(base);
  const words = [...new Set([...base, ...extra])];
  if (!words.length) return [];
  const out = [];
  for (const s of idx.skills){
    const nameParts = s.n.toLowerCase().split("-"), desc = (s.d + " " + s.w).toLowerCase(), tags = s.t.map(t => t.toLowerCase());
    let sc = 0, nameHit = 0, directHit = 0;
    for (const w of words){
      if (s.n.toLowerCase() === w) sc += 12;
      if (nameParts.includes(w)){ sc += 4; nameHit++; if (direct.has(w)) directHit++; }
      else if (s.n.toLowerCase().includes(w) && w.length > 3){ sc += 2; nameHit++; }
      if (tags.some(t => t === w || t.includes(w) && w.length > 3)) sc += 2;
      if (new RegExp(`\\b${w.replace(/[+]/g, "\\+")}`).test(desc)) sc += 1;
    }
    if (sc > 0) out.push({name: s.n, group: s.g, desc: s.d, score: sc, nameHit, directHit});
  }
  return out.sort((a, b) => b.score - a.score).slice(0, n);
}
// 질문이 특정 NVIDIA 스킬과 분명히 맞을 때만 자동으로 켠다
export async function nvAutoSkill(q){
  try {
    const [top] = await nvSearch(q, 1);
    if (!top || top.score < 9 || !top.directHit) return null;   // 제품·기술 이름을 직접 말했을 때만
    const sk = await nvSkill(top.name);
    return {name: top.name, body: sk.files["SKILL.md"] || ""};
  } catch(e){ return null; }
}
