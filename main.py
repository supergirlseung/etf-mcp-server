import os
import datetime
import httpx
import pandas as pd
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
KRX_API_KEY = os.getenv("KRX_API_KEY")

mcp = FastMCP("ETF Marketing Intelligence Server")


# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────

def _fmt_num(n) -> str:
    """숫자를 천 단위 콤마 문자열로 변환"""
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def _fmt_view(n: int) -> str:
    """조회수를 만 단위 약식으로 변환 (예: 12,341 → 1.2만)"""
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}억"
    if n >= 10_000:
        return f"{n / 10_000:.1f}만"
    return _fmt_num(n)


# ─────────────────────────────────────────────
# ETF / 채널 마스터 로더 (싱글턴)
# ─────────────────────────────────────────────

ETF_MASTER = None
CHANNEL_MASTER = None


def load_etf_master() -> pd.DataFrame:
    global ETF_MASTER
    if ETF_MASTER is None:
        try:
            ETF_MASTER = pd.read_excel("etf_master_20260616.xlsx", dtype=str)
        except Exception:
            ETF_MASTER = pd.DataFrame()
    return ETF_MASTER


def load_channel_master() -> pd.DataFrame:
    global CHANNEL_MASTER
    if CHANNEL_MASTER is None:
        try:
            CHANNEL_MASTER = pd.read_excel(
                "youtube channels master final.xlsx",
                sheet_name="채널 분류표",
                dtype=str,
            )
        except Exception:
            CHANNEL_MASTER = pd.DataFrame()
    return CHANNEL_MASTER


# ─────────────────────────────────────────────
# 도구 1: 네이버 검색 트렌드 조회
# ─────────────────────────────────────────────

