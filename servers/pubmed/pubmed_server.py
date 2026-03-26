from mcp.server.fastmcp import FastMCP
import httpx
import os
import xml.etree.ElementTree as ET
from datetime import datetime

mcp = FastMCP("PubMed")

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PMC_OA_BASE = "https://www.ncbi.nlm.nih.gov/pmc/utils"
API_KEY = os.environ.get("NCBI_API_KEY", "")


def _base_params() -> dict:
    """APIキーを含む共通パラメータ"""
    params = {}
    if API_KEY:
        params["api_key"] = API_KEY
    return params


async def _get_json(url: str, params: dict) -> dict:
    """NCBI APIへのGETリクエスト（JSON）"""
    params.update(_base_params())
    params["retmode"] = "json"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            return {"error": f"API Error: {resp.status_code} - {resp.text[:300]}"}
        try:
            return resp.json()
        except Exception:
            return {"error": f"JSON parse error: {resp.text[:300]}"}


async def _get_xml(url: str, params: dict) -> str:
    """NCBI APIへのGETリクエスト（XML文字列を返す）"""
    params.update(_base_params())
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            return f"<error>API Error: {resp.status_code}</error>"
        return resp.text


async def _get_text(url: str, params: dict) -> str:
    """NCBI APIへのGETリクエスト（プレーンテキスト）"""
    params.update(_base_params())
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            return f"ERROR: {resp.status_code}"
        return resp.text


def _parse_article_xml(article_elem) -> dict:
    """PubmedArticle XML要素からメタデータを抽出"""
    info = {}

    # PMID
    pmid_elem = article_elem.find(".//PMID")
    info["pmid"] = pmid_elem.text if pmid_elem is not None else "N/A"

    # タイトル
    title_elem = article_elem.find(".//ArticleTitle")
    info["title"] = "".join(title_elem.itertext()) if title_elem is not None else "N/A"

    # Abstract
    abstract_parts = article_elem.findall(".//Abstract/AbstractText")
    if abstract_parts:
        abs_texts = []
        for part in abstract_parts:
            label = part.get("Label", "")
            text = "".join(part.itertext()) or ""
            if label:
                abs_texts.append(f"[{label}] {text}")
            else:
                abs_texts.append(text)
        info["abstract"] = " ".join(abs_texts)
    else:
        info["abstract"] = ""

    # 著者
    authors = []
    for author in article_elem.findall(".//Author"):
        last = author.findtext("LastName", "")
        fore = author.findtext("ForeName", "")
        if last:
            authors.append(f"{last} {fore}".strip())
    info["authors"] = authors

    # ジャーナル
    journal_elem = article_elem.find(".//Journal/Title")
    info["journal"] = journal_elem.text if journal_elem is not None else "N/A"

    journal_abbrev = article_elem.find(".//Journal/ISOAbbreviation")
    info["journal_abbrev"] = journal_abbrev.text if journal_abbrev is not None else ""

    # 出版日
    pub_date = article_elem.find(".//PubDate")
    if pub_date is not None:
        year = pub_date.findtext("Year", "")
        month = pub_date.findtext("Month", "")
        day = pub_date.findtext("Day", "")
        medline_date = pub_date.findtext("MedlineDate", "")
        if year:
            info["pubdate"] = f"{year} {month} {day}".strip()
        elif medline_date:
            info["pubdate"] = medline_date
        else:
            info["pubdate"] = "N/A"
    else:
        info["pubdate"] = "N/A"

    # DOI
    doi_elem = article_elem.find(".//ArticleId[@IdType='doi']")
    if doi_elem is None:
        doi_elem = article_elem.find(".//ELocationID[@EIdType='doi']")
    info["doi"] = doi_elem.text if doi_elem is not None else ""

    # PMC ID
    pmc_elem = article_elem.find(".//ArticleId[@IdType='pmc']")
    info["pmc"] = pmc_elem.text if pmc_elem is not None else ""

    # Publication Type
    pub_types = []
    for pt in article_elem.findall(".//PublicationType"):
        if pt.text:
            pub_types.append(pt.text)
    info["publication_types"] = pub_types

    # MeSH Terms
    mesh_terms = []
    for mesh in article_elem.findall(".//MeshHeading/DescriptorName"):
        if mesh.text:
            mesh_terms.append(mesh.text)
    info["mesh_terms"] = mesh_terms

    # Keywords
    keywords = []
    for kw in article_elem.findall(".//Keyword"):
        if kw.text:
            keywords.append(kw.text)
    info["keywords"] = keywords

    return info


def _format_article_short(art: dict) -> str:
    """論文情報を短い形式でフォーマット"""
    authors = art.get("authors", [])
    if len(authors) > 3:
        author_str = ", ".join(authors[:3]) + " et al."
    elif authors:
        author_str = ", ".join(authors)
    else:
        author_str = "著者不明"

    line = f"PMID: {art['pmid']} | {art['pubdate']}\n"
    line += f"  {art['title']}\n"
    line += f"  {author_str}\n"
    line += f"  {art.get('journal', 'N/A')}"
    if art.get("doi"):
        line += f"\n  DOI: {art['doi']}"
    return line


def _format_article_detail(art: dict) -> str:
    """論文情報を詳細形式でフォーマット"""
    authors = art.get("authors", [])
    if len(authors) > 5:
        author_str = ", ".join(authors[:5]) + f" et al. (全{len(authors)}名)"
    elif authors:
        author_str = ", ".join(authors)
    else:
        author_str = "著者不明"

    lines = [
        f"PMID: {art['pmid']}",
        f"タイトル: {art['title']}",
        f"著者: {author_str}",
        f"ジャーナル: {art.get('journal', 'N/A')}",
        f"出版日: {art['pubdate']}",
    ]
    if art.get("doi"):
        lines.append(f"DOI: {art['doi']}")
    if art.get("pmc"):
        lines.append(f"PMC: {art['pmc']}")
    if art.get("publication_types"):
        lines.append(f"論文種別: {', '.join(art['publication_types'])}")
    if art.get("abstract"):
        lines.append(f"抄録: {art['abstract'][:500]}")
    if art.get("mesh_terms"):
        lines.append(f"MeSH: {', '.join(art['mesh_terms'][:15])}")
    if art.get("keywords"):
        lines.append(f"キーワード: {', '.join(art['keywords'][:10])}")

    return "\n".join(lines)


