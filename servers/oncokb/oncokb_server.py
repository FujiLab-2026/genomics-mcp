from mcp.server.fastmcp import FastMCP
import httpx
import os

mcp = FastMCP("OncoKB")

ONCOKB_BASE = "https://www.oncokb.org/api/v1"
ONCOKB_TOKEN = os.environ.get("ONCOKB_TOKEN", "")

# 共通ヘッダー（全リクエストで使用）
def get_headers():
    return {
        "Authorization": f"Bearer {ONCOKB_TOKEN}",
        "Accept": "application/json"
    }


@mcp.tool()
async def get_cancer_genes() -> str:
    """
    OncoKBに登録されているがん遺伝子の一覧を取得します。
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{ONCOKB_BASE}/utils/cancerGeneList",
            headers=get_headers()
        )
        
        if resp.status_code != 200:
            return f"エラー: {resp.status_code}"
        
        genes = resp.json()
        
        results = []
        for gene in genes[:30]:  # 最初の30件
            hugo = gene.get("hugoSymbol", "N/A")
            # oncogene/tsg はbool値またはGene Type文字列で返る場合がある
            oncogene = gene.get("oncogene", False)
            tsg = gene.get("tsg", False)
            gene_type = gene.get("geneType", "")
            
            # geneType文字列での判定もフォールバック
            if not oncogene and "ONCOGENE" in str(gene_type).upper():
                oncogene = True
            if not tsg and "TSG" in str(gene_type).upper():
                tsg = True
            
            oncogene_str = "✓" if oncogene else ""
            tsg_str = "✓" if tsg else ""
            
            results.append(f"{hugo} | Oncogene: {oncogene_str} | TSG: {tsg_str}")
        
        header = f"OncoKB がん遺伝子リスト（{len(genes)}件中30件表示）\n"
        header += "=" * 50 + "\n\n"
        
        return header + "\n".join(results)


async def _get_all_curated_genes_data() -> list | str:
    """
    データ取得用内部関数
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{ONCOKB_BASE}/utils/allCuratedGenes",
            headers=get_headers()
        )
        
        if resp.status_code != 200:
            return f"エラー: {resp.status_code}"
        
        return resp.json()

@mcp.tool()
async def get_all_curated_genes() -> str:
    """
    OncoKBでキュレーションされた全遺伝子の情報を取得します。
    """
    genes = await _get_all_curated_genes_data()
    
    if isinstance(genes, str):
        return genes
    
    results = []
    for gene in genes[:30]:
        hugo = gene.get("hugoSymbol", "N/A")
        highest_level = gene.get("highestSensitiveLevel", "") or "N/A"
        highest_resistance = gene.get("highestResistanceLevel", "") or "N/A"
        
        results.append(
            f"【{hugo}】\n"
            f"  最高感受性レベル: {highest_level}\n"
            f"  最高耐性レベル: {highest_resistance}"
        )
    
    header = f"OncoKB キュレーション済み遺伝子（{len(genes)}件中30件表示）\n"
    header += "=" * 50 + "\n\n"
    
    return header + "\n\n".join(results)


