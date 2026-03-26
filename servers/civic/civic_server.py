from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("CIViC")

CIVIC_API = "https://civicdb.org/api/graphql"


async def _graphql_query(query: str, variables: dict = None) -> dict:
    """CIViC GraphQL APIにクエリを送信する共通関数"""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(CIVIC_API, json=payload)
        if resp.status_code != 200:
            return {"error": f"API Error: {resp.status_code} - {resp.text[:200]}"}
        data = resp.json()
        if "errors" in data:
            return {"error": f"GraphQL Error: {data['errors']}"}
        return data


@mcp.tool()
async def search_civic_variants(gene_symbol: str, variant_name: str = "") -> str:
    """
    CIViCで遺伝子名・バリアント名からバリアントを検索します。

    Args:
        gene_symbol: 遺伝子シンボル（例: "KRAS", "BRAF", "EGFR"）
        variant_name: バリアント名（例: "V600E", "G12D"）。省略時は遺伝子の全バリアントを検索。
    """
    query = """
    query BrowseVariants($featureName: String, $variantName: String) {
      browseVariants(featureName: $featureName, variantName: $variantName, first: 20) {
        totalCount
        filteredCount
        nodes {
          id
          name
          link
          featureName
          diseases {
            name
          }
          therapies {
            name
          }
          evidenceItemCount
        }
      }
    }
    """

    variables = {"featureName": gene_symbol}
    if variant_name:
        variables["variantName"] = variant_name

    data = await _graphql_query(query, variables)

    if "error" in data:
        return f"エラー: {data['error']}"

    browse = data.get("data", {}).get("browseVariants", {})
    nodes = browse.get("nodes", [])
    total = browse.get("totalCount", 0)
    filtered = browse.get("filteredCount", 0)

    if not nodes:
        search_term = f"{gene_symbol} {variant_name}".strip()
        return f"CIViCで「{search_term}」に一致するバリアントが見つかりませんでした。"

    results = []
    for v in nodes:
        feature_name = v.get("featureName", "N/A")
        var_name = v.get("name", "N/A")
        var_id = v.get("id", "N/A")
        link = v.get("link", "")
        ev_count = v.get("evidenceItemCount", 0)

        diseases = v.get("diseases", [])
        disease_names = ", ".join([d.get("name", "") for d in diseases]) if diseases else "なし"

        therapies = v.get("therapies", [])
        therapy_names = ", ".join([t.get("name", "") for t in therapies]) if therapies else "なし"

        entry = f"【{feature_name} {var_name}】(CIViC ID: {var_id})\n"
        if link:
            entry += f"  リンク: https://civicdb.org{link}\n"
        entry += f"  エビデンス数: {ev_count}\n"
        entry += f"  関連疾患: {disease_names}\n"
        entry += f"  関連治療薬: {therapy_names}"

        results.append(entry)

    header = f"CIViC検索結果: {len(nodes)}件表示 / フィルタ後{filtered}件 / 全{total}件\n"
    header += f"検索: 遺伝子={gene_symbol}"
    if variant_name:
        header += f", バリアント={variant_name}"
    header += "\n" + "=" * 60 + "\n\n"

    return header + "\n\n".join(results)