# ============================================================
# 標準機能 (Anthropic PubMed MCP相当)
# ============================================================

async def _search_articles_data(
    query: str,
    max_results: int = 20,
    date_from: str = "",
    date_to: str = "",
    sort: str = "relevance",
    count_only: bool = False
) -> dict | str:
    """
    データ取得用内部関数
    Returns:
        dict: {"count": str, "id_list": list[str], "articles": list[dict]}
        str: error message
    """
    sort_map = {
        "relevance": "relevance",
        "pub_date": "pub+date",
        "author": "first+author",
    }

    if count_only:
        # 件数確認モード: retmax=0 でヒット数だけ取得（高速）
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": "0",
            "sort": sort_map.get(sort, "relevance"),
            "usehistory": "n",
        }
        if date_from:
            search_params["mindate"] = date_from
            search_params["datetype"] = "pdat"
        if date_to:
            search_params["maxdate"] = date_to
            if "datetype" not in search_params:
                search_params["datetype"] = "pdat"

        search_data = await _get_json(f"{NCBI_BASE}/esearch.fcgi", search_params)
        if "error" in search_data:
            return f"検索エラー: {search_data['error']}"

        result = search_data.get("esearchresult", {})
        total_count = result.get("count", "0")
        # 翻訳された検索式も取得
        query_translation = result.get("querytranslation", query)
        return {"count": total_count, "id_list": [], "articles": [], "query_translation": query_translation}

    # --- 全件取得モード（ページネーション対応）---
    PAGE_SIZE = 500  # 1回あたりの取得件数（APIキーあり時の推奨値）
    all_ids = []
    total_count = "0"
    retstart = 0
    effective_max = max_results

    while True:
        batch_size = min(PAGE_SIZE, effective_max - len(all_ids))
        if batch_size <= 0:
            break

        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": str(batch_size),
            "retstart": str(retstart),
            "sort": sort_map.get(sort, "relevance"),
            "usehistory": "n",
        }
        if date_from:
            search_params["mindate"] = date_from
            search_params["datetype"] = "pdat"
        if date_to:
            search_params["maxdate"] = date_to
            if "datetype" not in search_params:
                search_params["datetype"] = "pdat"

        search_data = await _get_json(f"{NCBI_BASE}/esearch.fcgi", search_params)
        if "error" in search_data:
            return f"検索エラー: {search_data['error']}"

        result = search_data.get("esearchresult", {})
        total_count = result.get("count", "0")
        id_list = result.get("idlist", [])

        if not id_list:
            break

        all_ids.extend(id_list)
        retstart += len(id_list)

        # 全件取得完了チェック
        if len(id_list) < batch_size or len(all_ids) >= int(total_count):
            break
        if len(all_ids) >= effective_max:
            break

    if not all_ids:
        return {"count": total_count, "id_list": [], "articles": []}

    # Step 2: efetch でメタデータ取得（200件ずつバッチ処理）
    FETCH_BATCH = 200
    all_articles = []
    for i in range(0, len(all_ids), FETCH_BATCH):
        batch_ids = all_ids[i:i + FETCH_BATCH]
        articles = await _get_article_metadata_data(batch_ids)
        if isinstance(articles, str):
            return articles  # Error message
        all_articles.extend(articles)

    return {"count": total_count, "id_list": all_ids, "articles": all_articles}


@mcp.tool()
async def search_articles(
    query: str,
    max_results: int = 20,
    date_from: str = "",
    date_to: str = "",
    sort: str = "relevance",
    count_only: bool = False
) -> str:
    """
    PubMedで論文を検索します。

    【推奨ワークフロー】
    網羅的検索が必要な場合は、まず count_only=True で総ヒット数を確認し、
    ユーザーに以下の選択肢を提示してください：
      (A) 全件取得する（max_results を総ヒット数に設定して再検索）
      (B) 条件を追加して絞り込む
      (C) 上位N件だけ取得する

    Args:
        query: 検索クエリ（PubMed構文対応）。例: "pancreatic cancer AND machine learning"
        max_results: 最大取得件数（デフォルト20）。ページネーション対応のため数千件でも取得可能。
        date_from: 開始日（例: "2023/01/01" or "2023"）
        date_to: 終了日（例: "2024/12/31" or "2024"）
        sort: ソート順 - "relevance"(関連度), "pub_date"(出版日), "author"(著者)
        count_only: Trueの場合、ヒット件数と検索式のみ返す（高速）。論文データは取得しない。
    """
    data = await _search_articles_data(query, max_results, date_from, date_to, sort, count_only)

    if isinstance(data, str):
        return data

    total_count = data["count"]

    # --- count_only モード ---
    if count_only:
        qt = data.get("query_translation", query)
        result = f"PubMed検索結果: 全{total_count}件ヒット\n"
        result += f"検索式: {query}\n"
        if qt != query:
            result += f"PubMed翻訳検索式: {qt}\n"
        if date_from or date_to:
            result += f"期間: {date_from or '---'} 〜 {date_to or '---'}\n"
        result += "\n"
        result += "【次のステップ】\n"
        result += f"  (A) 全{total_count}件を取得する → search_articles(query=..., max_results={total_count})\n"
        result += f"  (B) 条件を追加して絞り込む → 検索式を修正して再度 count_only=True\n"
        result += f"  (C) 上位N件だけ取得する → search_articles(query=..., max_results=N)\n"
        return result

    # --- 通常モード（メタデータ付き）---
    articles = data["articles"]
    id_list = data.get("id_list", [])

    if not articles:
        return f"「{query}」に一致する論文が見つかりませんでした。"

    header = f"PubMed検索結果: {len(articles)}件取得 / 全{total_count}件ヒット\n"
    header += f"検索: {query}\n"
    if date_from or date_to:
        header += f"期間: {date_from or '---'} 〜 {date_to or '---'}\n"
    if len(articles) < int(total_count):
        remaining = int(total_count) - len(articles)
        header += f"※ 未取得: {remaining}件（max_resultsを増やすと追加取得可能）\n"
    header += "=" * 60 + "\n\n"

    entries = [_format_article_short(a) for a in articles]
    return header + "\n\n".join(entries)


