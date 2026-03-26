from mcp.server.fastmcp import FastMCP
import httpx
import xml.etree.ElementTree as ET
import asyncio

mcp = FastMCP("ClinVar")

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


async def _esearch_data(query: str, max_results: int = 10) -> dict | str:
    """内部用: esearch実行"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        search_url = f"{NCBI_BASE}/esearch.fcgi"
        search_params = {
            "db": "clinvar",
            "term": query,
            "retmax": max_results,
            "retmode": "json"
        }
        resp = await client.get(search_url, params=search_params)
        if resp.status_code != 200:
            return f"API Error: {resp.status_code}"
        return resp.json()

async def _esummary_data(id_list: list[str]) -> dict | str:
    """内部用: esummary実行"""
    if not id_list:
        return {}
        
    async with httpx.AsyncClient(timeout=30.0) as client:
        summary_url = f"{NCBI_BASE}/esummary.fcgi"
        summary_params = {
            "db": "clinvar",
            "id": ",".join(id_list),
            "retmode": "json"
        }
        resp = await client.get(summary_url, params=summary_params)
        if resp.status_code != 200:
            return f"API Error: {resp.status_code}"
        return resp.json()

@mcp.tool()
async def search_clinvar(query: str, max_results: int = 10) -> str:
    """
    ClinVarでバリアントを検索します。
    遺伝子名、疾患名、バリアント名などで検索できます。

    Args:
        query: 検索クエリ(例: "BRCA1", "breast cancer", "BRCA1[gene] AND pathogenic")
        max_results: 取得する最大件数(デフォルト10)
    """
    search_data = await _esearch_data(query, max_results)
    if isinstance(search_data, str):
        return search_data

    id_list = search_data.get("esearchresult", {}).get("idlist", [])
    total_count = search_data.get("esearchresult", {}).get("count", "0")

    if not id_list:
        return f"「{query}」に一致する結果が見つかりませんでした。"

    summary_data = await _esummary_data(id_list)
    if isinstance(summary_data, str):
        return summary_data

    results = []
    for uid in id_list:
        item = summary_data.get("result", {}).get(uid, {})
        if not item or isinstance(item, list):
            continue

        title = item.get("title", "N/A")

        clinical_sig = "N/A"
        review_status = "N/A"

        clin_sig_obj = item.get("clinical_significance", {})
        if isinstance(clin_sig_obj, dict):
            clinical_sig = clin_sig_obj.get("description", "N/A")
            review_status = clin_sig_obj.get("review_status", "N/A")

        germline = item.get("germline_classification", {})
        if isinstance(germline, dict) and clinical_sig == "N/A":
            clinical_sig = germline.get("description", "N/A")
            review_status = germline.get("review_status", "N/A")

        genes = item.get("genes", [])
        if isinstance(genes, list) and genes:
            gene_symbols = list(set([g.get("symbol", "") for g in genes if g.get("symbol")]))
            gene_str = ", ".join(gene_symbols) if gene_symbols else "N/A"
        else:
            gene_str = "N/A"

        traits = item.get("trait_set", [])
        if isinstance(traits, list) and traits:
            trait_names = [t.get("trait_name", "") for t in traits if t.get("trait_name")]
            condition_str = ", ".join(trait_names[:3]) if trait_names else "N/A"
            if len(trait_names) > 3:
                condition_str += f" 他{len(trait_names)-3}件"
        else:
            condition_str = "N/A"

        var_set = item.get("variation_set", [])
        if isinstance(var_set, list) and var_set:
            var_type = var_set[0].get("variant_type", "N/A") if var_set else "N/A"
        else:
            var_type = "N/A"

        results.append(
            f"【ID: {uid}】{title}\n"
            f"  臨床的意義: {clinical_sig}\n"
            f"  レビューステータス: {review_status}\n"
            f"  遺伝子: {gene_str}\n"
            f"  バリアントタイプ: {var_type}\n"
            f"  関連疾患: {condition_str}\n"
            f"  リンク: https://www.ncbi.nlm.nih.gov/clinvar/variation/{uid}/"
        )

    if not results:
        return f"「{query}」の詳細情報を取得できませんでした。"

    header = f"検索結果: {len(results)}件表示 / 全{total_count}件\n"
    header += f"検索クエリ: {query}\n"
    header += "=" * 60 + "\n\n"

    return header + "\n\n".join(results)


@mcp.tool()
async def get_clinvar_variant(variant_id: str) -> str:
    """
    ClinVarの特定のバリアントIDの詳細情報を取得します。

    Args:
        variant_id: ClinVarのバリアントID(数字)
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        summary_url = f"{NCBI_BASE}/esummary.fcgi"
        summary_params = {
            "db": "clinvar",
            "id": variant_id,
            "retmode": "json"
        }
        resp = await client.get(summary_url, params=summary_params)
        data = resp.json()

        item = data.get("result", {}).get(variant_id, {})
        if not item or isinstance(item, list):
            return f"ID {variant_id} のバリアントが見つかりませんでした。"

        title = item.get("title", "N/A")
        obj_type = item.get("obj_type", "N/A")

        clinical_sig = "N/A"
        review_status = "N/A"
        last_evaluated = "N/A"

        clin_sig_obj = item.get("clinical_significance", {})
        if isinstance(clin_sig_obj, dict):
            clinical_sig = clin_sig_obj.get("description", "N/A")
            review_status = clin_sig_obj.get("review_status", "N/A")
            last_evaluated = clin_sig_obj.get("last_evaluated", "N/A")

        germline = item.get("germline_classification", {})
        if isinstance(germline, dict) and clinical_sig == "N/A":
            clinical_sig = germline.get("description", "N/A")
            review_status = germline.get("review_status", "N/A")
            last_evaluated = germline.get("last_evaluated", "N/A")

        genes = item.get("genes", [])
        if isinstance(genes, list) and genes:
            gene_info = []
            for g in genes:
                symbol = g.get("symbol", "")
                geneid = g.get("geneid", "")
                if symbol:
                    gene_info.append(f"{symbol} (GeneID: {geneid})" if geneid else symbol)
            gene_str = ", ".join(gene_info) if gene_info else "N/A"
        else:
            gene_str = "N/A"

        traits = item.get("trait_set", [])
        if isinstance(traits, list) and traits:
            trait_names = [t.get("trait_name", "") for t in traits if t.get("trait_name")]
            condition_str = "\n    - ".join(trait_names) if trait_names else "N/A"
        else:
            condition_str = "N/A"

        var_set = item.get("variation_set", [])
        if isinstance(var_set, list) and var_set:
            var_info = var_set[0]
            var_type = var_info.get("variant_type", "N/A")
            cdna_change = var_info.get("cdna_change", "N/A")
            canonical_spdi = var_info.get("canonical_spdi", "N/A")
        else:
            var_type = "N/A"
            cdna_change = "N/A"
            canonical_spdi = "N/A"

        accession = item.get("accession", "N/A")

        return (
            f"バリアント詳細\n"
            f"{'='*60}\n"
            f"ID: {variant_id}\n"
            f"アクセッション: {accession}\n"
            f"タイトル: {title}\n"
            f"オブジェクトタイプ: {obj_type}\n"
            f"\n【バリアント情報】\n"
            f"  タイプ: {var_type}\n"
            f"  cDNA変化: {cdna_change}\n"
            f"  SPDI: {canonical_spdi}\n"
            f"\n【臨床的意義】\n"
            f"  判定: {clinical_sig}\n"
            f"  レビューステータス: {review_status}\n"
            f"  最終評価日: {last_evaluated}\n"
            f"\n【遺伝子】\n  {gene_str}\n"
            f"\n【関連疾患】\n    - {condition_str}\n"
            f"\nClinVarリンク: https://www.ncbi.nlm.nih.gov/clinvar/variation/{variant_id}/"
        )