@mcp.tool()
async def get_civic_evidence(gene_symbol: str, variant_name: str) -> str:
    """
    CIViCで特定バリアントの全エビデンスをEID単位で取得します。
    CIViCのEvidence table viewと同じ形式で、個別のEIDレコードを返します。

    返却カラム: EID, Disease, Therapies, Evidence Type (ET), Evidence Level (EL),
    Evidence Direction (ED), Significance (S), Variant Origin (VO), Rating, MP,
    Citation, Description

    Args:
        gene_symbol: 遺伝子シンボル（例: "BRAF"）
        variant_name: バリアント名（例: "V600E"）
    """
    # まず browseVariants でバリアントIDを取得
    browse_query = """
    query BrowseVariants($featureName: String, $variantName: String) {
      browseVariants(featureName: $featureName, variantName: $variantName, first: 5) {
        nodes {
          id
          name
          link
          featureName
        }
      }
    }
    """

    data = await _graphql_query(browse_query, {
        "featureName": gene_symbol,
        "variantName": variant_name
    })

    if "error" in data:
        return f"エラー: {data['error']}"

    browse_nodes = data.get("data", {}).get("browseVariants", {}).get("nodes", [])

    if not browse_nodes:
        return f"CIViCで「{gene_symbol} {variant_name}」が見つかりませんでした。"

    results = []

    for bv in browse_nodes:
        var_id = bv.get("id")
        feature_name = bv.get("featureName", "N/A")
        var_name_found = bv.get("name", "N/A")

        detail_query = """
        query GetVariant($id: Int!) {
          variant(id: $id) {
            id
            name
            link
            feature {
              name
            }
            molecularProfiles(first: 50) {
              totalCount
              nodes {
                id
                name
                evidenceItems(first: 50) {
                  totalCount
                  nodes {
                    id
                    status
                    evidenceType
                    evidenceLevel
                    evidenceDirection
                    significance
                    variantOrigin
                    evidenceRating
                    therapies {
                      id
                      name
                    }
                    therapyInteractionType
                    disease {
                      name
                    }
                    source {
                      citation
                      sourceUrl
                    }
                    description
                  }
                }
              }
            }
          }
        }
        """

        detail_data = await _graphql_query(detail_query, {"id": var_id})

        if "error" in detail_data:
            results.append(f"=== {feature_name} {var_name_found} ===\nエビデンス取得エラー: {detail_data['error']}")
            continue

        variant = detail_data.get("data", {}).get("variant")
        if not variant:
            continue

        mp_nodes = variant.get("molecularProfiles", {}).get("nodes", [])

        eid_records = []

        for mp in mp_nodes:
            mp_id = mp.get("id", "N/A")
            mp_name = mp.get("name", "N/A")
            ev_items = mp.get("evidenceItems", {}).get("nodes", [])

            for ev in ev_items:
                ev_status = ev.get("status", "")
                if ev_status not in ("ACCEPTED", "SUBMITTED"):
                    continue

                eid = ev.get("id", "N/A")
                ev_type = ev.get("evidenceType", "N/A")
                ev_level = ev.get("evidenceLevel", "N/A")
                direction = ev.get("evidenceDirection", "N/A")
                significance = ev.get("significance", "N/A")
                variant_origin = ev.get("variantOrigin", "N/A")
                rating = ev.get("evidenceRating", "N/A")
                disease = ev.get("disease", {}).get("name", "N/A") if ev.get("disease") else "N/A"
                description = (ev.get("description", "") or "")[:300]

                therapies = ev.get("therapies", [])
                interaction_type = ev.get("therapyInteractionType", None)
                if therapies:
                    therapy_names = [t.get("name", "") for t in therapies]
                    if interaction_type and len(therapy_names) > 1:
                        therapy_str = f" + ".join(therapy_names) + f" ({interaction_type})"
                    else:
                        therapy_str = ", ".join(therapy_names)
                else:
                    therapy_str = "N/A"

                source = ev.get("source", {})
                citation = source.get("citation", "N/A") if source else "N/A"
                source_url = source.get("sourceUrl", "") if source else ""

                status_tag = "" if ev_status == "ACCEPTED" else f" [{ev_status}]"
                record = (
                    f"  EID{eid} | {ev_type} | Level {ev_level} | {direction} | {significance}{status_tag}\n"
                    f"    Disease: {disease}\n"
                    f"    Therapies: {therapy_str}\n"
                    f"    Variant Origin: {variant_origin} | Rating: {rating}\n"
                    f"    MP: {mp_name} (MPID: {mp_id})\n"
                    f"    Citation: {citation}\n"
                    f"    Description: {description}"
                )

                eid_records.append((ev_status, ev_type, ev_level, eid, record))

        # Sort: ACCEPTED first, then PREDICTIVE first, then by level (A > B > C > D > E)
        status_order = {"ACCEPTED": 0, "SUBMITTED": 1}
        level_order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        type_order = {"PREDICTIVE": 0, "DIAGNOSTIC": 1, "PROGNOSTIC": 2, "PREDISPOSING": 3, "ONCOGENIC": 4, "FUNCTIONAL": 5}

        eid_records.sort(key=lambda x: (
            status_order.get(x[0], 99),
            type_order.get(x[1], 99),
            level_order.get(x[2], 99),
            x[3]
        ))

        variant_url = f"https://civicdb.org/variants/{var_id}/summary"
        section = f"=== {feature_name} {var_name_found} (Variant ID: {var_id}) ===\n"
        section += f"URL: {variant_url}\n"
        accepted_count = sum(1 for r in eid_records if r[0] == "ACCEPTED")
        submitted_count = sum(1 for r in eid_records if r[0] == "SUBMITTED")
        section += f"Evidence Items: {len(eid_records)}件 (ACCEPTED: {accepted_count}, SUBMITTED: {submitted_count})\n"
        section += "=" * 60 + "\n\n"

        if eid_records:
            for _, _, _, _, record in eid_records:
                section += record + "\n\n"
        else:
            section += "Evidence Items: なし\n"

        results.append(section)

    if not results:
        return f"CIViCで「{gene_symbol} {variant_name}」に一致するエビデンスが見つかりませんでした。"

    return "\n\n".join(results)