async def _get_article_metadata_data(pmids: list[str]) -> list[dict] | str:
    """
    データ取得用内部関数
    """
    if not pmids:
        return []

    fetch_xml = await _get_xml(f"{NCBI_BASE}/efetch.fcgi", {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "xml",
    })

    if fetch_xml.startswith("<error>"):
        return f"取得エラー: {fetch_xml}"

    try:
        root = ET.fromstring(fetch_xml)
    except ET.ParseError:
        return "XMLパースエラーが発生しました。"

    articles = []
    for art_elem in root.findall(".//PubmedArticle"):
        articles.append(_parse_article_xml(art_elem))

    return articles


@mcp.tool()
async def get_article_metadata(pmids: list[str]) -> str:
    """
    PubMed IDを指定して論文の詳細メタデータを取得します。

    Args:
        pmids: PMIDのリスト（例: ["35486828", "33264437"]）
    """
    if not pmids:
        return "PMIDを指定してください。"

    articles = await _get_article_metadata_data(pmids)
    
    if isinstance(articles, str):
        return articles

    if not articles:
        return "指定されたPMIDの論文が見つかりませんでした。"

    entries = [_format_article_detail(a) for a in articles]
    return "\n\n" + ("=" * 60 + "\n\n").join(entries)


async def _get_full_text_article_data(pmc_ids: list[str]) -> list[dict] | str:
    """
    データ取得用内部関数
    Returns:
        list[dict]: [{"id": str, "title": str, "body": str, "error": str}, ...]
    """
    results_data = []

    for pmc_id in pmc_ids:
        # PMCプレフィックスを正規化
        clean_id = pmc_id.replace("PMC", "").strip()
        pmc_str = f"PMC{clean_id}"
        
        entry = {"id": pmc_str, "title": "", "body": "", "error": ""}

        # PMC OA APIで全文取得を試行
        xml_text = await _get_xml(
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            {"db": "pmc", "id": clean_id, "rettype": "xml"}
        )

        if "<error>" in xml_text.lower() or "API Error" in xml_text:
            entry["error"] = "全文を取得できませんでした。PMCに収録されていない可能性があります。"
            results_data.append(entry)
            continue

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            entry["error"] = "XMLパースエラー"
            results_data.append(entry)
            continue

        # タイトル
        title_elem = root.find(".//article-title")
        title = "".join(title_elem.itertext()) if title_elem is not None else "N/A"
        entry["title"] = title

        # 本文を抽出
        body_parts = []
        for sec in root.findall(".//body//sec"):
            sec_title = sec.find("title")
            if sec_title is not None and sec_title.text:
                body_parts.append(f"\n## {sec_title.text}\n")
            for p in sec.findall("p"):
                text = "".join(p.itertext()).strip()
                if text:
                    body_parts.append(text)

        if not body_parts:
            # bodyがない場合、abstractだけでも取得
            for abstract in root.findall(".//abstract//p"):
                text = "".join(abstract.itertext()).strip()
                if text:
                    body_parts.append(text)

        if body_parts:
            full_text = "\n\n".join(body_parts)
            entry["body"] = full_text
        else:
            entry["error"] = "本文テキストを抽出できませんでした。"
        
        results_data.append(entry)

    return results_data


@mcp.tool()
async def get_full_text_article(pmc_ids: list[str]) -> str:
    """
    PubMed Central (PMC) から全文テキストを取得します。

    Args:
        pmc_ids: PMC IDのリスト（例: ["PMC9046468"]）。"PMC"プレフィックスは有無どちらでも可。
    """
    data_list = await _get_full_text_article_data(pmc_ids)
    
    if isinstance(data_list, str):
        return data_list
        
    results = []
    for entry in data_list:
        pmc_str = entry["id"]
        title = entry["title"]
        body = entry["body"]
        error = entry["error"]
        
        if error:
            results.append(f"=== {pmc_str} ===\n{error}")
            continue
            
        # 長すぎる場合は切り詰め (表示用のみ)
        if len(body) > 15000:
            body = body[:15000] + "\n\n... [テキスト切り詰め: 全文はPMCサイトで確認してください]"
            
        results.append(f"=== {pmc_str}: {title} ===\n\n{body}")

    return "\n\n".join(results) if results else "指定されたPMC IDの全文が見つかりませんでした。"


