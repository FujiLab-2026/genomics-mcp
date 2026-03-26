from mcp.server.fastmcp import FastMCP
import httpx
import asyncio

mcp = FastMCP("SemanticScholar")

BASE_URL = "https://api.semanticscholar.org/graph/v1"
REC_URL = "https://api.semanticscholar.org/recommendations/v1/papers"

# レートリミット対策（1秒1リクエスト）
_last_request_time = 0


async def _rate_limit():
    """APIレートリミット（1秒1リクエスト）を守る"""
    global _last_request_time
    now = asyncio.get_event_loop().time()
    elapsed = now - _last_request_time
    if elapsed < 1.0:
        await asyncio.sleep(1.0 - elapsed)
    _last_request_time = asyncio.get_event_loop().time()


async def _get_json(url: str, params: dict = None) -> dict:
    """Semantic Scholar APIへのGETリクエスト"""
    await _rate_limit()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params or {})
        if resp.status_code == 404:
            return {"error": "Not found (404)"}
        if resp.status_code == 429:
            return {"error": "Rate limit exceeded. Please wait and retry."}
        if resp.status_code != 200:
            return {"error": f"API Error: {resp.status_code} - {resp.text[:300]}"}
        try:
            return resp.json()
        except Exception:
            return {"error": f"JSON parse error: {resp.text[:300]}"}


async def _post_json(url: str, json_body: dict, params: dict = None) -> dict:
    """Semantic Scholar APIへのPOSTリクエスト"""
    await _rate_limit()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=json_body, params=params or {})
        if resp.status_code != 200:
            return {"error": f"API Error: {resp.status_code} - {resp.text[:300]}"}
        try:
            return resp.json()
        except Exception:
            return {"error": f"JSON parse error: {resp.text[:300]}"}


def _format_paper(paper: dict, include_abstract: bool = False) -> str:
    """論文情報を整形して文字列で返す"""
    if not paper:
        return "（データなし）"

    lines = []

    title = paper.get("title", "N/A")
    paper_id = paper.get("paperId", "")
    lines.append(f"📄 {title}")

    # 著者
    authors = paper.get("authors")
    if authors:
        author_names = [a.get("name", "") for a in authors[:5]]
        if len(authors) > 5:
            author_names.append(f"... (+{len(authors)-5}名)")
        lines.append(f"   著者: {', '.join(author_names)}")

    # 年・ジャーナル
    year = paper.get("year")
    venue = paper.get("venue") or paper.get("publicationVenue", {})
    if isinstance(venue, dict):
        venue = venue.get("name", "")
    info_parts = []
    if year:
        info_parts.append(str(year))
    if venue:
        info_parts.append(venue)
    if info_parts:
        lines.append(f"   掲載: {' | '.join(info_parts)}")

    # 引用数
    citation_count = paper.get("citationCount")
    influential_count = paper.get("influentialCitationCount")
    if citation_count is not None:
        cite_str = f"   被引用数: {citation_count}"
        if influential_count:
            cite_str += f" (influential: {influential_count})"
        lines.append(cite_str)

    # 外部ID
    ext_ids = paper.get("externalIds") or {}
    id_parts = []
    if ext_ids.get("DOI"):
        id_parts.append(f"DOI: {ext_ids['DOI']}")
    if ext_ids.get("PubMed"):
        id_parts.append(f"PMID: {ext_ids['PubMed']}")
    if ext_ids.get("ArXiv"):
        id_parts.append(f"arXiv: {ext_ids['ArXiv']}")
    if id_parts:
        lines.append(f"   ID: {' | '.join(id_parts)}")

    # TLDR
    tldr = paper.get("tldr")
    if tldr and isinstance(tldr, dict):
        lines.append(f"   TLDR: {tldr.get('text', '')}")

    # Abstract
    if include_abstract:
        abstract = paper.get("abstract")
        if abstract:
            lines.append(f"   Abstract: {abstract[:500]}{'...' if len(abstract) > 500 else ''}")

    # URL
    url = paper.get("url")
    if url:
        lines.append(f"   URL: {url}")

    # S2 Paper ID
    if paper_id:
        lines.append(f"   S2 ID: {paper_id}")

    return "\n".join(lines)