@mcp.tool()
async def search_civic_gene(gene_symbol: str) -> str:
    """
    CIViCで遺伝子の概要情報（登録バリアント数、エビデンス数）を取得します。

    Args:
        gene_symbol: 遺伝子シンボル（例: "KRAS", "TP53", "BRCA2"）
    """
    # CIViC V2 では featureTypeahead を使用して遺伝子を検索
    gene_query = """
    query SearchGene($queryTerm: String!) {
      featureTypeahead(featureType: GENE, queryTerm: $queryTerm) {
        id
        name
        description
        link
        featureType
        variants {
          totalCount
        }
      }
    }
    """

    data = await _graphql_query(gene_query, {"queryTerm": gene_symbol})

    if "error" in data:
        # フォールバック: browseFeatures を試行
        fallback_query = """
        query BrowseFeatures($featureName: String) {
          browseFeatures(featureName: $featureName, first: 5) {
            totalCount
            nodes {
              id
              name
              featureType
              description
              link
            }
          }
        }
        """
        data = await _graphql_query(fallback_query, {"featureName": gene_symbol})

        if "error" in data:
            return f"エラー: {data['error']}"

        nodes = data.get("data", {}).get("browseFeatures", {}).get("nodes", [])
        if not nodes:
            return f"CIViCで遺伝子「{gene_symbol}」が見つかりませんでした。"

        results = []
        for g in nodes:
            name = g.get("name", "N/A")
            gene_id = g.get("id", "N/A")
            description = (g.get("description", "") or "説明なし")[:300]
            link = g.get("link", "")

            entry = f"遺伝子: {name} (CIViC ID: {gene_id})\n"
            if link:
                entry += f"リンク: https://civicdb.org{link}\n"
            entry += f"説明: {description}"
            results.append(entry)

    else:
        # featureTypeahead の結果を処理
        features = data.get("data", {}).get("featureTypeahead", [])

        if not features:
            return f"CIViCで遺伝子「{gene_symbol}」が見つかりませんでした。"

        # 完全一致を優先
        exact_match = None
        for f in features:
            if f.get("name", "").upper() == gene_symbol.upper():
                exact_match = f
                break
        if not exact_match and features:
            exact_match = features[0]

        results = []
        targets = [exact_match] if exact_match else features[:5]
        for g in targets:
            name = g.get("name", "N/A")
            gene_id = g.get("id", "N/A")
            description = (g.get("description", "") or "説明なし")[:300]
            link = g.get("link", "")
            var_count = g.get("variants", {}).get("totalCount", 0)

            entry = f"遺伝子: {name} (CIViC ID: {gene_id})\n"
            if link:
                entry += f"リンク: https://civicdb.org{link}\n"
            entry += f"説明: {description}\n"
            entry += f"登録バリアント数: {var_count}"
            results.append(entry)

    # browseVariants でバリアント一覧も取得
    variant_query = """
    query BrowseVariants($featureName: String) {
      browseVariants(featureName: $featureName, first: 20) {
        totalCount
        nodes {
          id
          name
          featureName
          evidenceItemCount
        }
      }
    }
    """

    var_data = await _graphql_query(variant_query, {"featureName": gene_symbol})

    if "error" not in var_data:
        var_browse = var_data.get("data", {}).get("browseVariants", {})
        var_nodes = var_browse.get("nodes", [])
        var_total = var_browse.get("totalCount", 0)

        if var_nodes:
            var_section = f"\n\n--- {gene_symbol} のバリアント一覧 ({len(var_nodes)}件表示 / 全{var_total}件) ---\n"
            for var in var_nodes:
                ev_count = var.get("evidenceItemCount", 0)
                var_section += f"  - {var.get('name', 'N/A')} (ID: {var.get('id')}, エビデンス: {ev_count})\n"
            if var_total > 20:
                var_section += f"  ... 他{var_total - 20}件\n"
            results.append(var_section)

    return "\n\n".join(results)


