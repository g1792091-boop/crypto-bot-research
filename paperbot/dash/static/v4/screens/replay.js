// #/replay — 거래 다시보기 (v4 additions, builder fills this in). Placeholder so the route exists while it is built.
import {ui} from "../core/pb.js";

export async function mount(el, ctx) {
  ctx.setTitle("거래 다시보기");
  el.append(ui.screenHead("거래 다시보기", "만드는 중"));
}
export function unmount() {}