@mcp.tool()
async def find_related_articles(
    pmids: list[str],
    max_results: int = 10,
    link_type: str = "pubmed_pubmed"
) -> str:
    """
    PubMedで関連論文を検索します。

    Args:
        pmids: 元論文のPMIDリスト（例: ["35486828"]）
        max_results: 最大取得件数（デフォルト10）
        link_type: リンクタイプ
            - "pubmed_pubmed": 類似論文（デフォルト）
            - "pubmed_pmc": PMC全文版
    """
    link_data = await _get_json(f"{NCBI_BASE}/elink.fcgi", {
        "dbfrom": "pubmed",
        "db": "pubmed" if link_type == "pubmed_pubmed" else "pmc",
        "id": ",".join(pmids),
        "linkname": link_type,
        "cmd": "neighbor_score",
    })

    if "error" in link_data:
        return f"エラー: {link_data['error']}"

    linksets = link_data.get("linksets", [])
    related_ids = []

    for ls in linksets:
        for linksetdb in ls.get("linksetdbs", []):
            for link in linksetdb.get("links", []):
                # eLink JSON returns links as strings, not dicts
                lid = str(link) if not isinstance(link, dict) else str(link.get("id", ""))
                if lid and lid not in related_ids:
                    related_ids.append(lid)

    if not related_ids:
        return f"PMID {', '.join(pmids)} の関連論文が見つかりませんでした。"

    related_ids = related_ids[:max_results]

    if link_type == "pubmed_pmc":
        return f"PMC全文あり: {', '.join(['PMC' + rid for rid in related_ids])}"

    # 関連論文のメタデータを取得
    fetch_xml = await _get_xml(f"{NCBI_BASE}/efetch.fcgi", {
        "db": "pubmed",
        "id": ",".join(related_ids),
        "rettype": "xml",
    })

    try:
        root = ET.fromstring(fetch_xml)
    except ET.ParseError:
        return f"関連PMID: {', '.join(related_ids)}\n（メタデータ取得に失敗）"

    articles = []
    for art_elem in root.findall(".//PubmedArticle"):
        articles.append(_parse_article_xml(art_elem))

    header = f"PMID {', '.join(pmids)} の関連論文: {len(articles)}件\n"
    header += "=" * 60 + "\n\n"

    entries = [_format_article_short(a) for a in articles]
    return header + "\n\n".join(entries)


@mcp.tool()
async def convert_article_ids(
    ids: list[str],
    id_type: str = "pmid"
) -> str:
    """
    PMID, PMCID, DOI間のID変換を行います。

    Args:
        ids: 変換元IDのリスト（例: ["35486828"] or ["PMC9046468"] or ["10.1038/s41586-020-2012-7"]）
        id_type: 入力IDの種類 - "pmid", "pmcid", "doi"
    """
    id_type_map = {"pmid": "pmid", "pmcid": "pmcid", "doi": "doi"}
    itype = id_type_map.get(id_type, "pmid")

    params = {
        "ids": ",".join(ids),
        "idtype": itype,
        "format": "json",
        "tool": "pubmed_mcp",
        "email": "mcp@example.com",
    }
    if API_KEY:
        params["api_key"] = API_KEY

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            params=params
        )
        if resp.status_code != 200:
            return f"ID変換エラー: HTTP {resp.status_code}"
        try:
            data = resp.json()
        except Exception:
            return f"JSON解析エラー: {resp.text[:200]}"

    records = data.get("records", [])
    if not records:
        return "ID変換結果が得られませんでした。"

    results = []
    for rec in records:
        line = f"入力: {rec.get('requested-id', 'N/A')}\n"
        if rec.get("pmid"):
            line += f"  PMID: {rec['pmid']}\n"
        if rec.get("pmcid"):
            line += f"  PMCID: {rec['pmcid']}\n"
        if rec.get("doi"):
            line += f"  DOI: {rec['doi']}"
        if rec.get("errmsg"):
            line += f"  エラー: {rec['errmsg']}"
        results.append(line)

    return "\n\n".join(results)


@mcp.tool()
async def lookup_article_by_citation(
    journal: str = "",
    year: str = "",
    volume: str = "",
    first_page: str = "",
    author: str = ""
) -> str:
    """
    引用情報からPubMed論文を特定します。

    Args:
        journal: ジャーナル名または略称（例: "Nature", "Lancet"）
        year: 出版年（例: "2020"）
        volume: 巻（例: "580"）
        first_page: 最初のページ番号（例: "123"）
        author: 第一著者の姓（例: "Smith"）
    """
    # esearchで引用情報を検索クエリに変換
    query_parts = []
    if journal:
        query_parts.append(f"{journal}[journal]")
    if year:
        query_parts.append(f"{year}[pdat]")
    if volume:
        query_parts.append(f"{volume}[volume]")
    if first_page:
        query_parts.append(f"{first_page}[page]")
    if author:
        query_parts.append(f"{author}[1au]")

    if not query_parts:
        return "検索条件を少なくとも1つ指定してください。"

    query = " AND ".join(query_parts)

    search_data = await _get_json(f"{NCBI_BASE}/esearch.fcgi", {
        "db": "pubmed",
        "term": query,
        "retmax": "5",
    })

    if "error" in search_data:
        return f"検索エラー: {search_data['error']}"

    result = search_data.get("esearchresult", {})
    total = result.get("count", "0")
    id_list = result.get("idlist", [])

    if not id_list:
        return f"引用情報に一致する論文が見つかりませんでした。\n検索式: {query}"

    # メタデータを取得
    metadata = await get_article_metadata(id_list)

    header = f"引用検索結果: {total}件ヒット\n"
    header += f"検索式: {query}\n\n"
    return header + metadata


# ============================================================
# 追加機能 (おすすめ)
# ============================================================

@mcp.tool()
async def search_mesh_terms(term: str, max_results: int = 10) -> str:
    """
    MeSH（Medical Subject Headings）用語を検索します。
    系統的レビューや正確な検索式の構築に有用です。

    Args:
        term: 検索する用語（例: "pancreatic fistula", "machine learning"）
        max_results: 最大取得件数（デフォルト10）
    """
    # Step 1: MeSHデータベースで検索
    search_data = await _get_json(f"{NCBI_BASE}/esearch.fcgi", {
        "db": "mesh",
        "term": term,
        "retmax": str(max_results),
    })

    if "error" in search_data:
        return f"検索エラー: {search_data['error']}"

    id_list = search_data.get("esearchresult", {}).get("idlist", [])
    total = search_data.get("esearchresult", {}).get("count", "0")

    if not id_list:
        return f"MeSHで「{term}」に一致する用語が見つかりませんでした。"

    # Step 2: esummary でMeSH詳細を取得
    summary_data = await _get_json(f"{NCBI_BASE}/esummary.fcgi", {
        "db": "mesh",
        "id": ",".join(id_list),
    })

    if "error" in summary_data:
        return f"詳細取得エラー: {summary_data['error']}"

    result = summary_data.get("result", {})
    uids = result.get("uids", [])

    results = []
    for uid in uids:
        entry = result.get(uid, {})
        if not entry:
            continue

        mesh_id = entry.get("ds_meshui", "N/A")
        mesh_name = entry.get("ds_meshterms", "N/A")
        scope_note = entry.get("ds_scopenote", "")

        line = f"【{mesh_name}】(MeSH ID: {mesh_id})\n"
        if scope_note:
            line += f"  定義: {scope_note[:300]}"

        results.append(line)

    header = f"MeSH検索結果: {len(results)}件 / 全{total}件\n"
    header += f"検索: {term}\n"
    header += "=" * 60 + "\n\n"

    return header + "\n\n".join(results) if results else f"MeSHで「{term}」の詳細情報を取得できませんでした。"