@mcp.tool()
async def search_civic_by_disease(disease_name: str) -> str:
    """
    CIViCで疾患名からバリアント・エビデンスを検索します。
    特定のがん種でactionableなバリアントを網羅的に探すのに有用です。

    Args:
        disease_name: 疾患名（例: "Pancreatic Cancer", "Melanoma", "Lung Adenocarcinoma"）
    """
    query = """
    query BrowseVariants($diseaseName: String) {
      browseVariants(diseaseName: $diseaseName, first: 30) {
        totalCount
        filteredCount
        nodes {
          id
          name
          link
          featureName
          diseases {
            name
          }
          therapies {
            name
          }
          evidenceItemCount
        }
      }
    }
    """

    data = await _graphql_query(query, {"diseaseName": disease_name})

    if "error" in data:
        return f"エラー: {data['error']}"

    browse = data.get("data", {}).get("browseVariants", {})
    nodes = browse.get("nodes", [])
    total = browse.get("totalCount", 0)
    filtered = browse.get("filteredCount", 0)

    if not nodes:
        return f"CIViCで疾患「{disease_name}」に関連するバリアントが見つかりませんでした。"

    results = []
    for v in nodes:
        feature_name = v.get("featureName", "N/A")
        var_name = v.get("name", "N/A")
        var_id = v.get("id", "N/A")
        link = v.get("link", "")
        ev_count = v.get("evidenceItemCount", 0)

        diseases = v.get("diseases", [])
        disease_names = ", ".join([d.get("name", "") for d in diseases]) if diseases else "なし"

        therapies = v.get("therapies", [])
        therapy_names = ", ".join([t.get("name", "") for t in therapies]) if therapies else "なし"

        entry = f"【{feature_name} {var_name}】(CIViC ID: {var_id})\n"
        if link:
            entry += f"  リンク: https://civicdb.org{link}\n"
        entry += f"  エビデンス数: {ev_count}\n"
        entry += f"  関連疾患: {disease_names}\n"
        entry += f"  関連治療薬: {therapy_names}"

        results.append(entry)

    header = f"CIViC 疾患別検索結果: {len(nodes)}件表示 / フィルタ後{filtered}件 / 全{total}件\n"
    header += f"検索疾患: {disease_name}\n"
    header += "=" * 60 + "\n\n"

    return header + "\n\n".join(results)


