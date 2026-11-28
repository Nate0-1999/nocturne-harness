"""Exercise the installed Deck, Farm and Context Bars with native browser input."""

import argparse
import json
import re
import socket
from pathlib import Path
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
for key in ("url", "chrome", "profile", "thread", "out"):
    parser.add_argument("--" + key, required=True)
parser.add_argument("--width", type=int, choices=[390, 1267], required=True)
parser.add_argument("--before", action="store_true")
parser.add_argument("--blocked-run")
args = parser.parse_args()
width = args.width
height = 844 if width == 390 else 928
out = Path(args.out)
out.mkdir(exist_ok=True, parents=True)
readings = {}
with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        args.profile,
        executable_path=args.chrome,
        headless=True,
        viewport={"width": width, "height": height},
        has_touch=width == 390,
        args=["--disable-background-networking"],
    )
    try:
        page = browser.pages[0]
        page.goto(args.url)
        page.wait_for_selector(".rack-module iframe")
        cdp = browser.new_cdp_session(page)

        def layout(module, conversation_mode="stack"):
            # Same saved Stage dimensions on both builds. Two neighboring instruments
            # exercise real Deck attunement, with the chosen instrument in view.
            page.evaluate(
                """([key,tid,w,mode])=>{
              const store='nocturne.stage.layout.v5',l=JSON.parse(localStorage.getItem(store));
              const layer=l.layers.find(x=>x.layer_id===l.active_layer_id), cols=w===390?8:18;
              const make=(id,x,y,h)=>({instance_id:id,module_id:id,x,y,width:cols,height:h});
              const deck={...make('conversation',key==='context_bars'?cols+1:0,0,15),conversation_mode:'stack',source_thread_id:tid};
              const bars={...make('context_bars',0,key==='context_bars'?0:16,10),attunement_source_id:'conversation'};
              if(key==='context_bars'){
                deck.conversation_mode=mode;
                if(w===390){deck.x=0;deck.height=6;bars.y=6.25;bars.height=9}
                else{deck.x=0;deck.width=12;bars.x=12.25;bars.width=12}
              }
              layer.modules=key==='farm'?[{...make('farm',0,0,15),width:18}]:key==='threads'?[make('threads',0,0,15)]:[deck,bars];
              l.layers=[layer];l.removed_layers=[];layer.removed_modules=[];
              l.scopes.context_bars='ATTUNED';layer.camera={x:3,y:3,zoom:w===390?.95:1};
              localStorage.setItem(store,JSON.stringify(l))
            }""",
                [module, args.thread, width, conversation_mode],
            )
            page.reload()
            view = page.get_by_role("button", name="Stage", exact=True).first
            if view.get_attribute("aria-pressed") == "false":
                view.click()
            return page.frame_locator(
                '.rack-module[data-rack-module="' + module + '"] iframe'
            ).first

        def shot(name):
            hidden = []
            pattern = re.compile(
                r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|" + re.escape(socket.gethostname().split(".")[0]),
                re.I,
            )
            for frame in page.frames:
                hidden.extend(el for el in frame.get_by_text(pattern).all() if el.is_visible())
            page.screenshot(path=out / f"{name}-{width}.png", mask=hidden)

        def gesture(box, delta, table=False):
            x = min(width - 12, box["x"] + min(100, box["width"] / 2))
            y = min(
                height - 100,
                max(
                    140,
                    box["y"] + (box["height"] * 0.88 if table else min(104, box["height"] * 0.66)),
                ),
            )
            if width == 1267:
                page.mouse.move(x, y)
                page.mouse.wheel(0, delta)
            else:
                travel = min(110, box["height"] * 0.48) * (1 if delta > 0 else -1)
                for i in range(9):
                    cdp.send(
                        "Input.dispatchTouchEvent",
                        {
                            "type": "touchStart" if i == 0 else "touchMove",
                            "touchPoints": [{"x": x, "y": y - travel * i / 8}],
                        },
                    )
                    page.wait_for_timeout(15)
                cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            page.wait_for_timeout(125)

        def metrics(el):
            return el.evaluate(
                "e=>({top:e.scrollTop,size:e.clientHeight,full:e.scrollHeight,wide:e.scrollWidth,width:e.clientWidth})"
            )

        def rect(el):
            return el.evaluate(
                "e=>({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,right:e.getBoundingClientRect().right,left:e.getBoundingClientRect().left,vh:innerHeight})"
            )

        def travel(el, target):
            for _ in range(45):
                r = rect(target)
                box = el.bounding_box()
                if (
                    0 <= r["top"]
                    and r["bottom"] <= r["vh"]
                    and target.evaluate(
                        "e=>{const b=e.getBoundingClientRect();return e.contains(document.elementFromPoint(b.x+5,b.y+b.height/2))}"
                    )
                ):
                    return True
                old = metrics(el)
                gesture(box, 570 if r["top"] > 0 else -570, el.get_attribute("data-view") == "farm")
                if metrics(el)["top"] == old["top"]:
                    break
            return False

        rail = layout("threads")
        rail.locator(f'[data-thread-id="{args.thread}"] .thread-item__select').press("Enter")
        page.wait_for_timeout(400)
        for mode in ("Stage", "Sheet"):
            fr = layout("conversation")
            if mode == "Sheet":
                page.get_by_role("button", name="Sheet", exact=True).first.click()
            deck = fr.locator(".symphony-deck")
            cards = deck.locator(".deck-stack")
            cards.nth(1).wait_for(timeout=15000)
            shot(mode.lower() + "-deck-top")
            last = cards.last
            # Reach the last card's evidence using only wheel or touch scrolling.
            target = last.locator("summary").filter(has_text="Judge verdicts").last
            start = metrics(deck)
            if width == 1267:
                box = deck.bounding_box()
                page.mouse.click(box["x"] + 20, box["y"] + 15)
                page.keyboard.press("PageDown")
                page.wait_for_timeout(380)
                paged = metrics(deck)["top"] > start["top"]
                page.keyboard.press("Home")
                page.wait_for_timeout(200)
            reached = travel(deck, target)
            if reached:
                target.click()
            shot(mode.lower() + "-deck-verdict")
            readings[mode + " Deck"] = {
                "before": start,
                "after": metrics(deck),
                "cards": cards.count(),
                "last verdict reachable": reached,
            }
            if width == 1267:
                readings[mode + " Deck"]["PageDown moved"] = paged
            if args.blocked_run:
                blocked = deck.locator('.deck-stack[data-state="blocked"]').filter(
                    has_text=args.blocked_run
                )
                readings[mode + " Deck"]["blocked attempt labels"] = blocked.locator(
                    ".deck-attempt > div > span"
                ).all_text_contents()
            target = last.locator("summary").filter(has_text="Worker evidence").last
            reached_worker = travel(deck, target)
            if reached_worker:
                target.click()
            readings[mode + " Deck"]["last worker evidence reachable"] = reached_worker
            shot(mode.lower() + "-deck-worker")
        fr = layout("farm")
        table = fr.locator("table").first
        last = table.locator("tbody tr").last
        last.wait_for(timeout=25000)
        area = fr.get_by_test_id("farm-module")
        shot("stage-farm-top")
        start = metrics(area)
        ok = travel(area, last.locator("td").nth(3))
        shot("stage-farm-last")
        bounds = [c.bounding_box() for c in last.locator("td").all()[:4]]
        readings["Farm"] = {
            "before": start,
            "after": metrics(area),
            "rows": table.locator("tbody tr").count(),
            "last row reachable": ok,
            "identity fits": all(
                0 <= b["x"] and b["x"] + b["width"] <= width and b["y"] + b["height"] <= height
                for b in bounds
            ),
        }
        fr = layout("context_bars")
        fr.locator("body").wait_for()
        page.wait_for_timeout(1200)
        picker = fr.get_by_label("Context run")
        readings["Context Bars"] = {"offered with Deck": picker.count() > 0}
        shot("stage-context-with-deck")
        if args.before and not picker.count():
            fr = layout("context_bars", "focused")
            picker = fr.get_by_label("Context run")
            picker.wait_for(timeout=12000)
        if picker.count():
            picker.select_option(args.blocked_run) if args.blocked_run else picker.select_option(
                index=1
            )
            workers = fr.get_by_label("Context source")
            workers.wait_for()
            labels = workers.locator("option").all_text_contents()
            sel = next(s for s in labels if "attempt-2" in s and "completion" in s)
            workers.select_option(label=sel)
            fr.get_by_text("Latest completed worker request", exact=False).wait_for()
            readings["Context Bars"].update(labels=labels, selected=sel)
        shot("stage-context-selected")
        if not args.before:
            deck_ids = picker.locator("option").evaluate_all("els=>els.map(e=>e.value)")
            focused = layout("context_bars", "focused").get_by_label("Context run")
            focused.wait_for(timeout=12000)
            readings["Context Bars"]["same runs in Focused"] = deck_ids == focused.locator(
                "option"
            ).evaluate_all("els=>els.map(e=>e.value)")

        print(json.dumps(readings, indent=2), flush=True)
        (out / f"readings-{width}.json").write_text(json.dumps(readings, indent=2) + "\n")
        assert all(
            r["last verdict reachable"] and r["last worker evidence reachable"]
            for k, r in readings.items()
            if k.endswith(" Deck")
        )
        if width == 1267:
            assert all(r["PageDown moved"] for k, r in readings.items() if k.endswith(" Deck"))
        if args.blocked_run:
            assert readings["Stage Deck"]["blocked attempt labels"] == ["completed", "completed"]
        assert ok and readings["Farm"]["identity fits"]
        assert (
            readings["Context Bars"]["offered with Deck"]
            and readings["Context Bars"]["same runs in Focused"]
        )
        if args.blocked_run:
            judges = [s for s in labels if "judge-" in s]
            assert len(judges) >= 6 and len(judges) == len(set(judges))
            assert all(re.search(r"Round [1-9][0-9]*", label) for label in judges)
    finally:
        browser.close()