async def _annotate_mutation_data(hugo_symbol: str, alteration: str, tumor_type: str = "") -> dict | str:
    """
    データ取得用内部関数
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {
            "hugoSymbol": hugo_symbol,
            "alteration": alteration,
        }
        if tumor_type:
            params["tumorType"] = tumor_type
        
        resp = await client.get(
            f"{ONCOKB_BASE}/annotate/mutations/byProteinChange",
            params=params,
            headers=get_headers()
        )
        
        if resp.status_code == 401:
            return "エラー: 401 - APIキーが無効または期限切れです。oncokb_server.py内のONCOKB_TOKENを更新してください。"
        if resp.status_code != 200:
            return f"エラー: {resp.status_code}"
        
        return resp.json()

@mcp.tool()
async def annotate_mutation(hugo_symbol: str, alteration: str, tumor_type: str = "") -> str:
    """
    特定の遺伝子変異のOncoKBアノテーションを取得します。

    Args:
        hugo_symbol: 遺伝子シンボル（例: "KRAS", "BRAF", "BRCA1"）
        alteration: 変異（例: "G12D", "V600E", "Oncogenic Mutations"）
        tumor_type: がん種（例: "Pancreatic Cancer", "PDAC"）省略可
    """
    data = await _annotate_mutation_data(hugo_symbol, alteration, tumor_type)
    
    if isinstance(data, str):
        return data
        
    # 基本情報
    query = data.get("query", {})
    gene = query.get("hugoSymbol", hugo_symbol)
    alt = query.get("alteration", alteration)
    
    # オンコジェニシティ
    oncogenic = data.get("oncogenic", "N/A") or "N/A"
    
    # 変異効果
    mutation_effect = data.get("mutationEffect", {})
    known_effect = mutation_effect.get("knownEffect", "N/A") or "N/A"
    
    # 治療レベル
    highest_sensitive = data.get("highestSensitiveLevel", "") or "N/A"
    highest_resistance = data.get("highestResistanceLevel", "") or "N/A"
    highest_diagnostic = data.get("highestDiagnosticImplicationLevel", "") or "N/A"
    highest_prognostic = data.get("highestPrognosticImplicationLevel", "") or "N/A"
    
    # 治療情報
    treatments = data.get("treatments", []) or []
    treatment_list = []
    for t in treatments[:5]:
        drugs = ", ".join([d.get("drugName", "") for d in t.get("drugs", [])])
        level = t.get("level", "N/A")
        indications = ", ".join([i.get("name", "") for i in t.get("levelAssociatedCancerTypes", [])])
        treatment_list.append(f"  - {drugs} (Level {level}): {indications}")
    
    treatment_str = "\n".join(treatment_list) if treatment_list else "  なし"
    
    # サマリー情報
    gene_summary = data.get("geneSummary", "") or ""
    variant_summary = data.get("variantSummary", "") or ""
    tumor_summary = data.get("tumorTypeSummary", "") or ""
    
    summary_section = ""
    if gene_summary:
        summary_section += f"\n【遺伝子サマリー】\n  {gene_summary}\n"
    if variant_summary:
        summary_section += f"\n【変異サマリー】\n  {variant_summary}\n"
    if tumor_summary:
        summary_section += f"\n【腫瘍型サマリー】\n  {tumor_summary}\n"
    
    return (
        f"OncoKB アノテーション結果\n"
        f"{'='*60}\n"
        f"遺伝子: {gene}\n"
        f"変異: {alt}\n"
        f"\n【オンコジェニシティ】\n"
        f"  判定: {oncogenic}\n"
        f"  既知の効果: {known_effect}\n"
        f"\n【エビデンスレベル】\n"
        f"  治療感受性: {highest_sensitive}\n"
        f"  治療耐性: {highest_resistance}\n"
        f"  診断: {highest_diagnostic}\n"
        f"  予後: {highest_prognostic}\n"
        f"\n【関連治療】\n{treatment_str}\n"
        f"{summary_section}"
        f"\nOncoKBリンク: https://www.oncokb.org/gene/{gene}/{alt}"
    )


@mcp.tool()
async def get_oncokb_levels() -> str:
    """
    OncoKBのエビデンスレベルの説明を取得します。
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{ONCOKB_BASE}/levels",
            headers=get_headers()
        )
        
        if resp.status_code != 200:
            return f"エラー: {resp.status_code}"
        
        levels = resp.json()
        
        results = []
        
        # レスポンスが辞書の場合: {"LEVEL_1": "説明文", ...}
        if isinstance(levels, dict):
            for level_name, description in levels.items():
                results.append(f"【{level_name}】\n  {description}")
        # レスポンスがリストの場合: [{"levelOfEvidence": "LEVEL_1", "description": "..."}, ...]
        elif isinstance(levels, list):
            for level in levels:
                if isinstance(level, dict):
                    level_name = level.get("levelOfEvidence", level.get("level", "N/A"))
                    description = level.get("description", "N/A")
                    results.append(f"【{level_name}】\n  {description}")
                else:
                    results.append(str(level))
        else:
            return f"予期しないレスポンス形式: {type(levels).__name__}"
        
        header = "OncoKB エビデンスレベル一覧\n"
        header += "=" * 50 + "\n\n"
        
        return header + "\n\n".join(results)