@mcp.tool()
async def search_clinvar_gene(gene_symbol: str, significance: str = "", max_results: int = 10) -> str:
    """
    特定の遺伝子のClinVarバリアントを検索します。

    Args:
        gene_symbol: 遺伝子シンボル(例: "BRCA1", "TP53")
        significance: 臨床的意義でフィルタ(例: "pathogenic", "likely pathogenic", "uncertain")
        max_results: 取得する最大件数(デフォルト10)
    """
    query = f"{gene_symbol}[gene]"
    if significance:
        query += f' AND "{significance}"[clinsig]'

    async with httpx.AsyncClient(timeout=30.0) as client:
        search_url = f"{NCBI_BASE}/esearch.fcgi"
        search_params = {
            "db": "clinvar",
            "term": query,
            "retmax": max_results,
            "retmode": "json"
        }
        search_resp = await client.get(search_url, params=search_params)
        search_data = search_resp.json()

        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        total_count = search_data.get("esearchresult", {}).get("count", "0")

        if not id_list:
            msg = f"遺伝子「{gene_symbol}」"
            if significance:
                msg += f"（{significance}）"
            msg += "に一致するバリアントが見つかりませんでした。"
            return msg

        summary_url = f"{NCBI_BASE}/esummary.fcgi"
        summary_params = {
            "db": "clinvar",
            "id": ",".join(id_list),
            "retmode": "json"
        }
        summary_resp = await client.get(summary_url, params=summary_params)
        summary_data = summary_resp.json()

        results = []
        for uid in id_list:
            item = summary_data.get("result", {}).get(uid, {})
            if not item or isinstance(item, list):
                continue

            title = item.get("title", "N/A")

            clinical_sig = "N/A"
            review_status = "N/A"

            clin_sig_obj = item.get("clinical_significance", {})
            if isinstance(clin_sig_obj, dict):
                clinical_sig = clin_sig_obj.get("description", "N/A")
                review_status = clin_sig_obj.get("review_status", "N/A")

            germline = item.get("germline_classification", {})
            if isinstance(germline, dict) and clinical_sig == "N/A":
                clinical_sig = germline.get("description", "N/A")
                review_status = germline.get("review_status", "N/A")

            traits = item.get("trait_set", [])
            if isinstance(traits, list) and traits:
                trait_names = [t.get("trait_name", "") for t in traits if t.get("trait_name")]
                condition_str = ", ".join(trait_names[:2]) if trait_names else "N/A"
            else:
                condition_str = "N/A"

            results.append(
                f"【ID: {uid}】{title}\n"
                f"  臨床的意義: {clinical_sig}\n"
                f"  レビューステータス: {review_status}\n"
                f"  関連疾患: {condition_str}\n"
                f"  リンク: https://www.ncbi.nlm.nih.gov/clinvar/variation/{uid}/"
            )

        if not results:
            return f"遺伝子「{gene_symbol}」の詳細情報を取得できませんでした。"

        header = f"遺伝子 {gene_symbol} のバリアント検索結果\n"
        if significance:
            header += f"フィルタ: {significance}\n"
        header += f"表示: {len(results)}件 / 全{total_count}件\n"
        header += "=" * 60 + "\n\n"

        return header + "\n\n".join(results)


