"""실제 API를 부르지 않고, 응답을 흉내 낸 가짜 데이터로 전체 흐름을 검사합니다.

    pip install pytest
    pytest -q
    python tests/test_report.py   # 샘플 리포트(sample_report.md) 만들기
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import trend_report as tr  # noqa: E402

NOW = dt.datetime(2026, 11, 20, 7, 13, tzinfo=tr.KST)

TRENDS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>앤트로픽</title><ht:approx_traffic>2,000+</ht:approx_traffic>
  <ht:news_item><ht:news_item_title>앤트로픽, 새 AI 모델 공개</ht:news_item_title><ht:news_item_url>https://example.com/a</ht:news_item_url></ht:news_item></item>
<item><title>엔화</title><ht:approx_traffic>200+</ht:approx_traffic>
  <ht:news_item><ht:news_item_title>엔화 환율 900원 아래로</ht:news_item_title><ht:news_item_url>https://example.com/b</ht:news_item_url></ht:news_item></item>
<item><title>kt wiz</title><ht:approx_traffic>500+</ht:approx_traffic></item>
<item><title>회계사</title><ht:approx_traffic>100+</ht:approx_traffic>
  <ht:news_item><ht:news_item_title>AI 시대 회계사 채용 줄어</ht:news_item_title><ht:news_item_url>https://example.com/c</ht:news_item_url></ht:news_item></item>
</channel></rss>"""


def iso(days_ago):
    return (NOW - dt.timedelta(days=days_ago)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


VIDEOS = {
    "v1": ("따면 평생 간다던 자격증의 배신 TOP 7", "chA", 1_700_000, iso(5), "PT24M36S"),
    "v2": ("\"10년 뒤 몸값 3배\" AI 시대 귀해지는 직업 TOP7", "chA", 1_560_000, iso(6), "PT24M7S"),
    "v3": ("월 300 직장인 연말정산 130만원 돌려받은 방법", "chB", 210_000, iso(3), "PT11M2S"),
    "v4": ("청약 넣기 전에 꼭 보세요... 무순위 청약 현실", "chC", 48_000, iso(2), "PT9M40S"),
    "v5": ("연봉 4천 실수령액 공개", "chB", 520_000, iso(4), "PT45S"),
    "v6": ("조회수 적은 영상", "chC", 3_000, iso(1), "PT8M"),
    "v7": ("오래된 인기 영상", "chA", 9_000_000, iso(30), "PT10M"),
}
CHANNELS = {"chA": 120_000, "chB": 8_000, "chC": None}  # None = 구독자 비공개


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def fake_get(url, params=None, **kw):
    params = params or {}
    if "trends.google.com" in url:
        return FakeResp(text=TRENDS_XML)
    if url.endswith("/search"):
        q = params["q"]
        ids = {"자격증 추천": ["v1"], "AI 직업": ["v2"], "연말정산": ["v3", "v6"],
               "아파트 청약": ["v4"], "연봉 실수령액": ["v5"]}.get(q, [])
        return FakeResp(payload={"items": [{"id": {"videoId": i}} for i in ids]})
    if url.endswith("/videos") and params.get("chart") == "mostPopular":
        return FakeResp(payload={"items": [{"id": "v7"}, {"id": "v1"}]})
    if url.endswith("/videos"):
        items = []
        for vid in params["id"].split(","):
            title, ch, views, pub, dur = VIDEOS[vid]
            items.append({"id": vid, "snippet": {"title": title, "channelId": ch, "channelTitle": f"채널{ch}", "publishedAt": pub},
                          "statistics": {"viewCount": str(views), "likeCount": "100"},
                          "contentDetails": {"duration": dur}})
        return FakeResp(payload={"items": items})
    if url.endswith("/channels"):
        items = []
        for ch in params["id"].split(","):
            subs = CHANNELS[ch]
            stats = {"hiddenSubscriberCount": True} if subs is None else {"subscriberCount": str(subs), "hiddenSubscriberCount": False}
            items.append({"id": ch, "statistics": stats})
        return FakeResp(payload={"items": items})
    raise AssertionError(url)


def fake_post(url, data=None, **kw):
    body = json.loads(data)
    start = dt.date.fromisoformat(body["startDate"])
    end = dt.date.fromisoformat(body["endDate"])
    days = (end - start).days + 1
    results = []
    for g in body["keywordGroups"]:
        name = g["groupName"]
        out = []
        for i in range(days):
            day = start + dt.timedelta(days=i)
            if name == "연말정산":
                ratio = 10 + i * 1.5          # 꾸준히 상승
            elif name == "청약":
                ratio = 40 if i < days - 14 else 70
            elif name == "비트코인":
                ratio = 60 if i < days - 14 else 30
            else:
                ratio = 30
            out.append({"period": day.isoformat(), "ratio": ratio})
        results.append({"title": name, "keywords": g["keywords"], "data": out})
    return FakeResp(payload={"results": results})


def _patch(monkeypatch=None):
    if monkeypatch:
        monkeypatch.setattr(tr.requests, "get", fake_get)
        monkeypatch.setattr(tr.requests, "post", fake_post)
        monkeypatch.setenv("YOUTUBE_API_KEY", "x")
        monkeypatch.setenv("NAVER_CLIENT_ID", "x")
        monkeypatch.setenv("NAVER_CLIENT_SECRET", "x")
    else:
        import os
        tr.requests.get = fake_get
        tr.requests.post = fake_post
        os.environ.update(YOUTUBE_API_KEY="x", NAVER_CLIENT_ID="x", NAVER_CLIENT_SECRET="x")


def test_full_report(tmp_path, monkeypatch):
    _patch(monkeypatch)
    path = tr.run(str(ROOT / "config.yaml"), str(tmp_path), now=NOW)
    text = path.read_text(encoding="utf-8")
    assert (tmp_path / "latest.md").exists()
    for section in ("오늘의 요약", "구글 급상승", "유튜브 아웃라이어", "네이버 검색량", "오늘 노려볼 주제 후보"):
        assert section in text
    assert "엔화" in text and "✅" in text            # 연관 표시
    assert "조회수 적은 영상" not in text               # min_views 필터
    assert "오래된 인기 영상" not in text               # 기간 필터
    assert "연봉 4천 실수령액 공개" in text.split("### 쇼츠")[1]  # 45초 → 쇼츠
    assert "65.0배" in text                            # 520,000 / 8,000
    assert "연말정산" in text.split("오늘 노려볼 주제 후보")[1].split("## 1.")[0]


def test_without_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(tr.requests, "get", fake_get)
    for k in ("YOUTUBE_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    text = tr.run(str(ROOT / "config.yaml"), str(tmp_path), now=NOW).read_text(encoding="utf-8")
    assert "YOUTUBE_API_KEY가 설정되지 않았어요" in text
    assert "앤트로픽" in text


def test_helpers():
    assert tr.parse_duration("PT1H2M3S") == 3723
    assert tr.parse_duration("PT45S") == 45
    assert tr.parse_traffic("2,000+") == 2000
    assert tr.fmt_int(1_700_000) == "170.0만"


if __name__ == "__main__":
    _patch()
    out = ROOT / "sample"
    path = tr.run(str(ROOT / "config.yaml"), str(out), now=NOW)
    sample = out / "sample_report.md"
    sample.write_text("> ⚠️ 가짜 샘플 데이터로 만든 예시 리포트예요. 실제 숫자가 아니에요.\n\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    path.unlink()
    (out / "latest.md").unlink()
    print(f"샘플 리포트: {sample}")
