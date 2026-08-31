# -*- coding: utf-8 -*-
"""把 Field Nation 工单原始导出转成网站用的两个数据文件。

    python3 tools/build_gigs.py <fieldnation_available_raw.json>

产出：
    docs/gigs.json         列表层：地图、筛选、排序需要的字段（约 0.3 MB，gzip 后 ~50 KB）
    docs/gigs-detail.json  详情层：工作内容、任务清单、资质、扣款条款（页面后台懒加载）

分两个文件是为了手机：地图秒开，详情在后台补。

报酬口径注意：净额上限用 pay_summary.max_pay_limit（毛额扣平台费后）。
不要用 calculated_total.total.max —— 对 hourly/blended/device 它返回的是
"只干 1 个单位"的净额（时薪单只算 1 小时），会把报酬低估近一个数量级。
"""
import json, math, os, sys, re, collections, datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.expanduser("~"), "GPU365/fieldnationworkorder/fieldnation_available_raw.json")
DOCS = os.path.join(HERE, "docs")
DESC_CAP = 4000    # 详情正文上限字符数
TASK_CAP = 40

def g(d, *path):
    for k in path:
        if not isinstance(d, dict): return None
        d = d.get(k)
        if d is None: return None
    return d

raw = json.load(open(SRC, encoding="utf-8"))
idx, det = [], {}

for r in raw:
    ps, loc, sch = r.get("pay_summary") or {}, r.get("location") or {}, r.get("schedule") or {}
    lat, lon = loc.get("latitude"), loc.get("longitude")
    if lat is None or lon is None: continue

    net   = ps.get("max_pay_limit")
    gross = ps.get("max_pay")
    if net is None and gross is not None: net = round(gross * 0.885, 2)
    ptype, rate = ps.get("pay_type"), g(ps, "base", "amount")
    # 工时口径要和"报酬上限"配套：报酬取的是封顶值，工时也取封顶值，
    # 否则 blended 单（打包 2h + 追加 22h）会用 2h 去除以 24h 的钱，折合时薪虚高十倍。
    bu, au = g(ps, "base", "units") or 0, g(ps, "additional", "units") or 0
    if   ptype == "hourly":  hours = bu or sch.get("est_labor_hours") or ps.get("hours_cap")
    elif ptype == "blended": hours = (bu + au) or sch.get("est_labor_hours")
    else:                    hours = sch.get("est_labor_hours") or ps.get("hours_cap")
    if not hours and ptype == "hourly" and rate: hours = (gross or 0) / rate
    hours = hours or 4.0
    # 公开站点不发布 distance_miles：那是"距抓取账号住址"的距离，
    # 对访客没有意义，还会泄露站长的大致住址。
    # 有效时薪这里只按劳动工时算（不含路程），访客看到的是与自身位置无关的口径。
    eff   = net / hours if net and hours else None

    wid = str(r.get("id"))
    idx.append({
        "i": wid, "t": r.get("title") or "",
        "w": g(r, "type_of_work", "name") or "未标注",
        "n": round(net, 2) if net else None, "g": gross, "p": ptype,
        "r": rate, "bu": g(ps, "base", "units"),
        "au": g(ps, "additional", "units"), "aa": g(ps, "additional", "amount"),
        "h": round(hours, 2), "e": round(eff, 1) if eff else None,
        "la": round(lat, 5), "lo": round(lon, 5),
        "c": loc.get("city") or "", "s": loc.get("state") or "", "z": loc.get("zip") or "",
        "lt": g(loc, "location_type", "name") or "",
        "sd": g(sch, "start_local", "date") or "",
        "st": (g(sch, "start_local", "time") or "")[:5],
        "ed": g(sch, "end_local", "date") or "",
        "hs": 1 if sch.get("hard_start") else 0,
        "q": r.get("requests_count"),
        "cid": g(r, "company", "id"),
        "bs": g(r, "buyer_rating", "buyer", "overall", "stars"),
        "bn": g(r, "buyer_rating", "buyer", "overall", "ratings"),
        "bd": g(r, "buyer_rating", "buyer", "overall", "approval_days"),
        "sk": [x.get("name") for x in (r.get("sub_skills") or []) if x.get("name")],
    })

    desc = (r.get("description_markdown") or "").strip()
    desc = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>])", r"\1", desc)   # 去掉 markdown 转义反斜杠
    desc = re.sub(r"\*{2,}", "", desc)                          # 去掉加粗标记，按纯文本读
    desc = re.sub(r"\n{3,}", "\n\n", desc)
    cut  = len(desc) > DESC_CAP
    tasks = [t.get("description") or g(t, "descriptions", "task") or t.get("label")
             for t in (r.get("tasks") or [])]
    tasks = [t for t in tasks if t][:TASK_CAP]
    det[wid] = {
        "d": desc[:DESC_CAP] + ("\n\n…（正文过长已截断，全文见原页面）" if cut else ""),
        "k": tasks,
        "q": [x.get("description") for x in (g(r, "qualifications", "selection_rule", "results") or [])
              if x.get("description")],
        "p": [[p.get("name"), p.get("modifier")]
              for p in (g(r, "pay_raw", "penalties", "results") or [])],
        "m": loc.get("map_href") or "",
    }

# 同坐标（邮编质心）多单散开，保证每单都点得到
by = collections.defaultdict(list)
for r in idx: by[(r["la"], r["lo"])].append(r)
for _, grp in by.items():
    n = len(grp)
    if n == 1: continue
    R = 0.0030 + 0.0016 * math.log(n)
    for i, r in enumerate(sorted(grp, key=lambda x: x["i"])):
        a = 2 * math.pi * i / n
        r["la"] = round(r["la"] + R * math.cos(a), 5)
        r["lo"] = round(r["lo"] + R * math.sin(a) / max(math.cos(math.radians(r["la"])), .3), 5)

meta = {"updated": datetime.date.today().isoformat(), "total": len(idx),
        "tows": [t for t, _ in collections.Counter(r["w"] for r in idx).most_common()]}
json.dump({"meta": meta, "rows": idx}, open(os.path.join(DOCS, "gigs.json"), "w", encoding="utf-8"),
          ensure_ascii=False, separators=(",", ":"))
json.dump(det, open(os.path.join(DOCS, "gigs-detail.json"), "w", encoding="utf-8"),
          ensure_ascii=False, separators=(",", ":"))
for f in ("gigs.json", "gigs-detail.json"):
    print(f, round(os.path.getsize(os.path.join(DOCS, f)) / 1e6, 2), "MB")
print("工单", len(idx), "｜工种", len(meta["tows"]))
