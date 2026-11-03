"""Limited-water mode: split a litre budget across fields by priority."""


def allocate(ranked_fields, budget_litres):
    """Give water to fields that need it NOW, highest priority first.
    Returns (rows, litres_left). Fields due in 2 days are not served from today's budget."""
    left = budget_litres
    rows = []
    for f in ranked_fields:
        r = f["reco"]
        if r["action"] != "IRRIGATE_NOW":
            rows.append(dict(name=f["name"], need=0, give=0, status="not_today"))
            continue
        need = r["litres"]
        give = min(need, left)
        left -= give
        status = "full" if give >= need else ("partial" if give > 0 else "none")
        rows.append(dict(name=f["name"], need=need, give=int(give), status=status,
                         minutes=int(-(-give // max(1, float(f.get("pump_lpm", 400)))))))
    return rows, int(left)
