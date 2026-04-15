#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
국장 주간 경제뉴스 자동 수집 및 블로그 업데이트 스크립트
매주 GitHub Actions에서 자동 실행됩니다.
"""

import feedparser
import anthropic
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path


# ── RSS 피드 목록 ──────────────────────────────────────────────────────────────
RSS_FEEDS = [
    {"name": "한국경제",   "url": "https://www.hankyung.com/feed/economy"},
    {"name": "매일경제",   "url": "https://www.mk.co.kr/rss/30000001/"},
    {"name": "연합뉴스",   "url": "https://www.yna.co.kr/rss/economy.xml"},
    {"name": "이데일리",   "url": "https://rss.edaily.co.kr/edaily_allnews.xml"},
    {"name": "머니투데이", "url": "https://www.mt.co.kr/rss/news/news_list.xml"},
]

# 국장 관련 핵심 키워드
STOCK_KEYWORDS = [
    "코스피", "코스닥", "주식", "증시", "상장", "주가", "시가총액",
    "삼성전자", "SK하이닉스", "현대차", "LG전자", "카카오", "네이버",
    "외국인", "기관투자", "개인투자", "공매도", "IPO", "배당",
    "기준금리", "한국은행", "환율", "원달러",
    "반도체", "2차전지", "배터리", "바이오", "자동차주",
    "코스피200", "코스닥150", "ETF", "선물",
    "순매수", "순매도", "급등", "급락", "상한가", "하한가",
    "금리인상", "금리인하", "긴축", "유동성",
]

# 스타일 맵
SENTIMENT_COLOR = {"긍정": "#16a34a", "부정": "#dc2626", "중립": "#6b7280"}
SENTIMENT_BG    = {"긍정": "#dcfce7", "부정": "#fee2e2", "중립": "#f3f4f6"}
MOOD_EMOJI      = {"상승장": "📈", "하락장": "📉", "혼조세": "〰️"}
CATEGORY_COLOR  = {
    "시장동향":  "#2563eb",
    "종목분석":  "#7c3aed",
    "정책·금리": "#b45309",
    "외환·환율": "#0891b2",
    "산업·섹터": "#065f46",
}


# ── 뉴스 수집 ──────────────────────────────────────────────────────────────────
def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def collect_news() -> list:
    one_week_ago = datetime.now() - timedelta(days=7)
    articles = []
    seen = set()

    for feed_info in RSS_FEEDS:
        try:
            print(f"  [{feed_info['name']}] 수집 중...")
            feed = feedparser.parse(
                feed_info["url"],
                request_headers={"User-Agent": "Mozilla/5.0 (compatible; weekly-news-bot/1.0)"},
            )

            for entry in feed.entries[:40]:
                title = strip_html(entry.get("title", ""))
                if not title or title in seen:
                    continue

                # 날짜 파싱
                try:
                    tp = entry.get("published_parsed") or entry.get("updated_parsed")
                    pub_date = datetime(*tp[:6]) if tp else datetime.now()
                except Exception:
                    pub_date = datetime.now()

                if pub_date < one_week_ago:
                    continue

                summary = strip_html(entry.get("summary", entry.get("description", "")))[:600]
                full_text = title + " " + summary

                if not any(kw in full_text for kw in STOCK_KEYWORDS):
                    continue

                seen.add(title)
                articles.append({
                    "title":   title,
                    "summary": summary,
                    "link":    entry.get("link", ""),
                    "source":  feed_info["name"],
                    "date":    pub_date.strftime("%Y-%m-%d"),
                })

            print(f"  [{feed_info['name']}] 완료")
        except Exception as e:
            print(f"  [{feed_info['name']}] 실패: {e}")

    return articles


# ── Claude API 요약 ────────────────────────────────────────────────────────────
def summarize_with_claude(articles: list) -> dict:
    api_key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    articles_text = "\n\n".join(
        f"[{i+1}] 출처: {a['source']} | 날짜: {a['date']}\n제목: {a['title']}\n내용: {a['summary']}"
        for i, a in enumerate(articles[:60])
    )

    prompt = f"""아래는 이번 주 수집된 한국 주식시장(국장) 관련 뉴스 기사들입니다.

{articles_text}

위 뉴스를 분석하여 다음 JSON 형식으로만 응답해주세요. JSON 외 다른 텍스트는 쓰지 마세요.

{{
  "week_summary": "이번 주 코스피·코스닥 시장 흐름을 2~3문장으로 요약 (수치 포함)",
  "market_mood": "상승장 또는 하락장 또는 혼조세",
  "top_news": [
    {{
      "rank": 1,
      "title": "핵심 내용을 담은 뉴스 제목 (직접 작성, 원문 제목 아님)",
      "content": "2~3문장으로 핵심 내용 설명. 독자가 빠르게 파악할 수 있도록.",
      "source": "출처명",
      "link": "원문 링크 (없으면 빈 문자열)",
      "category": "시장동향 또는 종목분석 또는 정책·금리 또는 외환·환율 또는 산업·섹터",
      "sentiment": "긍정 또는 부정 또는 중립"
    }}
  ],
  "sector_highlights": [
    {{
      "sector": "섹터명",
      "change": "등락률 (정보 없으면 빈 문자열)",
      "summary": "한 문장 핵심 내용"
    }}
  ],
  "key_figures": [
    "코스피 XXXX 포인트 (전주 대비 ±X.X%)",
    "코스닥 XXX 포인트 (전주 대비 ±X.X%)"
  ]
}}

