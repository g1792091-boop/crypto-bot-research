"""Dashboard v4 홈: the band "story rings | 시장 지금" never pushes the page sideways on a PC window.

With a month of 하이라이트 rings, the rings' `auto` grid column grew to about 1,000 px and pushed 시장 지금 off the
page on 1100-1440 px windows (seen in the nav-top review, 10/06: the top menu is the default again, so 홈 sits in a
1320 px column there). The rings column is capped (its row scrolls inside itself, today first)."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def test_home_band_caps_the_rings_column():
    css = open(os.path.join(V4, "screens", "home-live.css"), encoding="utf-8").read()
    rule = re.search(r'\[data-screen="home"\] \.home-band \{ grid-template-columns: ([^;]+);', css)
    assert rule and rule.group(1).startswith("fit-content(") and rule.group(1).endswith("minmax(0, 1fr)"), rule
    assert "grid-template-columns: auto minmax(0, 1fr)" not in css
    kit = open(os.path.join(V4, "screens", "story-kit.css"), encoding="utf-8").read()
    assert ".sk-ring { display: grid; gap: 6px; min-width: 0; }" in kit       # the rings may shrink
    assert re.search(r"\.sk-row \{[^}]*overflow-x: auto;", kit)                  # and scroll inside themselves
