"""The three screens added together (코인별 ``coins``, 타임라인 ``timeline``, 데이터 점검 ``dataq``): one hook for runner.write_snapshots.

``add_blocks(doc, book, rows, lineup, equity0, ds_money)`` puts the three blocks into the snapshot dict ``doc``. Each is tried on its own: a failure sets
``doc["<name>_error"]`` and leaves the key out ("데이터 준비 중"); it never stops the snapshot. ``dataq`` goes last: it reads the ``*_error`` keys the
other blocks left (and its own failure only says so in ``dataq_error``)."""

from __future__ import annotations


def add_blocks(doc: dict, book: dict, rows: list, lineup: list, equity0: float, ds_money: bool) -> None:
    from . import coinview as CV, dataq as DQ, timeline as TL
    steps = (("coins", lambda: CV.coin_views(book, rows, lineup, equity0, ds_money)),
             ("timeline", lambda: TL.timeline_views(book, rows, lineup, doc.get("decision"), doc.get("start_ms"), doc.get("started_ms"), doc.get("done_ms"),
                                                    doc.get("notes"), ds_money)),
             ("dataq", lambda: DQ.dataq_views(doc, book, lineup, ds_money)))
    for name, make in steps:
        try:
            doc[name] = make()
        except Exception as exc:  # noqa: BLE001
            doc[f"{name}_error"] = f"{type(exc).__name__}: {exc}"[:200]