top_news는 중요도 순으로 7~10개 선별, sector_highlights는 주목할 섹터 3~5개."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    content = response.content[0].text.strip()
    json_match = re.search(r"\{[\s\S]*\}", content)
    return json.loads(json_match.group() if json_match else content)


# ── HTML 생성 ──────────────────────────────────────────────────────────────────
def build_news_cards(top_news: list) -> str:
    cards = ""
    for n in top_news:
        cat   = n.get("category", "시장동향")
        sent  = n.get("sentiment", "중립")
        link  = n.get("link", "")
        cc    = CATEGORY_COLOR.get(cat,  "#2563eb")
        sc    = SENTIMENT_COLOR.get(sent, "#6b7280")
        sb    = SENTIMENT_BG.get(sent,   "#f3f4f6")
        title = f'<a href="{link}" target="_blank" rel="noopener">{n["title"]}</a>' if link else n["title"]
        cards += f"""
        <article class="news-card">
          <div class="card-header">
            <span class="rank">#{n['rank']}</span>
            <span class="badge" style="background:{cc}18;color:{cc};border:1px solid {cc}40">{cat}</span>
            <span class="badge" style="background:{sb};color:{sc}">{sent}</span>
            <span class="source">{n.get('source','')}</span>
          </div>
          <h3 class="news-title">{title}</h3>
          <p class="news-content">{n.get('content','')}</p>
        </article>"""
    return cards


def build_sector_cards(sectors: list) -> str:
    cards = ""
    for s in sectors:
        change = s.get("change", "")
        change_html = f'<span class="change">{change}</span>' if change else ""
        cards += f"""
        <div class="sector-card">
          <div class="sector-name">{s['sector']} {change_html}</div>
          <div class="sector-summary">{s['summary']}</div>
        </div>"""
    return cards


def generate_html(summary: dict, week_display: str, archive_weeks: list) -> str:
    top_news  = summary.get("top_news", [])
    sectors   = summary.get("sector_highlights", [])
    figures   = summary.get("key_figures", [])
    mood      = summary.get("market_mood", "혼조세")
    mood_icon = MOOD_EMOJI.get(mood, "📊")

    news_cards   = build_news_cards(top_news)
    sector_cards = build_sector_cards(sectors)

    figures_html = "".join(f"<li>{fig}</li>" for fig in figures)
    figures_block = f'<ul class="figures">{figures_html}</ul>' if figures else ""

    archive_links = "".join(
        f'<a href="data/{wk}.html" class="archive-link">{wk}</a>'
        for wk in reversed(archive_weeks[-8:])
    )
    archive_block = (
        '<section class="section"><h2 class="section-title">지난 주 스크랩</h2>'
        f'<div class="archive-list">{archive_links}</div></section>'
    ) if archive_links else ""

    sector_block = (
        '<section class="section"><h2 class="section-title">섹터 하이라이트</h2>'
        f'<div class="sector-list">{sector_cards}</div></section>'
    ) if sector_cards else ""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>국장 주간 경제 스크랩 — {week_display}</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header>
    <div class="header-inner">
      <div class="logo">📊 국장 위클리</div>
      <div class="header-sub">매주 월요일 업데이트되는 국내 주식시장 뉴스 스크랩</div>
    </div>
  </header>

  <section class="hero">
    <div class="hero-inner">
      <div class="week-badge">{week_display} 주간 리포트</div>
      <div class="mood-badge">{mood_icon} 이번 주 시장: <strong>{mood}</strong></div>
      <p class="week-summary">{summary.get('week_summary', '')}</p>
      {figures_block}
    </div>
  </section>

  <main>
    <div class="content-grid">
      <div class="main-col">
        <section class="section">
          <h2 class="section-title">이번 주 주요 뉴스</h2>
          <div class="news-list">{news_cards}</div>
        </section>
      </div>
      <aside class="side-col">
        {sector_block}
        {archive_block}
      </aside>
    </div>
  </main>

  <footer>
    <p>자동 수집: 한국경제 · 매일경제 · 연합뉴스 · 이데일리 · 머니투데이</p>
    <p>마지막 업데이트: {now}</p>
  </footer>
</body>
</html>"""


# ── 메인 ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 52)
    print("  국장 주간 뉴스 스크랩 시작")
    print("=" * 52)

    # 1. 뉴스 수집
    print("\n[1/3] RSS 피드 수집 중...")
    articles = collect_news()
    print(f"  → 총 {len(articles)}개 기사 수집됨")

    if len(articles) < 5:
        print("수집된 기사가 너무 적습니다. 종료합니다.")
        return

    # 2. Claude API 요약
    print("\n[2/3] Claude API 요약 중...")
    summary_data = summarize_with_claude(articles)
    print("  → 요약 완료")

    # 3. 파일 저장
    print("\n[3/3] 파일 생성 중...")
    today        = datetime.now()
    week_key     = today.strftime("%Y-W%V")
    week_display = f"{today.year}년 {today.month}월 {today.day}일"

    root     = Path(__file__).parent.parent
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)

    # JSON 아카이브 저장
    payload = {
        "week":         week_key,
        "week_display": week_display,
        "collected_at": today.isoformat(),
        "raw_count":    len(articles),
        "summary":      summary_data,
    }
    with open(data_dir / f"{week_key}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 아카이브 주차 목록 (JSON 기준)
    archive_weeks = sorted(p.stem for p in data_dir.glob("*.json"))

    # index.html 재생성
    html = generate_html(summary_data, week_display, archive_weeks)
    with open(root / "index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  → index.html 업데이트 완료")
    print(f"  → data/{week_key}.json 저장 완료")
    print("\n모든 작업 완료!")


if __name__ == "__main__":
    main()