@mcp.tool()
async def get_cited_by(pmids: list[str], max_results: int = 20) -> str:
    """
    指定した論文を引用している後続論文（被引用論文）を取得します。
    論文のインパクト調査や研究の発展追跡に有用です。

    Args:
        pmids: 元論文のPMIDリスト（例: ["35486828"]）
        max_results: 最大取得件数（デフォルト20）
    """
    link_data = await _get_json(f"{NCBI_BASE}/elink.fcgi", {
        "dbfrom": "pubmed",
        "db": "pubmed",
        "id": ",".join(pmids),
        "linkname": "pubmed_pubmed_citedin",
    })

    if "error" in link_data:
        return f"エラー: {link_data['error']}"

    linksets = link_data.get("linksets", [])
    citing_ids = []

    for ls in linksets:
        for linksetdb in ls.get("linksetdbs", []):
            if linksetdb.get("linkname") == "pubmed_pubmed_citedin":
                for link in linksetdb.get("links", []):
                    # eLink JSON returns links as strings, not dicts
                    lid = str(link) if not isinstance(link, dict) else str(link.get("id", ""))
                    if lid and lid not in citing_ids:
                        citing_ids.append(lid)

    if not citing_ids:
        return f"PMID {', '.join(pmids)} を引用している論文が見つかりませんでした（PubMed Centralに収録されている論文のみ検索可能）。"

    total_citing = len(citing_ids)
    citing_ids = citing_ids[:max_results]

    # メタデータを取得
    fetch_xml = await _get_xml(f"{NCBI_BASE}/efetch.fcgi", {
        "db": "pubmed",
        "id": ",".join(citing_ids),
        "rettype": "xml",
    })

    try:
        root = ET.fromstring(fetch_xml)
    except ET.ParseError:
        return f"被引用PMID（全{total_citing}件）: {', '.join(citing_ids)}\n（メタデータ取得に失敗）"

    articles = []
    for art_elem in root.findall(".//PubmedArticle"):
        articles.append(_parse_article_xml(art_elem))

    header = f"PMID {', '.join(pmids)} の被引用論文: {len(articles)}件表示 / 全{total_citing}件\n"
    header += "=" * 60 + "\n\n"

    entries = [_format_article_short(a) for a in articles]
    return header + "\n\n".join(entries)


@mcp.tool()
async def get_author_publications(
    author_name: str,
    max_results: int = 20,
    date_from: str = "",
    date_to: str = ""
) -> str:
    """
    特定の著者の論文リストを取得します。

    Args:
        author_name: 著者名（例: "Fujii T", "Smith John"）。"姓 名のイニシャル" 形式推奨。
        max_results: 最大取得件数（デフォルト20）
        date_from: 開始日（例: "2020"）
        date_to: 終了日（例: "2024"）
    """
    query = f"{author_name}[Author]"

    search_params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "sort": "pub+date",
    }
    if date_from:
        search_params["mindate"] = date_from
        search_params["datetype"] = "pdat"
    if date_to:
        search_params["maxdate"] = date_to
        if "datetype" not in search_params:
            search_params["datetype"] = "pdat"

    search_data = await _get_json(f"{NCBI_BASE}/esearch.fcgi", search_params)
    if "error" in search_data:
        return f"検索エラー: {search_data['error']}"

    result = search_data.get("esearchresult", {})
    total = result.get("count", "0")
    id_list = result.get("idlist", [])

    if not id_list:
        return f"著者「{author_name}」の論文が見つかりませんでした。名前の形式を確認してください（例: \"Smith J\" or \"Smith John\"）。"

    fetch_xml = await _get_xml(f"{NCBI_BASE}/efetch.fcgi", {
        "db": "pubmed",
        "id": ",".join(id_list),
        "rettype": "xml",
    })

    try:
        root = ET.fromstring(fetch_xml)
    except ET.ParseError:
        return f"著者「{author_name}」の論文PMID: {', '.join(id_list)}\n（メタデータ取得に失敗）"

    articles = []
    for art_elem in root.findall(".//PubmedArticle"):
        articles.append(_parse_article_xml(art_elem))

    header = f"著者「{author_name}」の論文: {len(articles)}件表示 / 全{total}件\n"
    if date_from or date_to:
        header += f"期間: {date_from or '---'} 〜 {date_to or '---'}\n"
    header += "=" * 60 + "\n\n"

    entries = [_format_article_short(a) for a in articles]
    return header + "\n\n".join(entries)


