import os
import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

mcp = FastMCP("ETF Marketing Intelligence Server")

# ─────────────────────────────────────────────
# 도구 1: 네이버 검색 트렌드 조회
# ─────────────────────────────────────────────
@mcp.tool()
async def search_naver_trend(
    keywords: list[str],
    start_date: str,
    end_date: str,
    time_unit: str = "date"
) -> dict:
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
        "keywordGroups": keyword_groups
    }

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://openapi.naver.com/v1/datalab/search",
            json=body,
            headers=headers
        )
        data = response.json()

    return {
        "results": data,
        "ANALYSIS_GUIDE": (
            "⚠️ 이 수치는 절대 검색량이 아닙니다. "
            "조회 기간 내 최대값=100 기준 상대값입니다. "
            "반드시 '상대적 검색 관심도' 또는 '트렌드 지수'로 표현하고, "
            "절대 수치(예: 몇 명이 검색했다)처럼 말하지 마세요. "
            "여러 키워드를 동시에 조회한 경우, 각 그룹 내 최대값을 기준으로 정규화됩니다."
        )
    }


# ─────────────────────────────────────────────
# 도구 2: KODEX vs TIGER 트렌드 비교
# ─────────────────────────────────────────────
@mcp.tool()
async def compare_etf_brands(
    theme: str,
    start_date: str,
    end_date: str
) -> dict:
    """
    KODEX와 TIGER의 동일 테마 ETF 검색 트렌드를 비교합니다.
    theme: ETF 테마 (예: "반도체", "2차전지", "AI")
    start_date: 시작일 (예: "2024-01-01")
    end_date: 종료일 (예: "2024-12-31")
    """
    keyword_groups = [
        {"groupName": f"KODEX {theme}", "keywords": [f"KODEX {theme}"]},
        {"groupName": f"TIGER {theme}", "keywords": [f"TIGER {theme}"]}
    ]

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "date",
        "keywordGroups": keyword_groups
    }

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://openapi.naver.com/v1/datalab/search",
            json=body,
            headers=headers
        )
        data = response.json()

    return {
        "theme": theme,
        "comparison": data,
        "ANALYSIS_GUIDE": (
            f"⚠️ KODEX {theme}와 TIGER {theme}의 상대적 검색 트렌드 비교입니다. "
            "수치는 두 키워드 중 최대값=100 기준 상대값입니다. "
            "'A가 B보다 인기 있다'가 아니라 "
            "'A의 검색 관심도가 B보다 높게 나타났다'고 표현하세요. "
            "절대적 우열 판단이 아닌 상대적 트렌드 비교임을 명시하세요."
        )
    }


# ─────────────────────────────────────────────
# 도구 3: 유튜브 ETF 콘텐츠 검색
# ─────────────────────────────────────────────
@mcp.tool()
async def search_youtube_etf(
    query: str,
    max_results: int = 10,
    order: str = "viewCount",
    published_after: str = None
) -> dict:
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
        "key": YOUTUBE_API_KEY
    }

    if published_after:
        params["publishedAfter"] = published_after

    async with httpx.AsyncClient() as client:
        search_response = await client.get(
            "https://www.googleapis.com/youtube/v3/search",
            params=params
        )
        search_data = search_response.json()

    video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]

    stats_data = {}
    if video_ids:
        async with httpx.AsyncClient() as client:
            stats_response = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "statistics,snippet",
                    "id": ",".join(video_ids),
                    "key": YOUTUBE_API_KEY
                }
            )
            stats_data = stats_response.json()

    results = []
    for item in stats_data.get("items", []):
        results.append({
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "published_at": item["snippet"]["publishedAt"],
            "view_count": int(item["statistics"].get("viewCount", 0)),
            "like_count": int(item["statistics"].get("likeCount", 0)),
            "comment_count": int(item["statistics"].get("commentCount", 0)),
            "url": f"https://www.youtube.com/watch?v={item['id']}"
        })

    results.sort(key=lambda x: x["view_count"], reverse=True)

    return {
        "query": query,
        "total_found": len(results),
        "videos": results,
        "ANALYSIS_GUIDE": (
            "⚠️ 이 데이터는 유튜브 검색 결과 기준이며, "
            "전체 유튜브 콘텐츠를 완전히 포괄하지 않습니다. "
            "조회수는 누적 수치이므로 오래된 영상이 유리합니다. "
            "최신 콘텐츠 트렌드 파악 시 published_after 파라미터로 기간을 제한하세요. "
            "하루 유튜브 API 검색 쿼터는 100회로 제한됩니다."
        )
    }


# ─────────────────────────────────────────────
# 도구 4: 분석 가이드라인 조회
# ─────────────────────────────────────────────
@mcp.tool()
def get_analysis_guideline(topic: str = "general") -> dict:
    """
    ETF 마케팅 데이터 분석 시 반드시 준수해야 할 가이드라인을 반환합니다.
    topic: "naver"(네이버 트렌드), "youtube"(유튜브), "comparison"(브랜드 비교), "general"(전체)
    """
    guidelines = {
        "general": {
            "rules": [
                "모든 분석 결과에 데이터 출처와 조회 기간을 명시할 것",
                "네이버 트렌드 수치는 반드시 '상대값(0~100)'임을 밝힐 것",
                "유튜브 데이터는 검색 결과 기준이며 전수조사가 아님을 밝힐 것",
                "브랜드 간 비교 시 '우열'이 아닌 '차이'로 표현할 것",
                "단기 급등/급락은 이벤트·뉴스 등 외부 요인 가능성을 언급할 것"
            ]
        },
        "naver": {
            "rules": [
                "수치는 절대 검색량이 아닌 최대값 대비 상대 비율(0~100)",
                "동시 비교 그룹 간에만 상대 비교 가능 (다른 조회 결과와 교차 비교 불가)",
                "한 번에 최대 5개 키워드 그룹만 조회 가능",
                "최대 1년 단위 조회 권장"
            ]
        },
        "youtube": {
            "rules": [
                "하루 검색 쿼터 100회 제한 — 불필요한 중복 조회 금지",
                "조회수는 누적값이므로 업로드일 함께 제시",
                "검색어에 따라 결과 편향 가능 — 다양한 검색어로 교차 확인 권장",
                "쇼츠(Shorts)와 일반 영상이 혼재할 수 있음"
            ]
        },
        "comparison": {
            "rules": [
                "KODEX vs TIGER 비교 시 동일 조회에서 나온 수치만 비교",
                "검색 트렌드 ≠ 실제 거래량 또는 순자산 규모",
                "검색 관심도 높다고 반드시 투자 유입이 많은 것은 아님",
                "마케팅 인사이트 도출 시 트렌드 방향성(상승/하락)에 집중할 것"
            ]
        }
    }

    return guidelines.get(topic, guidelines["general"])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)