@mcp.tool()
async def search_gene_info(hugo_symbol: str) -> str:
    """
    特定の遺伝子のOncoKB情報を検索します。

    Args:
        hugo_symbol: 遺伝子シンボル（例: "KRAS", "TP53", "BRCA2"）
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # cancerGeneListからoncogene/tsg情報を取得
        resp_cancer = await client.get(
            f"{ONCOKB_BASE}/utils/cancerGeneList",
            headers=get_headers()
        )
        # allCuratedGenesからレベル情報を取得
        resp_curated = await client.get(
            f"{ONCOKB_BASE}/utils/allCuratedGenes",
            headers=get_headers()
        )
        
        if resp_cancer.status_code != 200:
            return f"エラー (cancerGeneList): {resp_cancer.status_code}"
        if resp_curated.status_code != 200:
            return f"エラー (allCuratedGenes): {resp_curated.status_code}"
        
        cancer_genes = resp_cancer.json()
        curated_genes = resp_curated.json()
        
        # cancerGeneListから遺伝子分類を検索
        target_cancer = None
        for gene in cancer_genes:
            if gene.get("hugoSymbol", "").upper() == hugo_symbol.upper():
                target_cancer = gene
                break
        
        # allCuratedGenesからレベル情報を検索
        target_curated = None
        for gene in curated_genes:
            if gene.get("hugoSymbol", "").upper() == hugo_symbol.upper():
                target_curated = gene
                break
        
        if not target_cancer and not target_curated:
            return f"遺伝子「{hugo_symbol}」はOncoKBに登録されていません。"
        
        hugo = hugo_symbol.upper()
        
        # Oncogene/TSG判定（cancerGeneListから）
        if target_cancer:
            hugo = target_cancer.get("hugoSymbol", hugo)
            oncogene = target_cancer.get("oncogene", False)
            tsg = target_cancer.get("tsg", False)
            gene_type = target_cancer.get("geneType", "")
            if not oncogene and "ONCOGENE" in str(gene_type).upper():
                oncogene = True
            if not tsg and "TSG" in str(gene_type).upper():
                tsg = True
        else:
            oncogene = False
            tsg = False
        
        oncogene_str = "Yes" if oncogene else "No"
        tsg_str = "Yes" if tsg else "No"
        
        # レベル情報（allCuratedGenesから）
        if target_curated:
            highest_sensitive = target_curated.get("highestSensitiveLevel", "") or "N/A"
            highest_resistance = target_curated.get("highestResistanceLevel", "") or "N/A"
            highest_diagnostic = target_curated.get("highestDiagnosticImplicationLevel", "") or "N/A"
            highest_prognostic = target_curated.get("highestPrognosticImplicationLevel", "") or "N/A"
            summary = target_curated.get("summary", "") or ""
            background = target_curated.get("background", "") or ""
        else:
            highest_sensitive = "N/A"
            highest_resistance = "N/A"
            highest_diagnostic = "N/A"
            highest_prognostic = "N/A"
            summary = ""
            background = ""
        
        result = (
            f"OncoKB 遺伝子情報\n"
            f"{'='*60}\n"
            f"遺伝子: {hugo}\n"
            f"\n【分類】\n"
            f"  Oncogene: {oncogene_str}\n"
            f"  Tumor Suppressor Gene: {tsg_str}\n"
            f"\n【最高エビデンスレベル】\n"
            f"  治療感受性: {highest_sensitive}\n"
            f"  治療耐性: {highest_resistance}\n"
            f"  診断: {highest_diagnostic}\n"
            f"  予後: {highest_prognostic}\n"
        )
        
        if summary:
            result += f"\n【サマリー】\n  {summary}\n"
        if background:
            result += f"\n【背景】\n  {background}\n"
        
        result += f"\nOncoKBリンク: https://www.oncokb.org/gene/{hugo}"
        
        return result


@mcp.tool()
async def annotate_cna(hugo_symbol: str, cna_type: str, tumor_type: str = "") -> str:
    """
    コピー数変化（CNA）のOncoKBアノテーションを取得します。
    CDKN2A deletion、KRAS amplificationなどの評価に使用します。

    Args:
        hugo_symbol: 遺伝子シンボル（例: "CDKN2A", "KRAS", "MYC", "ERBB2"）
        cna_type: コピー数変化の種類。AMPLIFICATION, DELETION, GAIN, LOSS のいずれか
        tumor_type: がん種（例: "Pancreatic Cancer", "Breast Cancer"）省略可
    """
    valid_types = ["AMPLIFICATION", "DELETION", "GAIN", "LOSS"]
    cna_upper = cna_type.upper()
    if cna_upper not in valid_types:
        return f"エラー: cna_typeは {', '.join(valid_types)} のいずれかを指定してください。入力値: {cna_type}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {
            "hugoSymbol": hugo_symbol,
            "copyNameAlterationType": cna_upper,
        }
        if tumor_type:
            params["tumorType"] = tumor_type

        resp = await client.get(
            f"{ONCOKB_BASE}/annotate/copyNumberAlterations",
            params=params,
            headers=get_headers()
        )

        if resp.status_code == 401:
            return "エラー: 401 - APIキーが無効または期限切れです。"
        if resp.status_code != 200:
            return f"エラー: {resp.status_code}"

        data = resp.json()

        query = data.get("query", {})
        gene = query.get("hugoSymbol", hugo_symbol)
        alt = query.get("alteration", cna_upper)

        oncogenic = data.get("oncogenic", "") or "N/A"
        mutation_effect = data.get("mutationEffect", {})
        known_effect = mutation_effect.get("knownEffect", "") or "N/A"

        highest_sensitive = data.get("highestSensitiveLevel", "") or "N/A"
        highest_resistance = data.get("highestResistanceLevel", "") or "N/A"
        highest_diagnostic = data.get("highestDiagnosticImplicationLevel", "") or "N/A"
        highest_prognostic = data.get("highestPrognosticImplicationLevel", "") or "N/A"

        treatments = data.get("treatments", []) or []
        treatment_list = []
        for t in treatments[:5]:
            drugs = ", ".join([d.get("drugName", "") for d in t.get("drugs", [])])
            level = t.get("level", "N/A")
            indications = ", ".join([i.get("name", "") for i in t.get("levelAssociatedCancerTypes", [])])
            treatment_list.append(f"  - {drugs} (Level {level}): {indications}")
        treatment_str = "\n".join(treatment_list) if treatment_list else "  なし"

        gene_summary = data.get("geneSummary", "") or ""
        variant_summary = data.get("variantSummary", "") or ""
        tumor_summary = data.get("tumorTypeSummary", "") or ""

        summary_section = ""
        if gene_summary:
            summary_section += f"\n【遺伝子サマリー】\n  {gene_summary}\n"
        if variant_summary:
            summary_section += f"\n【変異サマリー】\n  {variant_summary}\n"
        if tumor_summary:
            summary_section += f"\n【腫瘍型サマリー】\n  {tumor_summary}\n"

        return (
            f"OncoKB CNA アノテーション結果\n"
            f"{'='*60}\n"
            f"遺伝子: {gene}\n"
            f"CNA種別: {alt}\n"
            f"\n【オンコジェニシティ】\n"
            f"  判定: {oncogenic}\n"
            f"  既知の効果: {known_effect}\n"
            f"\n【エビデンスレベル】\n"
            f"  治療感受性: {highest_sensitive}\n"
            f"  治療耐性: {highest_resistance}\n"
            f"  診断: {highest_diagnostic}\n"
            f"  予後: {highest_prognostic}\n"
            f"\n【関連治療】\n{treatment_str}\n"
            f"{summary_section}"
            f"\nOncoKBリンク: https://www.oncokb.org/gene/{gene}"
        )


@mcp.tool()
async def annotate_structural_variant(
    hugo_symbol_a: str,
    hugo_symbol_b: str,
    structural_variant_type: str = "FUSION",
    is_functional_fusion: bool = True,
    tumor_type: str = ""
) -> str:
    """
    構造変異（融合遺伝子など）のOncoKBアノテーションを取得します。
    EML4-ALK fusion、BCR-ABL fusionなどの評価に使用します。

    Args:
        hugo_symbol_a: パートナー遺伝子A（例: "EML4", "BCR", "CD74"）
        hugo_symbol_b: パートナー遺伝子B（例: "ALK", "ABL1", "ROS1"）
        structural_variant_type: 構造変異の種類。FUSION, DELETION, TRANSLOCATION, DUPLICATION, INSERTION, INVERSION, UNKNOWN のいずれか（デフォルト: FUSION）
        is_functional_fusion: 機能的融合かどうか（デフォルト: True）
        tumor_type: がん種（例: "Lung Adenocarcinoma", "Pancreatic Cancer"）省略可
    """
    valid_types = ["DELETION", "TRANSLOCATION", "DUPLICATION", "INSERTION", "INVERSION", "FUSION", "UNKNOWN"]
    sv_upper = structural_variant_type.upper()
    if sv_upper not in valid_types:
        return f"エラー: structural_variant_typeは {', '.join(valid_types)} のいずれかを指定してください。入力値: {structural_variant_type}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {
            "hugoSymbolA": hugo_symbol_a,
            "hugoSymbolB": hugo_symbol_b,
            "structuralVariantType": sv_upper,
            "isFunctionalFusion": str(is_functional_fusion).lower(),
        }
        if tumor_type:
            params["tumorType"] = tumor_type

        resp = await client.get(
            f"{ONCOKB_BASE}/annotate/structuralVariants",
            params=params,
            headers=get_headers()
        )

        if resp.status_code == 401:
            return "エラー: 401 - APIキーが無効または期限切れです。"
        if resp.status_code != 200:
            return f"エラー: {resp.status_code}"

        data = resp.json()

        query = data.get("query", {})
        gene_a = query.get("hugoSymbolA", hugo_symbol_a)
        gene_b = query.get("hugoSymbolB", hugo_symbol_b)
        alt = query.get("alteration", f"{gene_a}-{gene_b} {sv_upper}")

        oncogenic = data.get("oncogenic", "") or "N/A"
        mutation_effect = data.get("mutationEffect", {})
        known_effect = mutation_effect.get("knownEffect", "") or "N/A"

        highest_sensitive = data.get("highestSensitiveLevel", "") or "N/A"
        highest_resistance = data.get("highestResistanceLevel", "") or "N/A"
        highest_diagnostic = data.get("highestDiagnosticImplicationLevel", "") or "N/A"
        highest_prognostic = data.get("highestPrognosticImplicationLevel", "") or "N/A"

        treatments = data.get("treatments", []) or []
        treatment_list = []
        for t in treatments[:5]:
            drugs = ", ".join([d.get("drugName", "") for d in t.get("drugs", [])])
            level = t.get("level", "N/A")
            indications = ", ".join([i.get("name", "") for i in t.get("levelAssociatedCancerTypes", [])])
            treatment_list.append(f"  - {drugs} (Level {level}): {indications}")
        treatment_str = "\n".join(treatment_list) if treatment_list else "  なし"

        gene_summary = data.get("geneSummary", "") or ""
        variant_summary = data.get("variantSummary", "") or ""
        tumor_summary = data.get("tumorTypeSummary", "") or ""

        summary_section = ""
        if gene_summary:
            summary_section += f"\n【遺伝子サマリー】\n  {gene_summary}\n"
        if variant_summary:
            summary_section += f"\n【変異サマリー】\n  {variant_summary}\n"
        if tumor_summary:
            summary_section += f"\n【腫瘍型サマリー】\n  {tumor_summary}\n"

        return (
            f"OncoKB 構造変異アノテーション結果\n"
            f"{'='*60}\n"
            f"パートナーA: {gene_a}\n"
            f"パートナーB: {gene_b}\n"
            f"変異: {alt}\n"
            f"種別: {sv_upper}\n"
            f"\n【オンコジェニシティ】\n"
            f"  判定: {oncogenic}\n"
            f"  既知の効果: {known_effect}\n"
            f"\n【エビデンスレベル】\n"
            f"  治療感受性: {highest_sensitive}\n"
            f"  治療耐性: {highest_resistance}\n"
            f"  診断: {highest_diagnostic}\n"
            f"  予後: {highest_prognostic}\n"
            f"\n【関連治療】\n{treatment_str}\n"
            f"{summary_section}"
            f"\nOncoKBリンク: https://www.oncokb.org/gene/{gene_a}"
        )


@mcp.tool()
async def annotate_mutation_by_hgvsg(hgvsg: str, tumor_type: str = "", reference_genome: str = "GRCh37") -> str:
    """
    ゲノム座標（HGVSg形式）から変異のOncoKBアノテーションを取得します。
    NGSパイプラインやVCFファイルの出力をそのまま入力できます。

    Args:
        hgvsg: HGVSg形式のゲノム変異（例: "7:g.140453136A>T" はBRAF V600E）
        tumor_type: がん種（例: "Pancreatic Cancer", "Melanoma"）省略可
        reference_genome: リファレンスゲノム。"GRCh37" または "GRCh38"（デフォルト: GRCh37）
    """
    if reference_genome not in ["GRCh37", "GRCh38"]:
        return f"エラー: reference_genomeは GRCh37 または GRCh38 を指定してください。入力値: {reference_genome}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        params = {
            "hgvsg": hgvsg,
            "referenceGenome": reference_genome,
        }
        if tumor_type:
            params["tumorType"] = tumor_type

        resp = await client.get(
            f"{ONCOKB_BASE}/annotate/mutations/byHGVSg",
            params=params,
            headers=get_headers()
        )

        if resp.status_code == 401:
            return "エラー: 401 - APIキーが無効または期限切れです。"
        if resp.status_code != 200:
            return f"エラー: {resp.status_code}"

        data = resp.json()

        query = data.get("query", {})
        gene = query.get("hugoSymbol", "N/A") or "N/A"
        alt = query.get("alteration", "N/A") or "N/A"
        hgvsg_query = query.get("hgvs", hgvsg) or hgvsg

        gene_exist = data.get("geneExist", False)
        variant_exist = data.get("variantExist", False)

        oncogenic = data.get("oncogenic", "") or "N/A"
        mutation_effect = data.get("mutationEffect", {})
        known_effect = mutation_effect.get("knownEffect", "") or "N/A"
        hotspot = data.get("hotspot", False)

        highest_sensitive = data.get("highestSensitiveLevel", "") or "N/A"
        highest_resistance = data.get("highestResistanceLevel", "") or "N/A"
        highest_diagnostic = data.get("highestDiagnosticImplicationLevel", "") or "N/A"
        highest_prognostic = data.get("highestPrognosticImplicationLevel", "") or "N/A"

        treatments = data.get("treatments", []) or []
        treatment_list = []
        for t in treatments[:5]:
            drugs = ", ".join([d.get("drugName", "") for d in t.get("drugs", [])])
            level = t.get("level", "N/A")
            indications = ", ".join([i.get("name", "") for i in t.get("levelAssociatedCancerTypes", [])])
            treatment_list.append(f"  - {drugs} (Level {level}): {indications}")
        treatment_str = "\n".join(treatment_list) if treatment_list else "  なし"

        gene_summary = data.get("geneSummary", "") or ""
        variant_summary = data.get("variantSummary", "") or ""
        tumor_summary = data.get("tumorTypeSummary", "") or ""

        summary_section = ""
        if gene_summary:
            summary_section += f"\n【遺伝子サマリー】\n  {gene_summary}\n"
        if variant_summary:
            summary_section += f"\n【変異サマリー】\n  {variant_summary}\n"
        if tumor_summary:
            summary_section += f"\n【腫瘍型サマリー】\n  {tumor_summary}\n"

        return (
            f"OncoKB HGVSg アノテーション結果\n"
            f"{'='*60}\n"
            f"HGVSg入力: {hgvsg}\n"
            f"リファレンスゲノム: {reference_genome}\n"
            f"遺伝子: {gene}\n"
            f"変異（タンパク変化）: {alt}\n"
            f"遺伝子登録: {'あり' if gene_exist else 'なし'}\n"
            f"変異登録: {'あり' if variant_exist else 'なし'}\n"
            f"ホットスポット: {'Yes' if hotspot else 'No'}\n"
            f"\n【オンコジェニシティ】\n"
            f"  判定: {oncogenic}\n"
            f"  既知の効果: {known_effect}\n"
            f"\n【エビデンスレベル】\n"
            f"  治療感受性: {highest_sensitive}\n"
            f"  治療耐性: {highest_resistance}\n"
            f"  診断: {highest_diagnostic}\n"
            f"  予後: {highest_prognostic}\n"
            f"\n【関連治療】\n{treatment_str}\n"
            f"{summary_section}"
            f"\nOncoKBリンク: https://www.oncokb.org/gene/{gene}/{alt}"
        )


async def _get_all_actionable_variants_data() -> dict | str:
    """
    データ取得用内部関数
    Returns:
        dict: {"type": "variants"|"genes", "data": ...}
        str: warning/error message
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # まずallActionableVariantsを試行
        resp = await client.get(
            f"{ONCOKB_BASE}/utils/allActionableVariants",
            headers=get_headers()
        )

        if resp.status_code == 200:
            variants = resp.json()
            if not variants:
                return "actionableバリアントが取得できませんでした。"
            return {"type": "variants", "data": variants}

        # 403/401の場合: allCuratedGenesから治療レベル付き遺伝子を抽出（フォールバック）
        resp2 = await client.get(
            f"{ONCOKB_BASE}/utils/allCuratedGenes",
            headers=get_headers()
        )
        if resp2.status_code != 200:
            return f"エラー: allActionableVariants({resp.status_code}), allCuratedGenes({resp2.status_code})。APIライセンスのアップグレードが必要な可能性があります。"

        genes = resp2.json()
        return {"type": "genes", "data": genes}