@mcp.tool()
async def get_publication_trends(
    query: str,
    start_year: int = 2000,
    end_year: int = 0
) -> str:
    """
    特定トピックの年別論文数推移を取得します。
    研究動向の把握や学会発表のイントロに有用です。

    Args:
        query: 検索クエリ（例: "pancreatic cancer AND machine learning"）
        start_year: 開始年（デフォルト2000）
        end_year: 終了年（デフォルト: 現在の年）
    """
    if end_year == 0:
        end_year = datetime.now().year

    yearly_counts = []

    for year in range(start_year, end_year + 1):
        search_data = await _get_json(f"{NCBI_BASE}/esearch.fcgi", {
            "db": "pubmed",
            "term": query,
            "mindate": f"{year}/01/01",
            "maxdate": f"{year}/12/31",
            "datetype": "pdat",
            "retmax": "0",
        })

        if "error" in search_data:
            yearly_counts.append((year, -1))
            continue

        count = int(search_data.get("esearchresult", {}).get("count", "0"))
        yearly_counts.append((year, count))

    # 結果フォーマット
    header = f"論文数推移: {query}\n"
    header += f"期間: {start_year} - {end_year}\n"
    header += "=" * 60 + "\n\n"

    lines = []
    max_count = max((c for _, c in yearly_counts if c >= 0), default=1)

    for year, count in yearly_counts:
        if count < 0:
            lines.append(f"  {year}: エラー")
        else:
            bar_len = int((count / max_count) * 30) if max_count > 0 else 0
            bar = "█" * bar_len
            lines.append(f"  {year}: {bar} {count}件")

    total = sum(c for _, c in yearly_counts if c >= 0)
    footer = f"\n合計: {total}件"

    return header + "\n".join(lines) + footer


# ============================================================
# 追加機能2: Bookshelf / ClinicalTrials / Batch / Export / GeneRIF
# ============================================================

@mcp.tool()
async def search_ncbi_books(
    query: str,
    max_results: int = 10
) -> str:
    """
    NCBI Bookshelf（GeneReviews等）を検索します。
    遺伝性疾患の臨床マネジメント、遺伝カウンセリング情報、
    サーベイランス推奨などの包括的レビューを取得できます。
    エキスパートパネルでの二次的所見の評価に特に有用です。

    Args:
        query: 検索クエリ（例: "BRCA2", "Lynch syndrome", "Li-Fraumeni"）
        max_results: 最大取得件数（デフォルト10）
    """
    # Step 1: esearch で Bookshelf ID を取得
    search_data = await _get_json(f"{NCBI_BASE}/esearch.fcgi", {
        "db": "books",
        "term": query,
        "retmax": str(max_results),
    })

    if "error" in search_data:
        return f"検索エラー: {search_data['error']}"

    result = search_data.get("esearchresult", {})
    total = result.get("count", "0")
    id_list = result.get("idlist", [])

    if not id_list:
        return f"NCBI Bookshelfで「{query}」に一致する文献が見つかりませんでした。"

    # Step 2: esummary で詳細取得
    summary_data = await _get_json(f"{NCBI_BASE}/esummary.fcgi", {
        "db": "books",
        "id": ",".join(id_list),
    })

    if "error" in summary_data:
        return f"詳細取得エラー: {summary_data['error']}"

    result_data = summary_data.get("result", {})
    uids = result_data.get("uids", [])

    entries = []
    for uid in uids:
        entry = result_data.get(uid, {})
        if not entry:
            continue

        title = entry.get("title", "N/A")
        book_title = entry.get("booktitle", "")
        authors_list = entry.get("authors", [])
        authors = ", ".join(
            a.get("name", "") for a in authors_list[:3]
        )
        if len(authors_list) > 3:
            authors += " et al."

        pub_date = entry.get("pubdate", "")
        # RID（章のID）を取得してURLを構築
        rid = entry.get("rid", "")
        chapter_url = f"https://www.ncbi.nlm.nih.gov/books/{rid}/" if rid else ""

        line = f"ID: {uid}"
        if rid:
            line += f" (RID: {rid})"
        line += f"\n  タイトル: {title}"
        if book_title and book_title != title:
            line += f"\n  書籍: {book_title}"
        if authors:
            line += f"\n  著者: {authors}"
        if pub_date:
            line += f"\n  更新日: {pub_date}"
        if chapter_url:
            line += f"\n  URL: {chapter_url}"

        entries.append(line)

    header = f"NCBI Bookshelf検索結果: {len(entries)}件 / 全{total}件\n"
    header += f"検索: {query}\n"
    header += "=" * 60 + "\n\n"

    return header + "\n\n".join(entries) if entries else f"「{query}」の詳細情報を取得できませんでした。"


@mcp.tool()
async def get_abstracts_batch(pmids: list[str]) -> str:
    """
    複数PMIDの抄録を一括取得し、比較しやすい形式で表示します。
    系統的レビューのスクリーニングやメタ解析の論文選定に有用です。

    Args:
        pmids: PMIDのリスト（例: ["35486828", "33264437", "31523456"]）
    """
    if not pmids:
        return "PMIDを指定してください。"

    if len(pmids) > 50:
        return "一度に取得できるのは最大50件です。PMIDを減らしてください。"

    fetch_xml = await _get_xml(f"{NCBI_BASE}/efetch.fcgi", {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "xml",
    })

    if fetch_xml.startswith("<e>"):
        return f"取得エラー: {fetch_xml}"

    try:
        root = ET.fromstring(fetch_xml)
    except ET.ParseError:
        return "XMLパースエラーが発生しました。"

    articles = []
    for art_elem in root.findall(".//PubmedArticle"):
        articles.append(_parse_article_xml(art_elem))

    if not articles:
        return "指定されたPMIDの論文が見つかりませんでした。"

    entries = []
    for i, art in enumerate(articles, 1):
        authors = art.get("authors", [])
        if len(authors) > 3:
            author_str = ", ".join(authors[:3]) + " et al."
        elif authors:
            author_str = ", ".join(authors)
        else:
            author_str = "著者不明"

        entry = f"--- [{i}/{len(articles)}] PMID: {art['pmid']} ---\n"
        entry += f"タイトル: {art['title']}\n"
        entry += f"著者: {author_str}\n"
        entry += f"ジャーナル: {art.get('journal', 'N/A')} ({art['pubdate']})\n"
        if art.get('abstract'):
            entry += f"抄録:\n{art['abstract']}\n"
        else:
            entry += "抄録: なし\n"
        if art.get('keywords'):
            entry += f"キーワード: {', '.join(art['keywords'][:8])}"

        entries.append(entry)

    header = f"抄録一括取得: {len(articles)}件\n"
    header += "=" * 60 + "\n\n"

    return header + "\n\n".join(entries)