@mcp.tool()
async def get_clinvar_submissions(variant_id: str) -> str:
    """
    特定バリアントの全サブミッション（提出）詳細を取得します。
    どの施設がどの根拠でPathogenic/VUS/Benignと判定したかを確認できます。
    Conflicting interpretationsの解決に必須のツールです。

    Args:
        variant_id: ClinVarのバリアントID(数字)
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        # efetch XMLでVCV（全サブミッション含む）を取得
        efetch_url = f"{NCBI_BASE}/efetch.fcgi"
        efetch_params = {
            "db": "clinvar",
            "id": variant_id,
            "rettype": "vcv",
            "is_variationid": "",
            "from_esearch": "true",
            "retmode": "xml"
        }
        resp = await client.get(efetch_url, params=efetch_params)

        if resp.status_code != 200:
            return f"エラー: {resp.status_code}"

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            return f"XMLパースエラー: {e}"

        # VariationArchive を探す
        var_archive = root.find(".//VariationArchive")
        if var_archive is None:
            # 直接rootがVariationArchiveの場合
            if root.tag == "ClinVarResult-Set":
                var_archive = root.find(".//VariationArchive")
            if var_archive is None:
                return f"ID {variant_id} のバリアント情報が見つかりませんでした。"

        var_name = var_archive.get("VariationName", "N/A")
        var_type = var_archive.get("VariationType", "N/A")
        accession = var_archive.get("Accession", "N/A")
        version = var_archive.get("Version", "")
        num_submitters = var_archive.get("NumberOfSubmitters", "N/A")
        num_submissions = var_archive.get("NumberOfSubmissions", "N/A")

        header = (
            f"ClinVar サブミッション詳細\n"
            f"{'='*60}\n"
            f"バリアント: {var_name}\n"
            f"アクセッション: {accession}.{version}\n"
            f"タイプ: {var_type}\n"
            f"提出者数: {num_submitters} / 提出数: {num_submissions}\n"
            f"{'='*60}\n\n"
        )

        # ClassifiedRecord / Classifications から全体の判定を取得
        interp_record = var_archive.find(".//ClassifiedRecord")
        if interp_record is None:
            interp_record = var_archive.find(".//InterpretedRecord")

        overall_sig = "N/A"
        review_status = "N/A"
        if interp_record is not None:
            # GermlineClassification or Classifications
            for cls_tag in ["GermlineClassification", "Classifications/GermlineClassification",
                           "SomaticClinicalImpact", "Classifications/SomaticClinicalImpact",
                           "OncogenicityClassification", "Classifications/OncogenicityClassification",
                           "Interpretations/Interpretation"]:
                cls_elem = interp_record.find(f".//{cls_tag}")
                if cls_elem is not None:
                    # Description child
                    desc = cls_elem.find("Description")
                    if desc is not None and desc.text:
                        overall_sig = desc.text
                    # ReviewStatus child
                    rs = cls_elem.find("ReviewStatus")
                    if rs is not None and rs.text:
                        review_status = rs.text
                    break

        header += f"【全体判定】{overall_sig}\n"
        header += f"【レビューステータス】{review_status}\n\n"

        # 個別サブミッション（ClinicalAssertion）を取得
        assertions = var_archive.findall(".//ClinicalAssertion")

        if not assertions:
            return header + "個別サブミッション情報が取得できませんでした。"

        submissions = []
        for i, assertion in enumerate(assertions, 1):
            # サブミッター
            submitter_elem = assertion.find(".//ClinVarSubmissionID")
            submitter = submitter_elem.get("submitter", "N/A") if submitter_elem is not None else "N/A"

            # SCV アクセッション
            clinvar_acc = assertion.find(".//ClinVarAccession")
            scv = clinvar_acc.get("Accession", "N/A") if clinvar_acc is not None else "N/A"
            org_name = clinvar_acc.get("SubmitterName", submitter) if clinvar_acc is not None else submitter

            # 臨床的意義
            sig = "N/A"
            for sig_path in ["Classification/GermlineClassification",
                            "Classification/SomaticClinicalImpact",
                            "Classification/OncogenicityClassification",
                            "Classification",
                            "Interpretation/Description"]:
                sig_elem = assertion.find(f".//{sig_path}")
                if sig_elem is not None:
                    if sig_elem.text and sig_elem.text.strip():
                        sig = sig_elem.text.strip()
                        break
                    # Check Description child
                    desc_child = sig_elem.find("Description")
                    if desc_child is not None and desc_child.text:
                        sig = desc_child.text.strip()
                        break

            # 評価日
            date_elem = assertion.find(".//Classification")
            eval_date = "N/A"
            if date_elem is not None:
                eval_date = date_elem.get("DateLastEvaluated", "N/A")

            # 手法
            method_elem = assertion.find(".//MethodType")
            method = method_elem.text if method_elem is not None and method_elem.text else "N/A"

            # 疾患
            trait_name_elem = assertion.find(".//TraitSet/Trait/Name/ElementValue")
            condition = trait_name_elem.text if trait_name_elem is not None and trait_name_elem.text else "N/A"

            # ACMG基準（AttributeSetにcitationやcommentとして含まれる場合）
            acmg_codes = []
            for attr in assertion.findall(".//AttributeSet/Attribute"):
                attr_type = attr.get("Type", "")
                if "ACMG" in attr_type.upper() or "AssertionMethod" in attr_type or attr_type == "ModeOfInheritance":
                    if attr.text:
                        acmg_codes.append(f"{attr_type}: {attr.text}")

            # Comment
            comment_elem = assertion.find(".//Classification/Comment")
            comment = ""
            if comment_elem is not None and comment_elem.text:
                comment = comment_elem.text[:200]

            entry = f"--- サブミッション {i}: {scv} ---\n"
            entry += f"  施設: {org_name}\n"
            entry += f"  判定: {sig}\n"
            entry += f"  評価日: {eval_date}\n"
            entry += f"  手法: {method}\n"
            entry += f"  疾患: {condition}\n"
            if acmg_codes:
                entry += f"  基準: {'; '.join(acmg_codes)}\n"
            if comment:
                entry += f"  コメント: {comment}\n"

            submissions.append(entry)

        return header + "\n".join(submissions)


@mcp.tool()
async def search_clinvar_by_condition(disease_name: str, significance: str = "", max_results: int = 10) -> str:
    """
    疾患名でClinVarバリアントを検索します。
    特定のがん種に関連するPathogenicバリアントの一覧取得に有用です。

    Args:
        disease_name: 疾患名(例: "breast cancer", "Lynch syndrome", "Li-Fraumeni syndrome")
        significance: 臨床的意義でフィルタ(例: "pathogenic", "likely pathogenic")省略可
        max_results: 取得する最大件数(デフォルト10)
    """
    query = f'"{disease_name}"[disease/phenotype]'
    if significance:
        query += f' AND "{significance}"[clinsig]'

    async with httpx.AsyncClient(timeout=30.0) as client:
        search_url = f"{NCBI_BASE}/esearch.fcgi"
        search_params = {
            "db": "clinvar",
            "term": query,
            "retmax": max_results,
            "retmode": "json"
        }
        search_resp = await client.get(search_url, params=search_params)
        search_data = search_resp.json()

        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        total_count = search_data.get("esearchresult", {}).get("count", "0")

        if not id_list:
            msg = f"疾患「{disease_name}」"
            if significance:
                msg += f"（{significance}）"
            msg += "に一致するバリアントが見つかりませんでした。"
            return msg

        summary_url = f"{NCBI_BASE}/esummary.fcgi"
        summary_params = {
            "db": "clinvar",
            "id": ",".join(id_list),
            "retmode": "json"
        }
        summary_resp = await client.get(summary_url, params=summary_params)
        summary_data = summary_resp.json()

        results = []
        for uid in id_list:
            item = summary_data.get("result", {}).get(uid, {})
            if not item or isinstance(item, list):
                continue

            title = item.get("title", "N/A")

            clinical_sig = "N/A"
            review_status = "N/A"

            clin_sig_obj = item.get("clinical_significance", {})
            if isinstance(clin_sig_obj, dict):
                clinical_sig = clin_sig_obj.get("description", "N/A")
                review_status = clin_sig_obj.get("review_status", "N/A")

            germline = item.get("germline_classification", {})
            if isinstance(germline, dict) and clinical_sig == "N/A":
                clinical_sig = germline.get("description", "N/A")
                review_status = germline.get("review_status", "N/A")

            genes = item.get("genes", [])
            if isinstance(genes, list) and genes:
                gene_symbols = list(set([g.get("symbol", "") for g in genes if g.get("symbol")]))
                gene_str = ", ".join(gene_symbols) if gene_symbols else "N/A"
            else:
                gene_str = "N/A"

            traits = item.get("trait_set", [])
            if isinstance(traits, list) and traits:
                trait_names = [t.get("trait_name", "") for t in traits if t.get("trait_name")]
                condition_str = ", ".join(trait_names[:3]) if trait_names else "N/A"
            else:
                condition_str = "N/A"

            results.append(
                f"【ID: {uid}】{title}\n"
                f"  臨床的意義: {clinical_sig}\n"
                f"  レビューステータス: {review_status}\n"
                f"  遺伝子: {gene_str}\n"
                f"  関連疾患: {condition_str}\n"
                f"  リンク: https://www.ncbi.nlm.nih.gov/clinvar/variation/{uid}/"
            )

        if not results:
            return f"疾患「{disease_name}」の詳細情報を取得できませんでした。"

        header = f"疾患別 ClinVar検索結果\n"
        header += f"疾患: {disease_name}\n"
        if significance:
            header += f"フィルタ: {significance}\n"
        header += f"表示: {len(results)}件 / 全{total_count}件\n"
        header += "=" * 60 + "\n\n"

        return header + "\n\n".join(results)


@mcp.tool()
async def get_clinvar_gene_summary(gene_symbol: str) -> str:
    """
    遺伝子単位のClinVarバリアント統計を取得します。
    Pathogenic/Likely pathogenic/VUS/Benign等の件数を集計します。
    初見の遺伝子の全体像把握に便利です。

    Args:
        gene_symbol: 遺伝子シンボル(例: "BRCA1", "TP53", "KRAS")
    """
    categories = [
        ("pathogenic", "Pathogenic"),
        ("likely pathogenic", "Likely pathogenic"),
        ("uncertain significance", "VUS (Uncertain significance)"),
        ("likely benign", "Likely benign"),
        ("benign", "Benign"),
        ("conflicting classifications", "Conflicting classifications"),
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 全体の件数
        total_resp = await client.get(
            f"{NCBI_BASE}/esearch.fcgi",
            params={
                "db": "clinvar",
                "term": f"{gene_symbol}[gene]",
                "retmode": "json",
                "retmax": 0
            }
        )
        total_data = total_resp.json()
        total_count = total_data.get("esearchresult", {}).get("count", "0")

        # カテゴリ別集計（レート制限回避のため間隔を空ける）
        results = []
        for sig, label in categories:
            query = f'{gene_symbol}[gene] AND "{sig}"[clinsig]'
            await asyncio.sleep(0.4)
            resp = await client.get(
                f"{NCBI_BASE}/esearch.fcgi",
                params={
                    "db": "clinvar",
                    "term": query,
                    "retmode": "json",
                    "retmax": 0
                }
            )
            data = resp.json()
            count = data.get("esearchresult", {}).get("count", "0")
            results.append(f"  {label}: {count}件")

        # レビューステータス別（expert panel, practice guideline）
        expert_query = f'{gene_symbol}[gene] AND "reviewed by expert panel"[review_status]'
        await asyncio.sleep(0.4)
        expert_resp = await client.get(
            f"{NCBI_BASE}/esearch.fcgi",
            params={
                "db": "clinvar",
                "term": expert_query,
                "retmode": "json",
                "retmax": 0
            }
        )
        expert_count = expert_resp.json().get("esearchresult", {}).get("count", "0")

        guideline_query = f'{gene_symbol}[gene] AND "practice guideline"[review_status]'
        await asyncio.sleep(0.4)
        guideline_resp = await client.get(
            f"{NCBI_BASE}/esearch.fcgi",
            params={
                "db": "clinvar",
                "term": guideline_query,
                "retmode": "json",
                "retmax": 0
            }
        )
        guideline_count = guideline_resp.json().get("esearchresult", {}).get("count", "0")

        output = (
            f"ClinVar 遺伝子サマリー: {gene_symbol}\n"
            f"{'='*60}\n"
            f"登録バリアント総数: {total_count}件\n"
            f"\n【臨床的意義別】\n"
            + "\n".join(results)
            + f"\n\n【高信頼レビュー】\n"
            f"  Expert panel reviewed: {expert_count}件\n"
            f"  Practice guideline: {guideline_count}件\n"
            f"\nClinVarリンク: https://www.ncbi.nlm.nih.gov/clinvar/?term={gene_symbol}%5Bgene%5D"
        )

        return output


if __name__ == "__main__":
    mcp.run(transport="stdio")
