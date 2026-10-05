// #/flow — 흐름 (v4 additions, builder fills this in). Placeholder so the route exists while it is built.
import {ui} from "../core/pb.js";

export async function mount(el, ctx) {
  ctx.setTitle("흐름");
  el.append(ui.screenHead("흐름", "만드는 중"));
}
export function unmount() {}