@mcp.tool()
async def get_all_actionable_variants() -> str:
    """
    OncoKBに登録されている全てのactionable（治療標的となりうる）バリアントを取得します。
    FDAレベルを含む治療関連バリアントの網羅的リストです。
    エキスパートパネルで検出バリアントがactionableか確認する際に有用です。
    """
    result = await _get_all_actionable_variants_data()
    
    if isinstance(result, str):
        return result
    
    data_type = result["type"]
    data_list = result["data"]
    
    if data_type == "variants":
        variants = data_list
        # レベル別に集計
        level_groups = {}
        for v in variants:
            gene = v.get("hugoSymbol", "N/A")
            alt = v.get("alteration", "N/A")
            cancer_type = v.get("cancerType", "N/A") or "全がん種"
            level = v.get("level", "N/A")
            drugs = v.get("drugs", "") or "N/A"

            if level not in level_groups:
                level_groups[level] = []
            level_groups[level].append(
                f"  {gene} {alt} | {cancer_type} | 薬剤: {drugs}"
            )

        level_order = ["LEVEL_1", "LEVEL_2", "LEVEL_3A", "LEVEL_3B", "LEVEL_4",
                       "LEVEL_R1", "LEVEL_R2", "LEVEL_Dx1", "LEVEL_Dx2", "LEVEL_Dx3",
                       "LEVEL_Px1", "LEVEL_Px2", "LEVEL_Px3"]

        results = []
        for level in level_order:
            if level in level_groups:
                entries = level_groups[level]
                results.append(f"\n【{level}】({len(entries)}件)")
                for entry in entries[:20]:
                    results.append(entry)
                if len(entries) > 20:
                    results.append(f"  ... 他{len(entries) - 20}件")

        for level, entries in level_groups.items():
            if level not in level_order:
                results.append(f"\n【{level}】({len(entries)}件)")
                for entry in entries[:10]:
                    results.append(entry)
                if len(entries) > 10:
                    results.append(f"  ... 他{len(entries) - 10}件")

        header = f"OncoKB Actionableバリアント一覧（全{len(variants)}件）\n"
        header += "=" * 60 + "\n"
        return header + "\n".join(results)

    elif data_type == "genes":
        genes = data_list
        # 治療レベルがある遺伝子を抽出
        actionable_genes = []
        for g in genes:
            hugo = g.get("hugoSymbol", "N/A")
            sensitive = g.get("highestSensitiveLevel", "") or ""
            resistance = g.get("highestResistanceLevel", "") or ""
            diagnostic = g.get("highestDiagnosticImplicationLevel", "") or ""
            prognostic = g.get("highestPrognosticImplicationLevel", "") or ""

            if sensitive or resistance or diagnostic or prognostic:
                levels = []
                if sensitive:
                    levels.append(f"感受性:{sensitive}")
                if resistance:
                    levels.append(f"耐性:{resistance}")
                if diagnostic:
                    levels.append(f"診断:{diagnostic}")
                if prognostic:
                    levels.append(f"予後:{prognostic}")
                actionable_genes.append(f"  {hugo} | {' | '.join(levels)}")

        header = (
            f"OncoKB Actionable遺伝子一覧（{len(actionable_genes)}遺伝子）\n"
            f"※ allActionableVariantsエンドポイントはアクセス制限のため、\n"
            f"  遺伝子単位の最高レベルを表示しています。\n"
            f"  個別バリアントの詳細はannotate_mutationで確認してください。\n"
            + "=" * 60 + "\n\n"
        )

        return header + "\n".join(actionable_genes)
    
    return "不明なデータタイプ"