@mcp.tool()
async def search_clinical_trials(
    query: str,
    max_results: int = 10,
    status: str = ""
) -> str:
    """
    ClinicalTrials.gov で臨床試験を検索します。
    エキスパートパネルで治験情報の確認（「この変異に対する治験があるか？」）に有用です。

    Args:
        query: 検索クエリ（例: "KRAS G12D pancreatic cancer", "olaparib BRCA2"）
        max_results: 最大取得件数（デフォルト10）
        status: 試験状態でフィルタ。省略時は全て。
            指定可能値: "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING",
            "COMPLETED", "ENROLLING_BY_INVITATION", "SUSPENDED", "TERMINATED", "WITHDRAWN"
    """
    params = {
        "query.term": query,
        "pageSize": str(min(max_results, 20)),
        "format": "json",
    }
    if status:
        params["filter.overallStatus"] = status

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params=params
        )
        if resp.status_code != 200:
            return f"ClinicalTrials.gov APIエラー: HTTP {resp.status_code} - {resp.text[:300]}"
        try:
            data = resp.json()
        except Exception:
            return f"JSON解析エラー: {resp.text[:300]}"

    studies = data.get("studies", [])
    total = data.get("totalCount", 0)

    if not studies:
        return f"「{query}」に一致する臨床試験が見つかりませんでした。"

    entries = []
    for study in studies:
        protocol = study.get("protocolSection", {})
        ident = protocol.get("identificationModule", {})
        status_mod = protocol.get("statusModule", {})
        design = protocol.get("designModule", {})
        desc = protocol.get("descriptionModule", {})
        contacts = protocol.get("contactsLocationsModule", {})
        conditions_mod = protocol.get("conditionsModule", {})
        interventions_mod = protocol.get("armsInterventionsModule", {})

        nct_id = ident.get("nctId", "N/A")
        title = ident.get("briefTitle", ident.get("officialTitle", "N/A"))
        overall_status = status_mod.get("overallStatus", "N/A")
        start_date = status_mod.get("startDateStruct", {}).get("date", "")
        phases = design.get("phases", [])
        phase_str = ", ".join(phases) if phases else "N/A"

        conditions = conditions_mod.get("conditions", [])
        condition_str = ", ".join(conditions[:3]) if conditions else "N/A"

        # 介入（薬剤名など）
        interventions = interventions_mod.get("interventions", [])
        intervention_names = []
        for iv in interventions[:3]:
            iv_name = iv.get("name", "")
            iv_type = iv.get("type", "")
            if iv_name:
                intervention_names.append(f"{iv_name} ({iv_type})" if iv_type else iv_name)
        intervention_str = ", ".join(intervention_names) if intervention_names else "N/A"

        brief_summary = desc.get("briefSummary", "")
        if len(brief_summary) > 300:
            brief_summary = brief_summary[:300] + "..."

        entry = f"NCT ID: {nct_id}\n"
        entry += f"  タイトル: {title}\n"
        entry += f"  状態: {overall_status} | Phase: {phase_str}\n"
        entry += f"  対象疾患: {condition_str}\n"
        entry += f"  介入: {intervention_str}\n"
        if start_date:
            entry += f"  開始日: {start_date}\n"
        entry += f"  URL: https://clinicaltrials.gov/study/{nct_id}"
        if brief_summary:
            entry += f"\n  概要: {brief_summary}"

        entries.append(entry)

    header = f"ClinicalTrials.gov検索結果: {len(entries)}件 / 全{total}件\n"
    header += f"検索: {query}"
    if status:
        header += f" (状態: {status})"
    header += "\n" + "=" * 60 + "\n\n"

    return header + "\n\n".join(entries)