@mcp.tool()
async def search_naver_trend(
    keywords: list[str],
    start_date: str,
    end_date: str,
    time_unit: str = "date",
) -> str:
    """
    네이버 데이터랩 API로 ETF 상품명의 검색 트렌드를 조회합니다.

    keywords: 조회할 ETF 상품명 리스트 (예: ["KODEX 반도체", "TIGER 반도체"])
    start_date: 시작일 (형식: "2024-01-01")
    end_date: 종료일 (형식: "2024-12-31")
    time_unit: 집계 단위 - "date"(일별), "week"(주별), "month"(월별)
    """
    keyword_groups = [{"groupName": kw, "keywords": [kw]} for kw in keywords]
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": time_unit,
        "keywordGroups": keyword_groups,
    }
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://openapi.naver.com/v1/datalab/search",
            json=body,
            headers=headers,
        )
    data = response.json()

    unit_label = {"date": "일별", "week": "주별", "month": "월별"}.get(time_unit, time_unit)
    actual_start = data.get("startDate", start_date)
    actual_end = data.get("endDate", end_date)

    lines = []
    lines.append("## 📊 네이버 검색 트렌드 분석")
    lines.append(f"**조회 기간:** {actual_start} ~ {actual_end} | **집계 단위:** {unit_label}\n")

    # 요약 표
    lines.append("### 키워드별 요약")
    lines.append("| ETF | 피크 지수 | 피크 시점 | 최근 지수 | 추세 |")
    lines.append("|---|:---:|---|:---:|:---:|")

    series_map = {}
    for group in data.get("results", []):
        title = group["title"]
        series = group["data"]
        if not series:
            continue
        series_map[title] = series
        peak = max(series, key=lambda x: x["ratio"])
        latest = series[-1]
        prev = series[-2] if len(series) >= 2 else latest
        trend = "▲" if latest["ratio"] > prev["ratio"] else ("▼" if latest["ratio"] < prev["ratio"] else "─")
        lines.append(
            f"| {title} | **{peak['ratio']:.1f}** | {peak['period']} "
            f"| {latest['ratio']:.1f} | {trend} |"
        )

    # 전체 시계열 (최근 10개 포인트)
    if series_map:
        lines.append("\n### 기간별 추이 (최근 데이터 기준)")
        all_periods = sorted({p["period"] for s in series_map.values() for p in s})
        recent_periods = all_periods[-10:]
        header = "| 기간 | " + " | ".join(series_map.keys()) + " |"
        sep = "|---|" + "|".join([":---:" for _ in series_map]) + "|"
        lines.append(header)
        lines.append(sep)
        for period in recent_periods:
            row = f"| {period} |"
            for series in series_map.values():
                match = next((p for p in series if p["period"] == period), None)
                row += f" {match['ratio']:.1f} |" if match else " - |"
            lines.append(row)

    lines.append(
        "\n> ⚠️ **분석 주의사항:** 수치는 조회 기간 내 최대값=100 기준 **상대적 검색 관심도**입니다. "
        "절대 검색량이 아니므로 '몇 명이 검색했다'는 표현은 사용하지 마세요. "
        "여러 키워드를 동시에 조회한 경우, 각 그룹 내 최대값을 기준으로 정규화됩니다."
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 도구 2: ETF 브랜드 간 트렌드 비교
# ─────────────────────────────────────────────

@mcp.tool()
async def compare_etf_brands(
    theme: str,
    start_date: str,
    end_date: str,
    brands: list[str] = None,
) -> str:
    """
    두 개 이상의 ETF 브랜드 간 네이버 검색 트렌드를 비교합니다.

    theme: ETF 테마 (예: "반도체", "2차전지", "AI", "미국S&P500")
    start_date: 시작일 (예: "2024-01-01")
    end_date: 종료일 (예: "2024-12-31")
    brands: 비교할 브랜드 리스트 (예: ["KODEX", "TIGER", "ACE"], 미입력 시 KODEX vs TIGER)
           지원 브랜드: KODEX, TIGER, RISE, ACE, PLUS, SOL, KIWOOM, HANARO, 1Q, KoAct, TIME, WON 등
    """
    if not brands:
        brands = ["KODEX", "TIGER"]

    if len(brands) > 5:
        return "❌ 네이버 API 제한으로 한 번에 최대 5개 브랜드만 비교 가능합니다."

    keyword_groups = [
        {"groupName": f"{brand} {theme}", "keywords": [f"{brand} {theme}"]}
        for brand in brands
    ]
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "week",
        "keywordGroups": keyword_groups,
    }
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://openapi.naver.com/v1/datalab/search",
            json=body,
            headers=headers,
        )
    data = response.json()

    actual_start = data.get("startDate", start_date)
    actual_end = data.get("endDate", end_date)

    lines = []
    lines.append(f"## 📊 ETF 브랜드 비교 — {theme} 테마")
    lines.append(f"**비교 브랜드:** {' vs '.join(brands)}")
    lines.append(f"**조회 기간:** {actual_start} ~ {actual_end} | **집계 단위:** 주별\n")

    # 브랜드별 요약
    lines.append("### 브랜드별 요약")
    lines.append("| 브랜드 | ETF명 | 피크 지수 | 피크 시점 | 최근 지수 | 평균 지수 |")
    lines.append("|---|---|:---:|---|:---:|:---:|")

    series_map = {}
    for group in data.get("results", []):
        title = group["title"]
        series = group["data"]
        if not series:
            continue
        series_map[title] = series
        peak = max(series, key=lambda x: x["ratio"])
        latest = series[-1]
        avg = sum(p["ratio"] for p in series) / len(series)
        brand = title.split()[0]
        lines.append(
            f"| {brand} | {title} | **{peak['ratio']:.1f}** | {peak['period']} "
            f"| {latest['ratio']:.1f} | {avg:.1f} |"
        )

    # 1위 브랜드 판정
    if series_map:
        avg_scores = {
            title: sum(p["ratio"] for p in s) / len(s)
            for title, s in series_map.items()
        }
        winner = max(avg_scores, key=avg_scores.get)
        lines.append(f"\n> 📌 **평균 검색 관심도 1위:** {winner} ({avg_scores[winner]:.1f})")

    # 주별 추이 표 (최근 8주)
    if series_map:
        lines.append("\n### 주별 추이 (최근 8주)")
        all_periods = sorted({p["period"] for s in series_map.values() for p in s})
        recent_periods = all_periods[-8:]
        header = "| 주 | " + " | ".join(series_map.keys()) + " |"
        sep = "|---|" + "|".join([":---:" for _ in series_map]) + "|"
        lines.append(header)
        lines.append(sep)
        for period in recent_periods:
            row = f"| {period} |"
            for series in series_map.values():
                match = next((p for p in series if p["period"] == period), None)
                row += f" {match['ratio']:.1f} |" if match else " - |"
            lines.append(row)

    lines.append(
        "\n> ⚠️ **분석 주의사항:** 수치는 비교 그룹 중 최대값=100 기준 상대값입니다. "
        "검색 관심도는 실제 거래량·순자산과 다를 수 있습니다."
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 도구 3: 유튜브 ETF 콘텐츠 검색
# ─────────────────────────────────────────────

@mcp.tool()
async def search_youtube_etf(
    query: str,
    max_results: int = 10,
    order: str = "viewCount",
    published_after: str = None,
) -> str:
    """
    유튜브에서 ETF 관련 콘텐츠를 검색합니다.

    query: 검색어 (예: "KODEX 반도체 ETF")
    max_results: 결과 수 (최대 50, 기본 10)
    order: 정렬 기준 - "viewCount"(조회수), "date"(최신순), "relevance"(관련성)
    published_after: 특정 날짜 이후 영상만 (예: "2024-01-01T00:00:00Z")
    """
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "order": order,
        "regionCode": "KR",
        "relevanceLanguage": "ko",
        "key": YOUTUBE_API_KEY,
    }
    if published_after:
        params["publishedAfter"] = published_after

    async with httpx.AsyncClient() as client:
        search_response = await client.get(
            "https://www.googleapis.com/youtube/v3/search", params=params
        )
        search_data = search_response.json()

    video_ids = [
        item["id"]["videoId"]
        for item in search_data.get("items", [])
        if "videoId" in item.get("id", {})
    ]

    if not video_ids:
        return f"## 🔍 유튜브 검색 결과\n**검색어:** {query}\n\n검색 결과가 없습니다."

    async with httpx.AsyncClient() as client:
        stats_response = await client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "statistics,snippet",
                "id": ",".join(video_ids),
                "key": YOUTUBE_API_KEY,
            },
        )
        stats_data = stats_response.json()

    results = []
    for item in stats_data.get("items", []):
        published = item["snippet"]["publishedAt"][:10]
        results.append({
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "published_at": published,
            "view_count": int(item["statistics"].get("viewCount", 0)),
            "like_count": int(item["statistics"].get("likeCount", 0)),
            "comment_count": int(item["statistics"].get("commentCount", 0)),
            "url": f"https://www.youtube.com/watch?v={item['id']}",
        })

    results.sort(key=lambda x: x["view_count"], reverse=True)

    order_label = {"viewCount": "조회수순", "date": "최신순", "relevance": "관련성순"}.get(order, order)
    period_note = f" | **{published_after[:10]} 이후**" if published_after else ""

    lines = []
    lines.append("## 🎬 유튜브 ETF 콘텐츠 검색 결과")
    lines.append(f"**검색어:** {query} | **정렬:** {order_label}{period_note}")
    lines.append(f"**검색 결과:** {len(results)}개\n")

    lines.append("| # | 제목 | 채널 | 업로드일 | 조회수 | 좋아요 |")
    lines.append("|:---:|---|---|:---:|:---:|:---:|")

    for i, v in enumerate(results, 1):
        title_link = f"[{v['title'][:35]}{'...' if len(v['title']) > 35 else ''}]({v['url']})"
        lines.append(
            f"| {i} | {title_link} | {v['channel']} | {v['published_at']} "
            f"| {_fmt_view(v['view_count'])} | {_fmt_view(v['like_count'])} |"
        )

    # 채널별 집계
    channel_counts: dict[str, int] = {}
    channel_views: dict[str, int] = {}
    for v in results:
        channel_counts[v["channel"]] = channel_counts.get(v["channel"], 0) + 1
        channel_views[v["channel"]] = channel_views.get(v["channel"], 0) + v["view_count"]

    if len(channel_counts) > 1:
        lines.append("\n### 채널별 집계")
        lines.append("| 채널 | 영상 수 | 총 조회수 |")
        lines.append("|---|:---:|:---:|")
        for ch, cnt in sorted(channel_counts.items(), key=lambda x: -channel_views[x[0]]):
            lines.append(f"| {ch} | {cnt} | {_fmt_view(channel_views[ch])} |")

    lines.append(
        "\n> ⚠️ **분석 주의사항:** 유튜브 검색 결과 기준이며 전수조사가 아닙니다. "
        "조회수는 누적값으로 오래된 영상이 유리합니다. "
        "하루 API 쿼터 100회 제한이 있습니다."
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 도구 4: 분석 가이드라인 조회
# ─────────────────────────────────────────────

@mcp.tool()
def get_analysis_guideline(topic: str = "general") -> str:
    """
    ETF 마케팅 데이터 분석 시 반드시 준수해야 할 가이드라인을 반환합니다.

    topic: "naver"(네이버 트렌드), "youtube"(유튜브), "comparison"(브랜드 비교), "general"(전체)
    """
    guidelines = {
        "general": {
            "title": "ETF 마케팅 데이터 분석 공통 가이드라인",
            "rules": [
                "모든 분석 결과에 데이터 출처와 조회 기간을 명시할 것",
                "네이버 트렌드 수치는 반드시 '상대값(0~100)'임을 밝힐 것",
                "유튜브 데이터는 검색 결과 기준이며 전수조사가 아님을 밝힐 것",
                "브랜드 간 비교 시 '우열'이 아닌 '차이'로 표현할 것",
                "단기 급등/급락은 이벤트·뉴스 등 외부 요인 가능성을 언급할 것",
            ],
        },
        "naver": {
            "title": "네이버 트렌드 분석 가이드라인",
            "rules": [
                "수치는 절대 검색량이 아닌 최대값 대비 상대 비율(0~100)",
                "동시 비교 그룹 간에만 상대 비교 가능 (다른 조회 결과와 교차 비교 불가)",
                "한 번에 최대 5개 키워드 그룹만 조회 가능",
                "최대 1년 단위 조회 권장",
            ],
        },
        "youtube": {
            "title": "유튜브 데이터 분석 가이드라인",
            "rules": [
                "하루 검색 쿼터 100회 제한 — 불필요한 중복 조회 금지",
                "조회수는 누적값이므로 업로드일 함께 제시",
                "검색어에 따라 결과 편향 가능 — 다양한 검색어로 교차 확인 권장",
                "쇼츠(Shorts)와 일반 영상이 혼재할 수 있음",
            ],
        },
        "comparison": {
            "title": "브랜드 비교 분석 가이드라인",
            "rules": [
                "KODEX vs TIGER 비교 시 동일 조회에서 나온 수치만 비교",
                "검색 트렌드 ≠ 실제 거래량 또는 순자산 규모",
                "검색 관심도 높다고 반드시 투자 유입이 많은 것은 아님",
                "마케팅 인사이트 도출 시 트렌드 방향성(상승/하락)에 집중할 것",
            ],
        },
    }

    g = guidelines.get(topic, guidelines["general"])

    lines = []
    lines.append(f"## 📋 {g['title']}")
    for i, rule in enumerate(g["rules"], 1):
        lines.append(f"{i}. {rule}")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 도구 5: KRX ETF 일별 시세 조회
# ─────────────────────────────────────────────

@mcp.tool()
async def get_krx_etf_price(
    etf_code: str,
    date: str = None,
) -> str:
    """
    KRX 정보데이터시스템 API로 ETF 일별 시세를 조회합니다.

    etf_code: ETF 종목코드 6자리 (예: "069500" = KODEX 200)
    date: 조회일자 (형식: "20240601", 미입력 시 가장 최근 영업일)
    """
    if not date:
        date = datetime.date.today().strftime("%Y%m%d")

    headers = {"AUTH_KEY": KRX_API_KEY}
    params = {"basDd": date}

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd.json",
            headers=headers,
            params=params,
            follow_redirects=True,
        )
    data = response.json()

    items = data.get("OutBlock_1", [])
    result = [item for item in items if item.get("ISU_CD", "").startswith(etf_code)]

    if not result:
        return (
            f"## 📈 KRX ETF 시세 조회\n"
            f"**종목코드:** {etf_code} | **조회일:** {date}\n\n"
            f"⚠️ 데이터를 찾을 수 없습니다. 날짜({date})가 영업일인지 확인해 주세요.\n\n"
            "> KRX 데이터는 전일 기준이며 익일 오전 8시에 업데이트됩니다."
        )

    item = result[0]
    etf_name = item.get("ISU_NM", etf_code)

    lines = []
    lines.append("## 📈 KRX ETF 시세")
    lines.append(f"**종목:** {etf_name} ({etf_code}) | **기준일:** {date}\n")

    lines.append("| 항목 | 수치 |")
    lines.append("|---|:---:|")
    lines.append(f"| 종가 | **{_fmt_num(item.get('TDD_CLSPRC', '-'))}원** |")
    lines.append(f"| 시가 | {_fmt_num(item.get('TDD_OPNPRC', '-'))}원 |")
    lines.append(f"| 고가 | {_fmt_num(item.get('TDD_HGPRC', '-'))}원 |")
    lines.append(f"| 저가 | {_fmt_num(item.get('TDD_LWPRC', '-'))}원 |")
    lines.append(f"| 거래량 | {_fmt_num(item.get('ACC_TRDVOL', '-'))}주 |")
    lines.append(f"| 거래대금 | {_fmt_num(item.get('ACC_TRDVAL', '-'))}원 |")
    lines.append(f"| 순자산총액 | {_fmt_num(item.get('NETASST_TOTAMT', '-'))}원 |")
    lines.append(f"| NAV | {_fmt_num(item.get('NAV', '-'))}원 |")

    lines.append(
        "\n> ⚠️ **분석 주의사항:** KRX 데이터는 전일 기준입니다. "
        "당일 실시간 시세가 아닙니다."
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 도구 6: KRX ETF 투자자별 순매수 조회
# ─────────────────────────────────────────────

@mcp.tool()
async def get_krx_etf_investor(
    etf_code: str,
    date: str = None,
) -> str:
    """
    KRX 정보데이터시스템 API로 ETF 투자자별 순매수를 조회합니다.

    etf_code: ETF 종목코드 6자리 (예: "069500" = KODEX 200)
    date: 조회일자 (형식: "20240601", 미입력 시 가장 최근 영업일)
    """
    if not date:
        date = datetime.date.today().strftime("%Y%m%d")

    headers = {"AUTH_KEY": KRX_API_KEY}
    params = {"basDd": date}

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_invstrgnt_trd.json",
            headers=headers,
            params=params,
        )
    data = response.json()

    items = data.get("OutBlock_1", [])
    result = [item for item in items if item.get("ISU_CD", "").startswith(etf_code)]

    if not result:
        return (
            f"## 👥 KRX ETF 투자자별 순매수\n"
            f"**종목코드:** {etf_code} | **조회일:** {date}\n\n"
            f"⚠️ 데이터를 찾을 수 없습니다.\n\n"
            "> KRX 데이터는 전일 기준이며 익일 오전 8시에 업데이트됩니다."
        )

    lines = []
    lines.append("## 👥 KRX ETF 투자자별 순매수")
    etf_name = result[0].get("ISU_NM", etf_code)
    lines.append(f"**종목:** {etf_name} ({etf_code}) | **기준일:** {date}\n")

    lines.append("| 투자자 | 순매수금액 (원) | 순매수수량 (주) | 방향 |")
    lines.append("|---|:---:|:---:|:---:|")

    for item in result:
        investor = item.get("INVST_TP_NM", "-")
        net_val = int(item.get("NETBUY_TRDVAL", 0))
        net_vol = int(item.get("NETBUY_TRDVOL", 0))
        direction = "▲ 매수우위" if net_val > 0 else ("▼ 매도우위" if net_val < 0 else "─ 중립")
        lines.append(
            f"| {investor} | {_fmt_num(net_val)} | {_fmt_num(net_vol)} | {direction} |"
        )

    lines.append(
        "\n> ⚠️ **분석 주의사항:** 순매수 양수=매수우위, 음수=매도우위입니다. "
        "전일 기준 데이터입니다."
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 도구 7: ETF 마스터 - 종목명으로 티커 검색
# ─────────────────────────────────────────────

@mcp.tool()
def search_etf_master(query: str) -> str:
    """
    ETF 마스터 파일에서 종목명, 운용사, 기초자산 등으로 ETF를 검색합니다.

    query: 검색어 (예: "우주항공", "삼성자산운용", "반도체", "069500")
    """
    df = load_etf_master()

    if df.empty:
        return "❌ ETF 마스터 파일을 불러올 수 없습니다."

    mask = df.apply(
        lambda row: row.astype(str).str.contains(query, case=False, na=False).any(),
        axis=1,
    )
    result_df = df[mask]

    if result_df.empty:
        return (
            f"## 🔎 ETF 마스터 검색 결과\n"
            f"**검색어:** {query}\n\n"
            f"'{query}'에 해당하는 ETF를 찾을 수 없습니다.\n\n"
            "> 종목명, 운용사명, 티커코드, 기초자산 등으로 검색해보세요."
        )

    lines = []
    lines.append("## 🔎 ETF 마스터 검색 결과")
    lines.append(f"**검색어:** {query} | **검색 결과:** {len(result_df)}개\n")

    # 컬럼 자동 감지 (파일 구조에 따라 유연하게 처리)
    cols = result_df.columns.tolist()
    display_cols = cols[:8]  # 최대 8개 컬럼 표시

    header = "| " + " | ".join(display_cols) + " |"
    sep = "|" + "|".join(["---|" for _ in display_cols])
    lines.append(header)
    lines.append(sep)

    for _, row in result_df.head(20).iterrows():
        cells = [str(row.get(c, "-"))[:30] for c in display_cols]
        lines.append("| " + " | ".join(cells) + " |")

    if len(result_df) > 20:
        lines.append(f"\n> 전체 {len(result_df)}개 중 상위 20개만 표시됩니다.")

    lines.append(
        "\n> 💡 **활용 팁:** 티커코드를 확인한 후 `get_krx_etf_price` 도구에 전달하면 "
        "실제 시세 데이터를 조회할 수 있습니다."
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 도구 8: 모니터링 채널 목록 조회
# ─────────────────────────────────────────────

@mcp.tool()
def get_monitored_channels(
    tier: str = None,
    channel_type: str = None,
) -> str:
    """
    모니터링 대상 유튜브 채널 목록을 조회합니다.

    tier: 채널 체급 필터 - "Mega"(100만+), "Macro"(10만~), "Micro"(~10만), 미입력 시 전체
    channel_type: 유형 필터 - "ETF 전문", "리서치/종목분석형", "배당/월배당 특화",
                  "연금/절세 특화", "재테크 입문/동기부여", "거시경제/시황",
                  "라이프스타일+투자", 미입력 시 전체
    """
    df = load_channel_master()

    if df.empty:
        return "❌ 채널 마스터 파일을 불러올 수 없습니다."

    if tier:
        df = df[df["Tier"].str.contains(tier, case=False, na=False)]
    if channel_type:
        df = df[df["채널 유형 태그"].str.contains(channel_type, case=False, na=False)]

    lines = []
    lines.append("## 📺 모니터링 채널 목록")
    lines.append(
        f"**Tier 필터:** {tier or '전체'} | "
        f"**유형 필터:** {channel_type or '전체'} | "
        f"**총 {len(df)}개 채널**\n"
    )

    # Tier별 그룹핑
    for t in ["Mega", "Macro", "Micro"]:
        group = df[df["Tier"].str.contains(t, case=False, na=False)] if "Tier" in df.columns else pd.DataFrame()
        if group.empty:
            continue
        lines.append(f"### {t} 채널 ({len(group)}개)")
        lines.append("| 채널명 | 구독자 | 주요 주제 | 유형 태그 |")
        lines.append("|---|:---:|---|---|")
        for _, row in group.iterrows():
            name = str(row.get("채널명", "-"))
            url = str(row.get("YouTube 주소", ""))
            subs = str(row.get("구독자(약)", "-"))
            topic = str(row.get("주요 주제", "-"))[:30]
            tag = str(row.get("채널 유형 태그", "-"))
            name_cell = f"[{name}]({url})" if url.startswith("http") else name
            lines.append(f"| {name_cell} | {subs} | {topic} | {tag} |")
        lines.append("")

    lines.append(
        "> 💡 **활용 팁:** 채널명을 `search_youtube_by_channel` 도구에 전달하면 "
        "해당 채널의 ETF 언급 영상을 조회할 수 있습니다."
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 도구 9: 특정 채널의 ETF 언급 영상 검색
# ─────────────────────────────────────────────

@mcp.tool()
async def search_youtube_by_channel(
    etf_name: str,
    channel_name: str = None,
    tier: str = None,
    max_results: int = 5,
    published_after: str = None,
) -> str:
    """
    모니터링 채널 내에서 특정 ETF 언급 영상을 검색합니다.

    etf_name: 검색할 ETF명 (예: "KODEX 반도체")
    channel_name: 특정 채널명 (예: "수페TV"), 미입력 시 전체 모니터링 채널 대상
    tier: 채널 체급 필터 - "Mega", "Macro", "Micro"
    max_results: 채널당 최대 결과 수 (기본 5)
    published_after: 특정 날짜 이후 영상만 (예: "2024-01-01T00:00:00Z")
    """
    df = load_channel_master()

    if df.empty:
        return "❌ 채널 마스터 파일을 불러올 수 없습니다."

    if channel_name:
        df = df[df["채널명"].str.contains(channel_name, case=False, na=False)]
    if tier:
        df = df[df["Tier"].str.contains(tier, case=False, na=False)]

    if df.empty:
        return "❌ 조건에 맞는 채널이 없습니다."

    all_results = []
    searched_channels = []

    for _, row in df.iterrows():
        ch_name = row.get("채널명", "")
        query = f"{etf_name} {ch_name}"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "order": "date",
            "regionCode": "KR",
            "relevanceLanguage": "ko",
            "key": YOUTUBE_API_KEY,
        }
        if published_after:
            params["publishedAfter"] = published_after

        try:
            async with httpx.AsyncClient() as client:
                search_resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/search", params=params
                )
                search_data = search_resp.json()

            video_ids = [
                item["id"]["videoId"]
                for item in search_data.get("items", [])
                if "videoId" in item.get("id", {})
            ]

            if video_ids:
                async with httpx.AsyncClient() as client:
                    stats_resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "statistics,snippet",
                            "id": ",".join(video_ids),
                            "key": YOUTUBE_API_KEY,
                        },
                    )
                    stats_data = stats_resp.json()

                for item in stats_data.get("items", []):
                    all_results.append({
                        "channel": ch_name,
                        "tier": row.get("Tier", ""),
                        "title": item["snippet"]["title"],
                        "published_at": item["snippet"]["publishedAt"][:10],
                        "view_count": int(item["statistics"].get("viewCount", 0)),
                        "url": f"https://www.youtube.com/watch?v={item['id']}",
                    })
                searched_channels.append(ch_name)

        except Exception:
            continue

    all_results.sort(key=lambda x: x["view_count"], reverse=True)

    period_note = f" | **{published_after[:10]} 이후**" if published_after else ""
    tier_note = f" | **{tier} 채널**" if tier else ""

    lines = []
    lines.append(f"## 🎬 채널별 ETF 언급 영상 — {etf_name}")
    lines.append(
        f"**검색 채널:** {', '.join(searched_channels) if searched_channels else '없음'}"
        f"{tier_note}{period_note}"
    )
    lines.append(f"**검색 결과:** {len(all_results)}개\n")

    if not all_results:
        lines.append("관련 영상을 찾을 수 없습니다.")
    else:
        lines.append("| # | 제목 | 채널 | Tier | 업로드일 | 조회수 |")
        lines.append("|:---:|---|---|:---:|:---:|:---:|")
        for i, v in enumerate(all_results, 1):
            title_link = f"[{v['title'][:35]}{'...' if len(v['title']) > 35 else ''}]({v['url']})"
            lines.append(
                f"| {i} | {title_link} | {v['channel']} | {v['tier']} "
                f"| {v['published_at']} | {_fmt_view(v['view_count'])} |"
            )

    lines.append(
        "\n> ⚠️ **분석 주의사항:** 유튜브 API 쿼터(하루 100회)를 채널 수만큼 소모합니다. "
        "채널을 특정하거나 Tier 필터를 사용해 쿼터를 아껴 쓰세요. "
        "검색 결과는 채널명+ETF명 조합이므로 실제 언급 여부는 영상에서 확인 필요합니다."
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)