@mcp.tool()
async def get_civic_assertions(
    gene_symbol: str = "",
    disease_name: str = "",
    assertion_type: str = ""
) -> str:
    """
    CIViCのAssertion（精査済みガイドラインレベルのエビデンス）を検索します。
    Evidence Itemより信頼性が高く、AMP/ASCOガイドラインに準拠した分類です。

    Args:
        gene_symbol: 遺伝子シンボル（例: "BRAF", "KRAS"）省略可
        disease_name: 疾患名（例: "Melanoma", "Pancreatic Cancer"）省略可
        assertion_type: アサーション種別。PREDICTIVE, PROGNOSTIC, DIAGNOSTIC, PREDISPOSING のいずれか。省略可
    """
    # browseVariants で対象のバリアントを特定してからassertionを取得
    # またはassertions直接クエリ
    filters = []
    variables = {}

    # assertionType フィルタ
    type_filter = ""
    if assertion_type:
        valid_types = ["PREDICTIVE", "PROGNOSTIC", "DIAGNOSTIC", "PREDISPOSING"]
        at_upper = assertion_type.upper()
        if at_upper in valid_types:
            type_filter = f", assertionType: {at_upper}"

    # 動的クエリ構築
    query = """
    query BrowseAssertions {
      assertions(first: 30, status: ACCEPTED""" + type_filter + """) {
        totalCount
        nodes {
          id
          name
          assertionType
          assertionDirection
          significance
          status
          ampLevel
          nccnGuidelineVersion
          fdaCompanionTest
          therapies {
            name
          }
          disease {
            name
          }
          molecularProfile {
            name
          }
          description
          phenotypes {
            name
          }
          acmgCodes {
            code
            description
          }
        }
      }
    }
    """

    data = await _graphql_query(query)

    if "error" in data:
        return f"エラー: {data['error']}"

    assertions_data = data.get("data", {}).get("assertions", {})
    nodes = assertions_data.get("nodes", [])
    total = assertions_data.get("totalCount", 0)

    if not nodes:
        return "CIViCで条件に一致するAssertionが見つかりませんでした。"

    # gene_symbol / disease_name でフィルタ
    filtered_nodes = []
    for a in nodes:
        mp_name = (a.get("molecularProfile", {}) or {}).get("name", "")
        disease = (a.get("disease", {}) or {}).get("name", "")

        if gene_symbol and gene_symbol.upper() not in mp_name.upper():
            continue
        if disease_name and disease_name.upper() not in disease.upper():
            continue
        filtered_nodes.append(a)

    if not filtered_nodes:
        search_terms = []
        if gene_symbol:
            search_terms.append(f"遺伝子={gene_symbol}")
        if disease_name:
            search_terms.append(f"疾患={disease_name}")
        if assertion_type:
            search_terms.append(f"種別={assertion_type}")
        return f"CIViCで条件（{', '.join(search_terms)}）に一致するAssertionが見つかりませんでした。取得した{total}件のうち該当なし。"

    results = []
    for a in filtered_nodes[:20]:
        a_id = a.get("id", "N/A")
        a_name = a.get("name", "N/A")
        a_type = a.get("assertionType", "N/A")
        a_direction = a.get("assertionDirection", "N/A")
        significance = a.get("significance", "N/A")
        amp_level = a.get("ampLevel", "N/A") or "N/A"
        nccn = a.get("nccnGuidelineVersion", "") or ""
        fda = a.get("fdaCompanionTest", False)
        description = (a.get("description", "") or "")[:300]

        mp_name = (a.get("molecularProfile", {}) or {}).get("name", "N/A")
        disease = (a.get("disease", {}) or {}).get("name", "N/A")

        therapies = a.get("therapies", []) or []
        therapy_names = ", ".join([t.get("name", "") for t in therapies]) if therapies else "なし"

        entry = f"【Assertion {a_id}: {a_name}】\n"
        entry += f"  分子プロファイル: {mp_name}\n"
        entry += f"  疾患: {disease}\n"
        entry += f"  種別: {a_type} | 方向: {a_direction} | 意義: {significance}\n"
        entry += f"  AMP/ASCOレベル: {amp_level}\n"
        if nccn:
            entry += f"  NCCNガイドライン: {nccn}\n"
        if fda:
            entry += f"  FDAコンパニオン診断: あり\n"
        entry += f"  治療薬: {therapy_names}\n"
        if description:
            entry += f"  概要: {description}"

        results.append(entry)

    header = f"CIViC Assertion検索結果: {len(filtered_nodes)}件\n"
    search_terms = []
    if gene_symbol:
        search_terms.append(f"遺伝子={gene_symbol}")
    if disease_name:
        search_terms.append(f"疾患={disease_name}")
    if assertion_type:
        search_terms.append(f"種別={assertion_type}")
    if search_terms:
        header += f"検索条件: {', '.join(search_terms)}\n"
    header += "=" * 60 + "\n\n"

    return header + "\n\n".join(results)