@mcp.tool()
async def export_citations(
    pmids: list[str],
    format: str = "ris"
) -> str:
    """
    論文の書誌情報をRISまたはBibTeX形式でエクスポートします。
    EndNote、Zotero、Mendeleyなどの文献管理ソフトへの取り込みに使用します。

    Args:
        pmids: PMIDのリスト（例: ["35486828", "33264437"]）
        format: 出力形式 - "ris"（EndNote/Zotero用）または "bibtex"（LaTeX用）
    """
    if not pmids:
        return "PMIDを指定してください。"

    # メタデータを取得
    fetch_xml = await _get_xml(f"{NCBI_BASE}/efetch.fcgi", {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "xml",
    })

    try:
        root = ET.fromstring(fetch_xml)
    except ET.ParseError:
        return "XMLパースエラーが発生しました。"

    articles = []
    for art_elem in root.findall(".//PubmedArticle"):
        art = _parse_article_xml(art_elem)

        # 追加情報を取得
        # Volume
        vol_elem = art_elem.find(".//JournalIssue/Volume")
        art["volume"] = vol_elem.text if vol_elem is not None else ""
        # Issue
        issue_elem = art_elem.find(".//JournalIssue/Issue")
        art["issue"] = issue_elem.text if issue_elem is not None else ""
        # Pages
        pages_elem = art_elem.find(".//Pagination/MedlinePgn")
        art["pages"] = pages_elem.text if pages_elem is not None else ""
        # Year
        year_elem = art_elem.find(".//PubDate/Year")
        art["year"] = year_elem.text if year_elem is not None else art.get("pubdate", "")[:4]

        articles.append(art)

    if not articles:
        return "指定されたPMIDの論文が見つかりませんでした。"

    output_lines = []

    if format.lower() == "bibtex":
        for art in articles:
            first_author_last = art["authors"][0].split()[0] if art["authors"] else "Unknown"
            cite_key = f"{first_author_last}{art.get('year', '')}_PMID{art['pmid']}"

            bib = f"@article{{{cite_key},\n"
            bib += f"  title = {{{art['title']}}},\n"
            if art["authors"]:
                bib += f"  author = {{{' and '.join(art['authors'])}}},\n"
            bib += f"  journal = {{{art.get('journal', '')}}},\n"
            if art.get("year"):
                bib += f"  year = {{{art['year']}}},\n"
            if art.get("volume"):
                bib += f"  volume = {{{art['volume']}}},\n"
            if art.get("issue"):
                bib += f"  number = {{{art['issue']}}},\n"
            if art.get("pages"):
                bib += f"  pages = {{{art['pages']}}},\n"
            if art.get("doi"):
                bib += f"  doi = {{{art['doi']}}},\n"
            bib += f"  pmid = {{{art['pmid']}}},\n"
            bib += "}"
            output_lines.append(bib)

        return f"BibTeX形式 ({len(articles)}件):\n\n" + "\n\n".join(output_lines)

    else:  # RIS形式
        for art in articles:
            ris = "TY  - JOUR\n"
            ris += f"TI  - {art['title']}\n"
            for author in art["authors"]:
                ris += f"AU  - {author}\n"
            ris += f"JO  - {art.get('journal', '')}\n"
            if art.get("journal_abbrev"):
                ris += f"JA  - {art['journal_abbrev']}\n"
            if art.get("year"):
                ris += f"PY  - {art['year']}\n"
            if art.get("volume"):
                ris += f"VL  - {art['volume']}\n"
            if art.get("issue"):
                ris += f"IS  - {art['issue']}\n"
            if art.get("pages"):
                ris += f"SP  - {art['pages']}\n"
            if art.get("doi"):
                ris += f"DO  - {art['doi']}\n"
            ris += f"AN  - PMID:{art['pmid']}\n"
            if art.get("abstract"):
                ris += f"AB  - {art['abstract'][:1000]}\n"
            if art.get("keywords"):
                for kw in art["keywords"]:
                    ris += f"KW  - {kw}\n"
            ris += "ER  - "
            output_lines.append(ris)

        return f"RIS形式 ({len(articles)}件):\n\n" + "\n\n".join(output_lines)


@mcp.tool()
async def get_gene_rifs(
    gene_symbol: str,
    max_results: int = 15
) -> str:
    """
    Gene RIF（Reference Into Function）を取得します。
    PubMed論文から抽出された遺伝子機能の簡潔な要約文です。
    エキスパートパネルで見慣れない遺伝子の機能を素早く把握するのに有用です。

    Args:
        gene_symbol: 遺伝子シンボル（例: "BRCA2", "PALB2", "ATM"）
        max_results: 最大取得件数（デフォルト15）
    """
    # Step 1: Gene DBで遺伝子IDを取得
    search_data = await _get_json(f"{NCBI_BASE}/esearch.fcgi", {
        "db": "gene",
        "term": f"{gene_symbol}[Gene Name] AND Homo sapiens[Organism]",
        "retmax": "3",
    })

    if "error" in search_data:
        return f"検索エラー: {search_data['error']}"

    gene_ids = search_data.get("esearchresult", {}).get("idlist", [])

    if not gene_ids:
        return f"遺伝子「{gene_symbol}」がNCBI Geneデータベースで見つかりませんでした。"

    gene_id = gene_ids[0]

    # Step 2: Gene詳細をXMLで取得（GeneRIFを含む）
    gene_xml = await _get_xml(f"{NCBI_BASE}/efetch.fcgi", {
        "db": "gene",
        "id": gene_id,
        "rettype": "xml",
    })

    if "API Error" in gene_xml:
        return f"Gene情報取得エラー: {gene_xml}"

    try:
        root = ET.fromstring(gene_xml)
    except ET.ParseError:
        return "XMLパースエラーが発生しました。"

    # 遺伝子基本情報
    gene_desc = ""
    gene_summary = ""
    official_symbol = gene_symbol
    official_name = ""

    # Entrezgene_gene > Gene-ref
    for desc_elem in root.iter("Gene-ref_desc"):
        official_name = desc_elem.text or ""
        break
    for locus_elem in root.iter("Gene-ref_locus"):
        official_symbol = locus_elem.text or gene_symbol
        break

    # Summary (Entrezgene_summary)
    for summary_elem in root.iter("Entrezgene_summary"):
        gene_summary = summary_elem.text or ""
        break

    # GeneRIFs
    rifs = []
    for generif in root.iter("Gene-commentary"):
        # GeneRIFのタイプは type="254" (generif)
        comm_type = generif.find("Gene-commentary_type")
        if comm_type is not None and comm_type.get("value") == "generif":
            text_elem = generif.find("Gene-commentary_text")
            if text_elem is not None and text_elem.text:
                # PMIDを取得
                pmid = ""
                for ref in generif.findall(".//PubMedId"):
                    if ref.text:
                        pmid = ref.text
                        break
                rifs.append({
                    "text": text_elem.text,
                    "pmid": pmid
                })

    # 結果を組み立て
    header = f"Gene RIF: {official_symbol}"
    if official_name:
        header += f" ({official_name})"
    header += f"\nNCBI Gene ID: {gene_id}\n"
    header += "=" * 60 + "\n"

    if gene_summary:
        header += f"\n【遺伝子概要】\n{gene_summary[:500]}\n"

    if rifs:
        header += f"\n【Gene RIF】 {len(rifs)}件中 {min(len(rifs), max_results)}件表示\n\n"
        for i, rif in enumerate(rifs[:max_results], 1):
            entry = f"{i}. {rif['text']}"
            if rif['pmid']:
                entry += f" (PMID: {rif['pmid']})"
            header += entry + "\n"
    else:
        header += f"\nGene RIFが登録されていません。"

    return header


if __name__ == "__main__":
    mcp.run(transport="stdio")
