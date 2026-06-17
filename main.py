import os
import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
KRX_API_KEY = os.getenv("KRX_API_KEY")

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
# 도구 2: ETF 브랜드 간 트렌드 비교 (전 브랜드 지원)
# ─────────────────────────────────────────────
@mcp.tool()
async def compare_etf_brands(
    theme: str,
    brands: list[str] = None,
    start_date: str = None,
    end_date: str = None
) -> dict:
    """
    두 개 이상의 ETF 브랜드 간 네이버 검색 트렌드를 비교합니다.
    theme: ETF 테마 (예: "반도체", "2차전지", "AI", "미국S&P500")
    brands: 비교할 브랜드 리스트 (예: ["KODEX", "TIGER", "ACE"], 미입력 시 KODEX vs TIGER)
            지원 브랜드: KODEX, TIGER, RISE, ACE, PLUS, SOL, KIWOOM, HANARO, 1Q, KoAct, TIME, WON 등
    start_date: 시작일 (예: "2024-01-01", 미입력 시 3개월 전)
    end_date: 종료일 (예: "2024-12-31", 미입력 시 오늘)
    """
    import datetime

    if not brands:
        brands = ["KODEX", "TIGER"]

    if len(brands) > 5:
        return {"error": "네이버 API 제한으로 한 번에 최대 5개 브랜드만 비교 가능합니다."}

    if not end_date:
        end_date = datetime.date.today().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")

    keyword_groups = [
        {"groupName": f"{brand} {theme}", "keywords": [f"{brand} {theme}"]}
        for brand in brands
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
        "brands": brands,
        "period": f"{start_date} ~ {end_date}",
        "comparison": data,
        "ANALYSIS_GUIDE": (
            f"⚠️ {', '.join(brands)} 브랜드의 '{theme}' 테마 검색 트렌드 비교입니다. "
            "수치는 비교 그룹 중 최대값=100 기준 상대값입니다. "
            "한 번에 최대 5개 브랜드까지 비교 가능합니다. "
            "'A가 B보다 인기 있다'가 아니라 "
            "'A의 검색 관심도가 B보다 높게 나타났다'고 표현하세요."
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


# ─────────────────────────────────────────────
# 도구 5: KRX ETF 일별 시세 조회
# ─────────────────────────────────────────────
@mcp.tool()
async def get_krx_etf_price(
    etf_code: str,
    date: str = None
) -> dict:
    """
    KRX 정보데이터시스템 API로 ETF 일별 시세를 조회합니다.
    etf_code: ETF 종목코드 6자리 (예: "069500" = KODEX 200)
    date: 조회일자 (형식: "20240601", 미입력 시 가장 최근 영업일)
    """
    import datetime

    if not date:
        today = datetime.date.today()
        date = today.strftime("%Y%m%d")

    headers = {"AUTH_KEY": KRX_API_KEY}
    params = {"basDd": date}

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd.json",
            headers=headers,
            params=params,
            follow_redirects=True
        )
        data = response.json()

    # 전체 ETF 중 해당 종목코드만 필터링
    items = data.get("OutBlock_1", [])
    result = [item for item in items if item.get("ISU_CD", "").startswith(etf_code)]

    if not result:
        return {
            "message": f"종목코드 {etf_code}의 데이터를 찾을 수 없습니다. 날짜({date})가 영업일인지 확인해 주세요.",
            "ANALYSIS_GUIDE": "KRX 데이터는 전일 기준이며 익일 오전 8시에 업데이트됩니다. 당일 실시간 데이터는 제공되지 않습니다."
        }

    return {
        "etf_code": etf_code,
        "date": date,
        "data": result,
        "ANALYSIS_GUIDE": (
            "⚠️ KRX 데이터는 전일 기준입니다. 당일 실시간 시세가 아닙니다. "
            "종가(TDD_CLSPRC), 거래량(ACC_TRDVOL), 거래대금(ACC_TRDVAL), "
            "순자산(NETASST_TOTAMT) 등을 확인할 수 있습니다. "
            "순매수는 투자자별 거래 데이터를 별도 조회해야 합니다."
        )
    }


# ─────────────────────────────────────────────
# 도구 6: KRX ETF 투자자별 순매수 조회
# ─────────────────────────────────────────────
@mcp.tool()
async def get_krx_etf_investor(
    etf_code: str,
    date: str = None
) -> dict:
    """
    KRX 정보데이터시스템 API로 ETF 투자자별 순매수를 조회합니다.
    etf_code: ETF 종목코드 6자리 (예: "069500" = KODEX 200)
    date: 조회일자 (형식: "20240601", 미입력 시 가장 최근 영업일)
    """
    import datetime

    if not date:
        today = datetime.date.today()
        date = today.strftime("%Y%m%d")

    headers = {"AUTH_KEY": KRX_API_KEY}
    params = {"basDd": date}

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_invstrgnt_trd.json",
            headers=headers,
            params=params
        )
        data = response.json()

    items = data.get("OutBlock_1", [])
    result = [item for item in items if item.get("ISU_CD", "").startswith(etf_code)]

    if not result:
        return {
            "message": f"종목코드 {etf_code}의 투자자 데이터를 찾을 수 없습니다.",
            "ANALYSIS_GUIDE": "KRX 데이터는 전일 기준이며 익일 오전 8시에 업데이트됩니다."
        }

    return {
        "etf_code": etf_code,
        "date": date,
        "investor_data": result,
        "ANALYSIS_GUIDE": (
            "⚠️ 투자자별 순매수는 전일 기준입니다. "
            "개인(INVST_TP_NM='개인'), 외국인, 기관 등 투자자 유형별 "
            "순매수금액(NETBUY_TRDVAL)과 순매수수량(NETBUY_TRDVOL)을 확인할 수 있습니다. "
            "순매수 양수=매수우위, 음수=매도우위입니다."
        )
    }