# ============================================================
# ツール定義
# ============================================================

PAPER_FIELDS = "paperId,title,authors,year,venue,publicationVenue,citationCount,influentialCitationCount,externalIds,tldr,url,abstract"
PAPER_FIELDS_SHORT = "paperId,title,authors,year,venue,citationCount,influentialCitationCount,externalIds,tldr,url"


@mcp.tool()
async def search_papers(
    query: str,
    max_results: int = 10,
    year_from: str = "",
    year_to: str = "",
    fields_of_study: str = "",
    open_access_only: bool = False,
) -> str:
    """
    Semantic Scholarでキーワード検索を行います。
    PubMedでカバーしにくいML/統計手法の原著論文や、分野横断的な検索に有用です。
    TLDR（AI要約）付きで結果を返します。

    Args:
        query: 検索クエリ（例: "pancreatic fistula prediction machine learning"）
        max_results: 最大取得件数（デフォルト10、最大100）
        year_from: 開始年（例: "2020"）省略可
        year_to: 終了年（例: "2024"）省略可
        fields_of_study: 分野フィルタ（例: "Medicine", "Computer Science"）省略可
        open_access_only: オープンアクセス論文のみに絞る場合True
    """
    params = {
        "query": query,
        "limit": min(max_results, 100),
        "fields": PAPER_FIELDS_SHORT,
    }

    # 年範囲
    if year_from or year_to:
        year_range = f"{year_from}-{year_to}" if year_from and year_to else (
            f"{year_from}-" if year_from else f"-{year_to}"
        )
        params["year"] = year_range

    if fields_of_study:
        params["fieldsOfStudy"] = fields_of_study

    if open_access_only:
        params["openAccessPdf"] = ""

    data = await _get_json(f"{BASE_URL}/paper/search", params)

    if "error" in data:
        return f"エラー: {data['error']}"

    total = data.get("total", 0)
    papers = data.get("data", [])

    if not papers:
        return f"検索結果: 0件（クエリ: {query}）"

    results = [f"検索結果: {total}件中 {len(papers)}件表示（クエリ: {query}）\n"]
    for i, paper in enumerate(papers, 1):
        results.append(f"--- [{i}] ---")
        results.append(_format_paper(paper))
        results.append("")

    return "\n".join(results)


@mcp.tool()
async def get_paper_detail(
    paper_id: str,
) -> str:
    """
    論文の詳細情報を取得します（Abstract含む）。
    Semantic Scholar ID、DOI、PMID、arXiv IDのいずれかで指定できます。

    Args:
        paper_id: 論文ID。以下の形式に対応:
            - Semantic Scholar ID（例: "649def34f8be52c8b66281af98ae884c09aef38b"）
            - DOI（例: "DOI:10.1038/s41586-020-2649-2"）
            - PMID（例: "PMID:35486828"）
            - arXiv ID（例: "ARXIV:2106.15928"）
    """
    params = {"fields": PAPER_FIELDS}
    data = await _get_json(f"{BASE_URL}/paper/{paper_id}", params)

    if "error" in data:
        return f"エラー: {data['error']}"

    return _format_paper(data, include_abstract=True)


@mcp.tool()
async def get_citations(
    paper_id: str,
    max_results: int = 20,
) -> str:
    """
    指定した論文を引用している論文（被引用論文）を取得します。
    ある重要論文からの研究発展を追跡するのに有用です。

    Args:
        paper_id: 論文ID（S2 ID, DOI:xxx, PMID:xxx, ARXIV:xxx）
        max_results: 最大取得件数（デフォルト20、最大1000）
    """
    params = {
        "fields": PAPER_FIELDS_SHORT,
        "limit": min(max_results, 1000),
    }
    data = await _get_json(f"{BASE_URL}/paper/{paper_id}/citations", params)

    if "error" in data:
        return f"エラー: {data['error']}"

    citations = data.get("data", [])
    if not citations:
        return "被引用論文: 0件"

    results = [f"被引用論文: {len(citations)}件\n"]
    for i, item in enumerate(citations, 1):
        citing_paper = item.get("citingPaper", {})
        results.append(f"--- [{i}] ---")
        results.append(_format_paper(citing_paper))
        results.append("")

    return "\n".join(results)