@mcp.tool()
async def get_relevant_cancer_types(cancer_type: str) -> str:
    """
    OncoKBで使用される関連がん種マッピングを取得します。
    腫瘍型の名称が曖昧な場合や、OncoKBでの正式名称を確認する際に有用です。
    エキスパートパネルで正しいがん種名を指定してアノテーションするために使用します。

    Args:
        cancer_type: がん種名（例: "Pancreatic Cancer", "NSCLC", "Melanoma"）
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # OncoTree API（OncoKBが使用する腫瘍分類体系）で全腫瘍型を取得しローカルフィルタ
        oncotree_url = "http://oncotree.info/api/tumorTypes"
        try:
            resp = await client.get(oncotree_url, timeout=15.0)
        except Exception:
            resp = None

        if resp is not None and resp.status_code == 200:
            all_types = resp.json()
            # キーワードでフィルタ（name, mainType, code, tissueを検索）
            keywords = cancer_type.upper().split()
            matched = []
            for item in all_types:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "") or ""
                main_type = item.get("mainType", "") or ""
                code = item.get("code", "") or ""
                tissue = item.get("tissue", "") or ""
                search_target = f"{name} {main_type} {code} {tissue}".upper()
                if all(kw in search_target for kw in keywords):
                    matched.append(item)

            if matched:
                results = []
                for item in matched[:30]:
                    code = item.get("code", "N/A")
                    name = item.get("name", "N/A")
                    main_type = item.get("mainType", "N/A")
                    tissue = item.get("tissue", "N/A")
                    parent = item.get("parent", "")

                    entry = f"  - {name} [コード: {code}]"
                    if main_type and main_type != name:
                        entry += f" (大分類: {main_type})"
                    if tissue:
                        entry += f" | 組織: {tissue}"
                    if parent:
                        entry += f" | 親: {parent}"
                    results.append(entry)

                header = (
                    f"OncoTree がん種マッチング: 「{cancer_type}」\n"
                    f"OncoTreeはOncoKBが使用する腫瘍分類体系です。\n"
                    f"一致: {len(matched)}件"
                )
                if len(matched) > 30:
                    header += f"（先頭30件表示）"
                header += "\n" + "=" * 60 + "\n\n"
                header += "※ OncoKBのannotate_mutationのtumorType引数には、「コード」または「名前」を使用できます。\n\n"

                return header + "\n".join(results)

        # OncoTreeが使えない場合: OncoKB APIを試行
        try:
            resp2 = await client.get(
                f"{ONCOKB_BASE}/utils/relevantCancerTypes",
                params={"levelOfEvidence": "LEVEL_1"},
                headers=get_headers()
            )
        except Exception:
            resp2 = None

        if resp2 is not None and resp2.status_code == 200:
            data = resp2.json()
            matched = []
            for item in data:
                if isinstance(item, dict):
                    main_type = item.get("mainType", {}).get("name", "") if isinstance(item.get("mainType"), dict) else str(item.get("mainType", ""))
                    sub_type = item.get("name", "") or item.get("subtype", "") or ""
                else:
                    main_type = str(item)
                    sub_type = str(item)

                search_target = f"{main_type} {sub_type}".upper()
                keywords = cancer_type.upper().split()
                if any(kw in search_target for kw in keywords):
                    code = item.get("code", "") if isinstance(item, dict) else ""
                    tissue = item.get("tissue", "") if isinstance(item, dict) else ""
                    matched.append(f"  - {sub_type} [コード: {code}] (大分類: {main_type}) | 組織: {tissue}")

            if matched:
                header = f"OncoKB がん種マッチング: 「{cancer_type}」\n"
                header += f"一致: {len(matched)}件\n"
                header += "=" * 60 + "\n\n"
                return header + "\n".join(matched[:30])

        return (
            f"「{cancer_type}」に一致するがん種が見つかりませんでした。\n"
            f"OncoTree (https://oncotree.info) で直接検索するか、\n"
            f"英語の正式名称で再度お試しください。"
        )


if __name__ == "__main__":
    mcp.run(transport="stdio")