# ─────────────────────────────────────────────
# 도구 7: ETF 마스터 - 종목명으로 티커 검색
# ─────────────────────────────────────────────
import pandas as pd

ETF_MASTER = None

def load_etf_master():
    global ETF_MASTER
    if ETF_MASTER is None:
        try:
            ETF_MASTER = pd.read_excel("etf_master_20260616.xlsx", dtype=str)
        except Exception as e:
            ETF_MASTER = pd.DataFrame()
    return ETF_MASTER

@mcp.tool()
def search_etf_master(query: str) -> dict:
    """
    ETF 마스터 파일에서 종목명, 운용사, 기초자산 등으로 ETF를 검색합니다.
    query: 검색어 (예: "우주항공", "삼성자산운용", "반도체", "069500")
    """
    df = load_etf_master()
    if df.empty:
        return {"error": "ETF 마스터 파일을 불러올 수 없습니다."}

    mask = df.apply(lambda row: row.astype(str).str.contains(query, case=False, na=False).any(), axis=1)
    result = df[mask].to_dict(orient="records")

    if not result:
        return {
            "message": f"'{query}'에 해당하는 ETF를 찾을 수 없습니다.",
            "tip": "종목명, 운용사명, 티커코드, 기초자산 등으로 검색해보세요."
        }

    return {
        "query": query,
        "count": len(result),
        "etf_list": result,
        "ANALYSIS_GUIDE": (
            "티커(ticker)를 확인한 후 get_krx_etf_price 도구에 전달하면 "
            "실제 시세 데이터를 조회할 수 있습니다."
        )
    }


# ─────────────────────────────────────────────
# 도구 8: 모니터링 채널 목록 조회
# ─────────────────────────────────────────────
CHANNEL_MASTER = None

def load_channel_master():
    global CHANNEL_MASTER
    if CHANNEL_MASTER is None:
        try:
            CHANNEL_MASTER = pd.read_excel(
                "youtube channels master final.xlsx",
                sheet_name="채널 분류표",
                dtype=str
            )
        except Exception as e:
            CHANNEL_MASTER = pd.DataFrame()
    return CHANNEL_MASTER

