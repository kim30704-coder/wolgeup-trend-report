#!/usr/bin/env python3
"""월급실험실 트렌드 리포트

매일 세 가지 데이터를 모아 마크다운 리포트를 만듭니다.
  1. 구글 트렌드 한국 급상승 검색어 (키 필요 없음)
  2. 유튜브 최근 영상 중 구독자 대비 조회수가 높은 '아웃라이어' (YOUTUBE_API_KEY 필요)
  3. 네이버 검색어 트렌드(NAVER API HUB) 검색량 추이 (NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 필요)

키가 없는 항목은 건너뛰고 나머지만으로 리포트를 만듭니다.

사용법:
    python trend_report.py                 # reports/YYYY-MM-DD.md 생성
    python trend_report.py --config my.yaml --out-dir somewhere
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import requests
import yaml

KST = dt.timezone(dt.timedelta(hours=9))
YT_BASE = "https://www.googleapis.com/youtube/v3"
NAVER_URL = "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"  # NAVER API HUB (2026년 6월~)
TRENDS_URL = "https://trends.google.com/trending/rss?geo={geo}"
WEEKDAYS = "월화수목금토일"


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fmt_int(n) -> str:
    if n is None:
        return "-"
    n = int(n)
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}억"
    if n >= 10_000:
        return f"{n / 10_000:.1f}만"
    if n >= 1_000:
        return f"{n / 1_000:.1f}천"
    return str(n)


def md_escape(text: str) -> str:
    return (text or "").replace("|", "∣").replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# 1. 구글 트렌드
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_traffic(text: str) -> int:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else 0


def parse_trends_rss(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        entry = {"title": "", "traffic": 0, "traffic_text": "", "news": []}
        for child in item:
            name = _local(child.tag)
            if name == "title":
                entry["title"] = (child.text or "").strip()
            elif name == "approx_traffic":
                entry["traffic_text"] = (child.text or "").strip()
                entry["traffic"] = parse_traffic(child.text)
            elif name == "news_item":
                news = {}
                for sub in child:
                    sub_name = _local(sub.tag)
                    if sub_name == "news_item_title":
                        news["title"] = (sub.text or "").strip()
                    elif sub_name == "news_item_url":
                        news["url"] = (sub.text or "").strip()
                    elif sub_name == "news_item_source":
                        news["source"] = (sub.text or "").strip()
                if news.get("title"):
                    entry["news"].append(news)
        if entry["title"]:
            items.append(entry)
    return items


def fetch_google_trends(geo: str) -> list[dict]:
    resp = requests.get(TRENDS_URL.format(geo=geo), timeout=20,
                        headers={"User-Agent": "Mozilla/5.0 (trend-report)"})
    resp.raise_for_status()
    return parse_trends_rss(resp.text)


def mark_relevance(items: list[dict], words: list[str]) -> list[dict]:
    # 영문 단어(AI, ETF 등)는 단어 경계로만 매칭해서 'lpga' 같은 오탐을 막음
    patterns = []
    for w in words:
        if re.fullmatch(r"[A-Za-z0-9]+", w):
            patterns.append((w, re.compile(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])", re.I)))
        else:
            patterns.append((w, re.compile(re.escape(w))))
    for it in items:
        haystack = " ".join([it["title"]] + [n.get("title", "") for n in it["news"]])
        it["relevant_words"] = [w for w, pat in patterns if pat.search(haystack)]
    return items


# ---------------------------------------------------------------------------
# 2. 유튜브 아웃라이어
# ---------------------------------------------------------------------------

class YouTubeClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.units_used = 0

    def get(self, endpoint: str, params: dict, cost: int = 1) -> dict:
        resp = requests.get(f"{YT_BASE}/{endpoint}", params={**params, "key": self.api_key}, timeout=30)
        self.units_used += cost
        if resp.status_code != 200:
            raise RuntimeError(f"YouTube API {endpoint} 오류 {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def search_video_ids(self, query, published_after, region, language, max_results) -> list[str]:
        data = self.get("search", {
            "part": "snippet", "q": query, "type": "video", "order": "viewCount",
            "publishedAfter": published_after, "regionCode": region,
            "relevanceLanguage": language, "maxResults": max_results,
        }, cost=100)
        return [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]

    def popular_video_ids(self, region, category_id) -> list[str]:
        data = self.get("videos", {
            "part": "id", "chart": "mostPopular", "regionCode": region,
            "videoCategoryId": category_id, "maxResults": 50,
        })
        return [it["id"] for it in data.get("items", [])]

    def videos(self, ids: list[str]) -> dict:
        out = {}
        for batch in chunks(ids, 50):
            data = self.get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(batch)})
            for it in data.get("items", []):
                out[it["id"]] = it
        return out

    def channels(self, ids: list[str]) -> dict:
        out = {}
        for batch in chunks(ids, 50):
            data = self.get("channels", {"part": "snippet,statistics", "id": ",".join(batch)})
            for it in data.get("items", []):
                out[it["id"]] = it
        return out


def parse_duration(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def build_video_rows(videos: dict, channels: dict, sources: dict, now: dt.datetime, min_views: int,
                     ratio_floor: int = 1000) -> list[dict]:
    rows = []
    for vid, v in videos.items():
        stats = v.get("statistics", {})
        views = int(stats.get("viewCount", 0))
        if views < min_views:
            continue
        snip = v.get("snippet", {})
        ch = channels.get(snip.get("channelId"), {})
        ch_stats = ch.get("statistics", {})
        hidden = ch_stats.get("hiddenSubscriberCount", False)
        subs = None if hidden or "subscriberCount" not in ch_stats else int(ch_stats["subscriberCount"])
        published = dt.datetime.fromisoformat(snip.get("publishedAt", now.isoformat()).replace("Z", "+00:00"))
        age_days = max((now - published).total_seconds() / 86400, 0.5)
        duration = parse_duration(v.get("contentDetails", {}).get("duration", ""))
        rows.append({
            "id": vid,
            "title": snip.get("title", ""),
            "channel": snip.get("channelTitle", ""),
            "views": views,
            "likes": int(stats["likeCount"]) if "likeCount" in stats else None,
            "comments": int(stats["commentCount"]) if "commentCount" in stats else None,
            "subs": subs,
            "ratio": (views / max(subs, ratio_floor)) if subs is not None else None,  # 신생 채널 과대평가 방지
            "views_per_day": views / age_days,
            "age_days": age_days,
            "duration": duration,
            "is_short": 0 < duration <= 180,
            "queries": sorted(sources.get(vid, [])),
            "url": f"https://www.youtube.com/watch?v={vid}" if duration > 180 else f"https://www.youtube.com/shorts/{vid}",
        })
    rows.sort(key=lambda r: (r["ratio"] is not None, r["ratio"] or 0, r["views_per_day"]), reverse=True)
    return rows


def collect_youtube(cfg: dict, api_key: str, now: dt.datetime) -> dict:
    yt = YouTubeClient(api_key)
    since = (now - dt.timedelta(days=cfg.get("days", 7))).astimezone(dt.timezone.utc)
    published_after = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    sources: dict[str, set] = {}
    warnings = []

    for q in cfg.get("search_queries", []):
        try:
            for vid in yt.search_video_ids(q, published_after, cfg.get("region", "KR"),
                                           cfg.get("language", "ko"), cfg.get("results_per_query", 25)):
                sources.setdefault(vid, set()).add(q)
        except RuntimeError as e:
            warnings.append(f"검색 '{q}' 실패: {e}")
            if "quota" in str(e).lower():
                break

    for cat in cfg.get("popular_categories", []) or []:
        try:
            for vid in yt.popular_video_ids(cfg.get("region", "KR"), cat):
                sources.setdefault(vid, set()).add(f"인기급상승(카테고리 {cat})")
        except RuntimeError as e:
            warnings.append(f"인기 차트 카테고리 {cat} 실패: {e}")

    videos = yt.videos(list(sources)) if sources else {}
    # 인기 차트 영상은 기간이 넓으므로 최근 N일 안에 올라온 것만 남김
    videos = {k: v for k, v in videos.items()
              if dt.datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00")) >= since}
    channel_ids = sorted({v["snippet"]["channelId"] for v in videos.values()})
    channels = yt.channels(channel_ids) if channel_ids else {}
    rows = build_video_rows(videos, channels, sources, now, cfg.get("min_views", 10000),
                            cfg.get("ratio_floor_subs", 1000))
    return {"rows": rows, "units_used": yt.units_used, "warnings": warnings}


STOPWORDS = {
    "그리고", "하는", "있는", "없는", "이유", "방법", "진짜", "정말", "지금", "이것", "이거", "그냥",
    "the", "and", "for", "shorts", "쇼츠", "feat", "with", "ep", "편", "까지", "에서", "으로", "하면",
}


def analyze_titles(rows: list[dict]) -> dict:
    if not rows:
        return {}
    titles = [r["title"] for r in rows]
    n = len(titles)

    def share(pattern):
        return round(100 * sum(1 for t in titles if re.search(pattern, t, re.I)) / n)

    words = Counter()
    for t in titles:
        for w in set(re.findall(r"[가-힣A-Za-z0-9]{2,}", t)):
            if w.lower() not in STOPWORDS and not w.isdigit():
                words[w] += 1
    return {
        "count": n,
        "avg_len": round(statistics.mean(len(t) for t in titles)),
        "quote": share(r"[\"“”'‘’]"),
        "number": share(r"\d"),
        "money": share(r"\d+\s*(만|억|원|천)"),
        "top_n": share(r"top\s*\d|\d+\s*(가지|개|위)"),
        "question": share(r"\?"),
        "ellipsis": share(r"\.\.\.|…"),
        "top_words": words.most_common(15),
    }


# ---------------------------------------------------------------------------
# 3. 네이버 데이터랩
# ---------------------------------------------------------------------------

def naver_request(client_id, client_secret, start, end, groups: list[dict]) -> list[dict]:
    body = {
        "startDate": start, "endDate": end, "timeUnit": "date",
        "keywordGroups": [{"groupName": g["name"], "keywords": g["keywords"][:20]} for g in groups],
    }
    resp = requests.post(NAVER_URL, data=json.dumps(body), timeout=30, headers={
        "X-NCP-APIGW-API-KEY-ID": client_id, "X-NCP-APIGW-API-KEY": client_secret,
        "Content-Type": "application/json",
    })
    if resp.status_code != 200:
        raise RuntimeError(f"네이버 API HUB 오류 {resp.status_code}: {resp.text[:300]}")
    return resp.json().get("results", [])


def _series(result: dict, start: dt.date, end: dt.date) -> list[float]:
    """네이버는 검색량 0인 날을 생략하므로 빈 날짜를 0으로 채움"""
    by_day = {d["period"]: float(d["ratio"]) for d in result.get("data", [])}
    out, day = [], start
    while day <= end:
        out.append(by_day.get(day.isoformat(), 0.0))
        day += dt.timedelta(days=1)
    return out


def summarize_naver(batches: list[list[dict]], anchor_name: str, start: dt.date, end: dt.date,
                    compare_days: int) -> list[dict]:
    rows = []
    for results in batches:
        anchor = next((r for r in results if r["title"] == anchor_name), None)
        if not anchor:
            continue
        a = _series(anchor, start, end)
        a_recent = statistics.mean(a[-compare_days:]) if a else 0
        for r in results:
            if r["title"] == anchor_name:
                continue
            s = _series(r, start, end)
            recent = statistics.mean(s[-compare_days:])
            prev = statistics.mean(s[-2 * compare_days:-compare_days])
            change = ((recent - prev) / prev * 100) if prev > 0 else (100.0 if recent > 0 else 0.0)
            level = (recent / a_recent * 100) if a_recent > 0 else None
            peak = max(s) if s else 0
            rows.append({
                "name": r["title"],
                "keywords": r.get("keywords", []),
                "level": level,
                "change": change,
                "at_peak": change >= 15 and peak > 0 and statistics.mean(s[-3:]) >= peak * 0.8,
                "spark": sparkline(s[-compare_days * 2:]),
            })
    rows.sort(key=lambda x: x["change"], reverse=True)
    return rows


def sparkline(values: list[float]) -> str:
    bars = "▁▂▃▄▅▆▇█"
    if not values or max(values) == 0:
        return ""
    # 이틀씩 묶어서 짧게
    vals = [statistics.mean(values[i:i + 2]) for i in range(0, len(values), 2)]
    hi = max(vals)
    return "".join(bars[min(int(v / hi * (len(bars) - 1)), len(bars) - 1)] for v in vals)


def collect_naver(cfg: dict, client_id: str, client_secret: str, today: dt.date) -> dict:
    end = today - dt.timedelta(days=1)  # 오늘은 아직 덜 쌓였으니 어제까지
    start = end - dt.timedelta(days=cfg.get("days", 56) - 1)
    anchor = cfg["anchor"]
    groups = cfg.get("keyword_groups", [])
    batches, warnings = [], []
    for batch in chunks(groups, 4):  # 한 번에 5그룹까지 → 기준 1 + 비교 4
        try:
            batches.append(naver_request(client_id, client_secret, start.isoformat(), end.isoformat(),
                                         [anchor] + list(batch)))
        except RuntimeError as e:
            warnings.append(str(e))
    rows = summarize_naver(batches, anchor["name"], start, end, cfg.get("compare_days", 14))
    return {"rows": rows, "warnings": warnings, "start": start, "end": end}


def signal(change: float) -> str:
    if change >= 50:
        return "🔥 급상승"
    if change >= 15:
        return "⬆ 상승"
    if change <= -30:
        return "⬇ 하락"
    return "보합"


# ---------------------------------------------------------------------------
# 리포트
# ---------------------------------------------------------------------------

def match_ideas(naver_rows, video_rows, trends) -> list[dict]:
    """검색량이 오르는 키워드 × 실제로 터진 영상 × 오늘 급상승 검색어를 엮어 후보를 만듦"""
    ideas = []
    for nr in naver_rows:
        if nr["change"] < 15:
            continue
        terms = [nr["name"]] + nr["keywords"]
        hits = [v for v in video_rows if any(t.replace(" ", "") in v["title"].replace(" ", "") for t in terms)]
        trend_hits = [t["title"] for t in trends
                      if any(term.replace(" ", "") in (t["title"] + " ".join(n.get("title", "") for n in t["news"])).replace(" ", "")
                             for term in terms)]
        ideas.append({"name": nr["name"], "change": nr["change"], "videos": hits[:3], "trends": trend_hits[:3]})
    ideas.sort(key=lambda i: (len(i["videos"]) > 0, i["change"]), reverse=True)
    return ideas[:6]


def render_report(now: dt.datetime, trends: dict, youtube: dict, naver: dict) -> str:
    L = []
    L.append(f"# 월급실험실 트렌드 리포트 — {now:%Y-%m-%d} ({WEEKDAYS[now.weekday()]})")
    L.append("")
    L.append(f"생성 시각: {now:%H:%M} KST · 숫자는 모두 추정치예요.")
    L.append("")

    # 요약
    L.append("## 오늘의 요약")
    summary = []
    if naver.get("rows"):
        top = [r for r in naver["rows"] if r["change"] >= 15][:3]
        if top:
            summary.append("네이버 검색 상승: " + ", ".join(f"{r['name']}({r['change']:+.0f}%)" for r in top))
    if youtube.get("rows"):
        best = [r for r in youtube["rows"] if r["ratio"]][:1]
        if best:
            b = best[0]
            summary.append(f"이번 주 최대 아웃라이어: 「{md_escape(b['title'])}」 구독자의 {b['ratio']:.0f}배 조회")
    if trends.get("items"):
        rel = [t["title"] for t in trends["items"] if t.get("relevant_words")][:5]
        if rel:
            summary.append("채널과 연관된 급상승 검색어: " + ", ".join(rel))
    L.extend(f"- {s}" for s in summary) if summary else L.append("- 수집된 데이터가 없어요. 아래 경고를 확인하세요.")
    L.append("")

    # 조합 후보
    ideas = match_ideas(naver.get("rows", []), youtube.get("rows", []), trends.get("items", []))
    if ideas:
        L.append("## 오늘 노려볼 주제 후보")
        L.append("검색량이 오르고 있고, 실제로 터진 영상이 있는 주제부터 정렬했어요.")
        L.append("")
        for i, idea in enumerate(ideas, 1):
            L.append(f"**{i}. {idea['name']}** (네이버 검색 {idea['change']:+.0f}%)")
            for v in idea["videos"]:
                ratio = f"구독자의 {v['ratio']:.0f}배" if v["ratio"] else "구독자 비공개"
                L.append(f"- 터진 영상: [{md_escape(v['title'])}]({v['url']}) · {fmt_int(v['views'])}회 · {ratio}")
            if idea["trends"]:
                L.append(f"- 오늘 구글 급상승: {', '.join(idea['trends'])}")
            if not idea["videos"] and not idea["trends"]:
                L.append("- 검색은 오르는데 아직 터진 영상이 없음 → 선점 기회")
            L.append("")

    # 1. 구글 트렌드
    L.append("## 1. 구글 급상승 검색어 (한국)")
    if trends.get("error"):
        L.append(f"> 가져오지 못했어요: {trends['error']}")
    elif trends.get("items"):
        L.append("| 순위 | 검색어 | 검색량 | 채널 연관 | 관련 뉴스 |")
        L.append("|---|---|---|---|---|")
        for i, t in enumerate(trends["items"][:20], 1):
            rel = "✅ " + ", ".join(t["relevant_words"][:3]) if t.get("relevant_words") else ""
            news = t["news"][0] if t["news"] else {}
            news_md = f"[{md_escape(news.get('title', ''))[:40]}]({news['url']})" if news.get("url") else md_escape(news.get("title", ""))[:40]
            L.append(f"| {i} | {md_escape(t['title'])} | {t['traffic_text'] or '-'} | {rel} | {news_md} |")
    L.append("")

    # 2. 유튜브
    L.append(f"## 2. 유튜브 아웃라이어 (최근 {youtube.get('days', 7)}일)")
    if youtube.get("skipped"):
        L.append(f"> 건너뜀: {youtube['skipped']}")
    else:
        L.append("배수 = 조회수 ÷ 채널 구독자 수(1천 명 미만 채널은 1천으로 계산). 높을수록 채널 힘이 아니라 주제·제목·썸네일이 먹힌 영상이에요.")
        L.append("")
        rows = youtube.get("rows", [])
        top_n = youtube.get("top_n", 15)
        for label, subset in (("롱폼", [r for r in rows if not r["is_short"]]),
                              ("쇼츠", [r for r in rows if r["is_short"]])):
            L.append(f"### {label}")
            if not subset:
                L.append("해당 영상 없음")
                L.append("")
                continue
            L.append("| 배수 | 조회수 | 하루 평균 | 구독자 | 제목 | 채널 |")
            L.append("|---|---|---|---|---|---|")
            for r in subset[:top_n]:
                ratio = f"{r['ratio']:.1f}배" if r["ratio"] else "-"
                L.append(f"| {ratio} | {fmt_int(r['views'])} | {fmt_int(r['views_per_day'])} | {fmt_int(r['subs'])} | "
                         f"[{md_escape(r['title'])}]({r['url']}) | {md_escape(r['channel'])} |")
            L.append("")

        ta = analyze_titles([r for r in rows if r["ratio"]][:30])
        if ta:
            L.append("### 터진 영상 제목 패턴 (상위 30개)")
            L.append(f"- 평균 길이 {ta['avg_len']}자 · 숫자 포함 {ta['number']}% · 금액 포함 {ta['money']}% · "
                     f"따옴표 {ta['quote']}% · TOP N/가지 {ta['top_n']}% · 물음표 {ta['question']}% · 말줄임 {ta['ellipsis']}%")
            L.append("- 자주 나온 단어: " + ", ".join(f"{w}({c})" for w, c in ta["top_words"]))
            L.append("")
        L.append(f"API 사용량: 약 {youtube.get('units_used', 0)} / 10,000")
    L.append("")

    # 3. 네이버
    L.append("## 3. 네이버 검색량 추이")
    if naver.get("skipped"):
        L.append(f"> 건너뜀: {naver['skipped']}")
    elif naver.get("rows"):
        L.append(f"기간 {naver['start']} ~ {naver['end']} · 변화율 = 최근 {naver.get('compare_days', 14)}일 평균 vs 그 전 {naver.get('compare_days', 14)}일 · "
                 f"기준 대비 = '{naver.get('anchor', '')}' 검색량을 100으로 볼 때")
        L.append("")
        L.append("| 키워드 | 신호 | 변화율 | 기준 대비 | 추이(최근 4주) |")
        L.append("|---|---|---|---|---|")
        for r in naver["rows"]:
            level = f"{r['level']:.0f}" if r["level"] is not None else "-"
            peak = " · 최고치 근처" if r["at_peak"] else ""
            L.append(f"| {r['name']} | {signal(r['change'])}{peak} | {r['change']:+.0f}% | {level} | {r['spark']} |")
    L.append("")

    warnings = trends.get("warnings", []) + youtube.get("warnings", []) + naver.get("warnings", [])
    if warnings:
        L.append("## 경고")
        L.extend(f"- {md_escape(w)}" for w in warnings)
        L.append("")

    L.append("---")
    L.append("데이터: Google Trends 급상승 RSS · YouTube Data API v3 · NAVER API HUB 검색어 트렌드")
    return "\n".join(L) + "\n"


def run(config_path: str, out_dir: str | None = None, now: dt.datetime | None = None) -> Path:
    cfg = load_config(config_path)
    now = now or now_kst()

    # 1. 구글 트렌드
    gcfg = cfg.get("google_trends", {})
    trends: dict = {"warnings": []}
    try:
        trends["items"] = mark_relevance(fetch_google_trends(gcfg.get("geo", "KR")), gcfg.get("relevance_words", []))
    except Exception as e:  # 네트워크 문제 등
        trends["error"] = str(e)

    # 2. 유튜브
    ycfg = cfg.get("youtube", {})
    yt_key = os.environ.get("YOUTUBE_API_KEY")
    if yt_key:
        try:
            youtube = collect_youtube(ycfg, yt_key, now)
        except Exception as e:
            youtube = {"skipped": f"오류 — {e}", "warnings": []}
    else:
        youtube = {"skipped": "YOUTUBE_API_KEY가 설정되지 않았어요.", "warnings": []}
    youtube["days"] = ycfg.get("days", 7)
    youtube["top_n"] = ycfg.get("top_n", 15)

    # 3. 네이버
    ncfg = cfg.get("naver", {})
    nid, nsecret = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if nid and nsecret:
        try:
            naver = collect_naver(ncfg, nid, nsecret, now.date())
        except Exception as e:
            naver = {"skipped": f"오류 — {e}", "warnings": []}
    else:
        naver = {"skipped": "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 설정되지 않았어요.", "warnings": []}
    naver["anchor"] = ncfg.get("anchor", {}).get("name", "")
    naver["compare_days"] = ncfg.get("compare_days", 14)

    report = render_report(now, trends, youtube, naver)
    out = Path(out_dir or cfg.get("report", {}).get("out_dir", "reports"))
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{now:%Y-%m-%d}.md"
    path.write_text(report, encoding="utf-8")
    (out / "latest.md").write_text(report, encoding="utf-8")
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description="월급실험실 트렌드 리포트")
    p.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    p.add_argument("--out-dir", default=None)
    args = p.parse_args(argv)
    path = run(args.config, args.out_dir)
    print(f"리포트 생성: {path}")


if __name__ == "__main__":
    sys.exit(main())