@mcp.tool()
async def get_references(
    paper_id: str,
    max_results: int = 20,
) -> str:
    """
    指定した論文が引用している論文（参考文献）を取得します。
    論文の理論的基盤や関連研究を把握するのに有用です。

    Args:
        paper_id: 論文ID（S2 ID, DOI:xxx, PMID:xxx, ARXIV:xxx）
        max_results: 最大取得件数（デフォルト20、最大1000）
    """
    params = {
        "fields": PAPER_FIELDS_SHORT,
        "limit": min(max_results, 1000),
    }
    data = await _get_json(f"{BASE_URL}/paper/{paper_id}/references", params)

    if "error" in data:
        return f"エラー: {data['error']}"

    references = data.get("data", [])
    if not references:
        return "参考文献: 0件"

    results = [f"参考文献: {len(references)}件\n"]
    for i, item in enumerate(references, 1):
        cited_paper = item.get("citedPaper", {})
        results.append(f"--- [{i}] ---")
        results.append(_format_paper(cited_paper))
        results.append("")

    return "\n".join(results)


@mcp.tool()
async def search_author(
    query: str,
    max_results: int = 5,
) -> str:
    """
    著者名でSemantic Scholarの著者を検索します。
    著者ID、所属、論文数、被引用数、h-indexなどを取得できます。

    Args:
        query: 著者名（例: "Callery MP", "Fujii T"）
        max_results: 最大取得件数（デフォルト5）
    """
    params = {
        "query": query,
        "limit": min(max_results, 20),
        "fields": "authorId,name,affiliations,paperCount,citationCount,hIndex,url",
    }
    data = await _get_json(f"{BASE_URL}/author/search", params)

    if "error" in data:
        return f"エラー: {data['error']}"

    authors = data.get("data", [])
    if not authors:
        return f"著者検索結果: 0件（クエリ: {query}）"

    results = [f"著者検索結果: {len(authors)}件\n"]
    for i, author in enumerate(authors, 1):
        lines = [f"--- [{i}] ---"]
        lines.append(f"👤 {author.get('name', 'N/A')}")
        lines.append(f"   Author ID: {author.get('authorId', 'N/A')}")

        affiliations = author.get("affiliations")
        if affiliations:
            lines.append(f"   所属: {', '.join(affiliations)}")

        paper_count = author.get("paperCount", 0)
        citation_count = author.get("citationCount", 0)
        h_index = author.get("hIndex", 0)
        lines.append(f"   論文数: {paper_count} | 被引用数: {citation_count} | h-index: {h_index}")

        url = author.get("url")
        if url:
            lines.append(f"   URL: {url}")

        results.append("\n".join(lines))
        results.append("")

    return "\n".join(results)


@mcp.tool()
async def get_author_papers(
    author_id: str,
    max_results: int = 20,
) -> str:
    """
    著者IDを指定して、その著者の論文リストを取得します。
    search_authorで取得したauthor_idを使用します。

    Args:
        author_id: Semantic ScholarのAuthor ID（例: "1741101"）
        max_results: 最大取得件数（デフォルト20、最大1000）
    """
    params = {
        "fields": PAPER_FIELDS_SHORT,
        "limit": min(max_results, 1000),
    }
    data = await _get_json(f"{BASE_URL}/author/{author_id}/papers", params)

    if "error" in data:
        return f"エラー: {data['error']}"

    papers = data.get("data", [])
    if not papers:
        return "論文: 0件"

    results = [f"著者の論文: {len(papers)}件\n"]
    for i, paper in enumerate(papers, 1):
        results.append(f"--- [{i}] ---")
        results.append(_format_paper(paper))
        results.append("")

    return "\n".join(results)