@mcp.tool()
def get_monitored_channels(
    tier: str = None,
    channel_type: str = None
) -> dict:
    """
    모니터링 대상 유튜브 채널 목록을 조회합니다.
    tier: 채널 체급 필터 - "Mega"(100만+), "Macro"(10만~), "Micro"(~10만), 미입력 시 전체
    channel_type: 유형 필터 - "ETF 전문", "리서치/종목분석형", "배당/월배당 특화",
                  "연금/절세 특화", "재테크 입문/동기부여", "거시경제/시황",
                  "라이프스타일+투자", 미입력 시 전체
    """
    df = load_channel_master()
    if df.empty:
        return {"error": "채널 마스터 파일을 불러올 수 없습니다."}

    if tier:
        df = df[df["Tier"].str.contains(tier, case=False, na=False)]

    if channel_type:
        df = df[df["채널 유형 태그"].str.contains(channel_type, case=False, na=False)]

    result = df[["채널명", "YouTube 주소", "구독자(약)", "Tier", "주요 주제", "채널 유형 태그"]].to_dict(orient="records")

    return {
        "tier_filter": tier or "전체",
        "type_filter": channel_type or "전체",
        "count": len(result),
        "channels": result,
        "ANALYSIS_GUIDE": (
            "이 채널 목록은 자체 모니터링 대상 채널입니다. "
            "채널명을 search_youtube_etf 도구의 검색어에 활용하거나, "
            "특정 채널의 ETF 언급 콘텐츠를 조회할 때 참고하세요."
        )
    }


# ─────────────────────────────────────────────
# 도구 9: 특정 채널의 ETF 언급 영상 검색
# ─────────────────────────────────────────────
@mcp.tool()
async def search_youtube_by_channel(
    etf_name: str,
    channel_name: str = None,
    tier: str = None,
    max_results: int = 5,
    published_after: str = None
) -> dict:
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
        return {"error": "채널 마스터 파일을 불러올 수 없습니다."}

    if channel_name:
        df = df[df["채널명"].str.contains(channel_name, case=False, na=False)]
    if tier:
        df = df[df["Tier"].str.contains(tier, case=False, na=False)]

    if df.empty:
        return {"error": "조건에 맞는 채널이 없습니다."}

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
            "key": YOUTUBE_API_KEY
        }
        if published_after:
            params["publishedAfter"] = published_after

        try:
            async with httpx.AsyncClient() as client:
                search_resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params=params
                )
                search_data = search_resp.json()

            video_ids = [item["id"]["videoId"] for item in search_data.get("items", []) if "videoId" in item.get("id", {})]

            if video_ids:
                async with httpx.AsyncClient() as client:
                    stats_resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "statistics,snippet",
                            "id": ",".join(video_ids),
                            "key": YOUTUBE_API_KEY
                        }
                    )
                    stats_data = stats_resp.json()

                for item in stats_data.get("items", []):
                    all_results.append({
                        "channel": ch_name,
                        "tier": row.get("Tier", ""),
                        "title": item["snippet"]["title"],
                        "published_at": item["snippet"]["publishedAt"],
                        "view_count": int(item["statistics"].get("viewCount", 0)),
                        "url": f"https://www.youtube.com/watch?v={item['id']}"
                    })

            searched_channels.append(ch_name)

        except Exception:
            continue

    all_results.sort(key=lambda x: x["view_count"], reverse=True)

    return {
        "etf_name": etf_name,
        "searched_channels": searched_channels,
        "total_found": len(all_results),
        "videos": all_results,
        "ANALYSIS_GUIDE": (
            "⚠️ 유튜브 API 쿼터(하루 100회)를 채널 수만큼 소모합니다. "
            "채널을 특정하거나 Tier 필터를 사용해 쿼터를 아껴 쓰세요. "
            "검색 결과는 채널명+ETF명 조합이므로 실제 언급 여부는 영상에서 확인 필요합니다."
        )
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)