@mcp.tool()
async def get_civic_variant_detail(variant_id: int) -> str:
    """
    CIViCのバリアントIDから詳細情報を取得します。
    search_civic_variantsで得たIDを指定して使用します。

    Args:
        variant_id: CIViCのバリアントID（例: 12はBRAF V600E）
    """
    query = """
    query GetVariantDetail($id: Int!) {
      variant(id: $id) {
        id
        name
        link
        feature {
          name
          description
          link
        }
        variantAliases
        variantTypes {
          name
          description
        }
        molecularProfiles {
          totalCount
          nodes {
            id
            name
            evidenceItems(first: 50) {
              totalCount
              nodes {
                id
                status
                evidenceType
                evidenceLevel
                evidenceDirection
                significance
                therapies {
                  name
                }
                disease {
                  name
                }
                source {
                  citation
                }
                description
              }
            }
            assertions {
              totalCount
              nodes {
                id
                name
                assertionType
                significance
                ampLevel
                disease {
                  name
                }
              }
            }
          }
        }
      }
    }
    """

    data = await _graphql_query(query, {"id": variant_id})

    if "error" in data:
        return f"エラー: {data['error']}"

    variant = data.get("data", {}).get("variant")
    if not variant:
        return f"CIViCでバリアントID {variant_id} が見つかりませんでした。"

    name = variant.get("name", "N/A")
    link = variant.get("link", "")
    feature = variant.get("feature", {}) or {}
    feature_name = feature.get("name", "N/A")
    feature_desc = (feature.get("description", "") or "")[:300]

    aliases = variant.get("variantAliases", []) or []
    alias_str = ", ".join(aliases) if aliases else "なし"

    var_types = variant.get("variantTypes", []) or []
    type_str = ", ".join([vt.get("name", "") for vt in var_types]) if var_types else "N/A"

    result = f"CIViC バリアント詳細\n"
    result += "=" * 60 + "\n"
    result += f"バリアント: {feature_name} {name} (ID: {variant_id})\n"
    if link:
        result += f"リンク: https://civicdb.org{link}\n"
    result += f"別名: {alias_str}\n"
    result += f"バリアントタイプ: {type_str}\n"
    if feature_desc:
        result += f"\n【遺伝子説明】\n  {feature_desc}\n"

    # 分子プロファイル・エビデンス集計
    mp_nodes = variant.get("molecularProfiles", {}).get("nodes", [])
    mp_total = variant.get("molecularProfiles", {}).get("totalCount", 0)

    # エビデンスタイプ別集計
    ev_summary = {"PREDICTIVE": 0, "DIAGNOSTIC": 0, "PROGNOSTIC": 0, "PREDISPOSING": 0, "FUNCTIONAL": 0, "ONCOGENIC": 0}
    total_evidence = 0
    total_assertions = 0
    diseases_set = set()
    therapies_set = set()

    assertion_entries = []

    for mp in mp_nodes:
        ev_items = mp.get("evidenceItems", {}).get("nodes", [])
        for ev in ev_items:
            if ev.get("status") != "ACCEPTED":
                continue
            ev_type = ev.get("evidenceType", "OTHER")
            ev_summary[ev_type] = ev_summary.get(ev_type, 0) + 1
            total_evidence += 1

            disease = (ev.get("disease", {}) or {}).get("name", "")
            if disease:
                diseases_set.add(disease)

            for t in (ev.get("therapies", []) or []):
                tname = t.get("name", "")
                if tname:
                    therapies_set.add(tname)

        # Assertions
        a_nodes = mp.get("assertions", {}).get("nodes", [])
        total_assertions += mp.get("assertions", {}).get("totalCount", 0)
        for a in a_nodes:
            a_name = a.get("name", "N/A")
            a_type = a.get("assertionType", "N/A")
            significance = a.get("significance", "N/A")
            amp = a.get("ampLevel", "") or "N/A"
            a_disease = (a.get("disease", {}) or {}).get("name", "N/A")
            assertion_entries.append(
                f"  - {a_name} | {a_type} | {significance} | AMP: {amp} | 疾患: {a_disease}"
            )

    result += f"\n【エビデンス集計（Accepted）: {total_evidence}件】\n"
    for ev_type, count in ev_summary.items():
        if count > 0:
            result += f"  {ev_type}: {count}件\n"

    result += f"\n【関連疾患】\n  {', '.join(sorted(diseases_set)) if diseases_set else 'なし'}\n"
    result += f"\n【関連治療薬】\n  {', '.join(sorted(therapies_set)) if therapies_set else 'なし'}\n"

    if assertion_entries:
        result += f"\n【Assertions: {total_assertions}件】\n"
        result += "\n".join(assertion_entries)
    else:
        result += f"\n【Assertions: なし】"

    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