@mcp.tool()
async def get_recommended_papers(
    paper_id: str,
    max_results: int = 10,
) -> str:
    """
    指定した論文に基づいて推薦論文を取得します。
    Semantic ScholarのAIが類似・関連論文を推薦します。

    Args:
        paper_id: 基準となる論文ID（S2 ID, DOI:xxx, PMID:xxx, ARXIV:xxx）
        max_results: 最大取得件数（デフォルト10、最大500）
    """
    params = {
        "fields": PAPER_FIELDS_SHORT,
        "limit": min(max_results, 500),
    }
    data = await _get_json(f"{REC_URL}/forpaper/{paper_id}", params)

    if "error" in data:
        return f"エラー: {data['error']}"

    papers = data.get("recommendedPapers", [])
    if not papers:
        return "推薦論文: 0件"

    results = [f"推薦論文: {len(papers)}件\n"]
    for i, paper in enumerate(papers, 1):
        results.append(f"--- [{i}] ---")
        results.append(_format_paper(paper))
        results.append("")

    return "\n".join(results)


@mcp.tool()
async def batch_get_papers(
    paper_ids: list[str],
) -> str:
    """
    複数の論文IDを一括で詳細取得します（最大500件）。
    PMIDやDOIのリストからまとめて情報を取得するのに有用です。

    Args:
        paper_ids: 論文IDのリスト（例: ["PMID:35486828", "DOI:10.1038/xxx"]）
    """
    if len(paper_ids) > 500:
        return "エラー: 一度に取得できるのは最大500件です"

    json_body = {"ids": paper_ids}
    params = {"fields": PAPER_FIELDS}

    data = await _post_json(f"{BASE_URL}/paper/batch", json_body, params)

    if isinstance(data, dict) and "error" in data:
        return f"エラー: {data['error']}"

    if not isinstance(data, list):
        return f"予期しないレスポンス形式: {str(data)[:300]}"

    results = [f"取得結果: {len(data)}件\n"]
    for i, paper in enumerate(data, 1):
        if paper is None:
            results.append(f"--- [{i}] ---\n（論文が見つかりません: {paper_ids[i-1] if i-1 < len(paper_ids) else 'N/A'}）\n")
            continue
        results.append(f"--- [{i}] ---")
        results.append(_format_paper(paper, include_abstract=True))
        results.append("")

    return "\n".join(results)


@mcp.tool()
async def search_papers_by_relevance(
    positive_paper_ids: list[str],
    negative_paper_ids: list[str] = [],
    max_results: int = 10,
) -> str:
    """
    複数の論文を「ポジティブ例」「ネガティブ例」として指定し、
    それらに基づいた推薦論文を取得します。
    系統的レビューの関連論文探索に特に有用です。

    Args:
        positive_paper_ids: 関連する論文のIDリスト（必須、1-5件）
        negative_paper_ids: 関連しない論文のIDリスト（省略可、0-5件）
        max_results: 最大取得件数（デフォルト10、最大500）
    """
    json_body = {
        "positivePaperIds": positive_paper_ids,
    }
    if negative_paper_ids:
        json_body["negativePaperIds"] = negative_paper_ids

    params = {
        "fields": PAPER_FIELDS_SHORT,
        "limit": min(max_results, 500),
    }

    data = await _post_json(REC_URL, json_body, params)

    if isinstance(data, dict) and "error" in data:
        return f"エラー: {data['error']}"

    papers = data.get("recommendedPapers", [])
    if not papers:
        return "推薦論文: 0件"

    results = [f"推薦論文（複数論文ベース）: {len(papers)}件\n"]
    for i, paper in enumerate(papers, 1):
        results.append(f"--- [{i}] ---")
        results.append(_format_paper(paper))
        results.append("")

    return "\n".join(results)


if __name__ == "__main__":
    mcp.run()
