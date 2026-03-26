from mcp.server.fastmcp import FastMCP
import httpx
import asyncio

mcp = FastMCP("ClinicalTrials")

API_BASE = "https://clinicaltrials.gov/api/v2"

# レートリミット: 50 req/min → 最低1.2秒間隔
_last_request_time = 0


async def _rate_limit():
    """APIレートリミットを守る"""
    global _last_request_time
    now = asyncio.get_event_loop().time()
    elapsed = now - _last_request_time
    if elapsed < 1.2:
        await asyncio.sleep(1.2 - elapsed)
    _last_request_time = asyncio.get_event_loop().time()


async def _get_json(url: str, params: dict = None) -> dict | str:
    """内部用: GET リクエスト"""
    await _rate_limit()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code == 429:
            return "レートリミット超過。しばらく待ってから再試行してください。"
        if resp.status_code != 200:
            return f"API Error: {resp.status_code} - {resp.text[:200]}"
        try:
            return resp.json()
        except Exception:
            return f"JSONパースエラー: {resp.text[:200]}"


def _format_status(status: str) -> str:
    """募集状況を日本語に変換"""
    status_map = {
        "RECRUITING": "募集中",
        "NOT_YET_RECRUITING": "募集開始前",
        "ACTIVE_NOT_RECRUITING": "実施中（募集終了）",
        "COMPLETED": "完了",
        "TERMINATED": "中止",
        "SUSPENDED": "一時中断",
        "WITHDRAWN": "取り下げ",
        "ENROLLING_BY_INVITATION": "招待制募集中",
        "UNKNOWN": "不明",
    }
    return status_map.get(status, status or "N/A")


def _format_phase(phases: list) -> str:
    """フェーズを日本語に変換"""
    if not phases:
        return "N/A"
    phase_map = {
        "EARLY_PHASE_1": "早期Phase 1",
        "PHASE1": "Phase 1",
        "PHASE2": "Phase 2",
        "PHASE3": "Phase 3",
        "PHASE4": "Phase 4",
        "NOT_APPLICABLE": "該当なし",
    }
    result = []
    for p in phases:
        # PHASE1, PHASE2 形式のほか、NA 形式もある
        mapped = phase_map.get(p, p)
        result.append(mapped)
    return " / ".join(result)


def _extract_japan_locations(locations: list) -> list[dict]:
    """日本の実施施設を抽出"""
    japan_sites = []
    for loc in locations:
        country = loc.get("country", "")
        if country in ("Japan", "日本"):
            japan_sites.append({
                "facility": loc.get("facility", "N/A"),
                "city": loc.get("city", ""),
                "state": loc.get("state", ""),
                "status": _format_status(loc.get("status", "")),
            })
    return japan_sites


def _format_study_summary(study: dict) -> str:
    """試験データを要約フォーマットに変換（jRCTと同等の情報）"""
    proto = study.get("protocolSection", {})
    has_results = study.get("hasResults", False)

    # 識別情報
    ident = proto.get("identificationModule", {})
    nct_id = ident.get("nctId", "N/A")
    brief_title = ident.get("briefTitle", "N/A")
    official_title = ident.get("officialTitle", "")
    acronym = ident.get("acronym", "")
    org = ident.get("organization", {})
    org_name = org.get("fullName", "N/A")

    # ステータス
    status_mod = proto.get("statusModule", {})
    overall_status = _format_status(status_mod.get("overallStatus", ""))
    start_date = status_mod.get("startDateStruct", {}).get("date", "N/A")
    completion_date = status_mod.get("completionDateStruct", {}).get("date", "N/A")
    last_update = status_mod.get("lastUpdatePostDateStruct", {}).get("date", "N/A")
    why_stopped = status_mod.get("whyStopped", "")

    # デザイン
    design = proto.get("designModule", {})
    phases = _format_phase(design.get("phases", []))
    study_type = design.get("studyType", "N/A")
    enrollment = design.get("enrollmentInfo", {})
    enroll_count = enrollment.get("count", "N/A")
    enroll_type = enrollment.get("type", "")

    # 対象疾患
    conditions_mod = proto.get("conditionsModule", {})
    conditions = conditions_mod.get("conditions", [])
    conditions_str = ", ".join(conditions) if conditions else "N/A"

    # 概要
    desc = proto.get("descriptionModule", {})
    brief_summary = desc.get("briefSummary", "")
    if len(brief_summary) > 500:
        brief_summary = brief_summary[:500] + "..."

    # 薬剤・介入
    arms_mod = proto.get("armsInterventionsModule", {})
    interventions = arms_mod.get("interventions", [])
    intervention_lines = []
    for intv in interventions:
        intv_type = intv.get("type", "")
        intv_name = intv.get("name", "")
        other_names = intv.get("otherNames", [])
        line = f"{intv_name} ({intv_type})"
        if other_names:
            line += f" [別名: {', '.join(other_names[:3])}]"
        intervention_lines.append(line)
    interventions_str = "\n    ".join(intervention_lines) if intervention_lines else "N/A"

    # 適格基準
    elig = proto.get("eligibilityModule", {})
    eligibility_criteria = elig.get("eligibilityCriteria", "N/A")
    min_age = elig.get("minimumAge", "N/A")
    max_age = elig.get("maximumAge", "N/A")
    sex = elig.get("sex", "ALL")

    # スポンサー
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
    lead_sponsor = sponsor_mod.get("leadSponsor", {})
    sponsor_name = lead_sponsor.get("name", "N/A")
    sponsor_class = lead_sponsor.get("class", "")

    # 実施施設（日本のみ抽出）
    contacts_mod = proto.get("contactsLocationsModule", {})
    locations = contacts_mod.get("locations", [])
    japan_sites = _extract_japan_locations(locations)

    # 実施国一覧
    all_countries = list(set(loc.get("country", "") for loc in locations if loc.get("country")))
    all_countries.sort()
    has_japan = any(c in ("Japan", "日本") for c in all_countries)
    total_sites = len(locations)

    # 主要評価項目
    outcomes_mod = proto.get("outcomesModule", {})
    primary_outcomes = outcomes_mod.get("primaryOutcomes", [])
    primary_str = ""
    for po in primary_outcomes[:3]:
        measure = po.get("measure", "")
        timeframe = po.get("timeFrame", "")
        primary_str += f"\n    - {measure} ({timeframe})"

    # 関連論文
    refs_mod = proto.get("referencesModule", {})
    references = refs_mod.get("references", [])
    result_refs = [r for r in references if r.get("type") == "RESULT"]
    bg_refs = [r for r in references if r.get("type") == "BACKGROUND"]

    # フォーマット
    output = f"""{'='*60}
【{nct_id}】{brief_title}
{'='*60}

■ 基本情報
  試験ID: {nct_id}
  略称: {acronym if acronym else 'なし'}
  スポンサー: {sponsor_name} ({sponsor_class})
  組織: {org_name}
  試験タイプ: {study_type}
  フェーズ: {phases}
  募集状況: {overall_status}"""

    if why_stopped:
        output += f"\n  中止理由: {why_stopped}"

    output += f"""
  登録数: {enroll_count} ({enroll_type})
  開始日: {start_date}
  完了予定: {completion_date}
  最終更新: {last_update}
  結果公開: {'あり' if has_results else 'なし'}

■ 対象疾患
  {conditions_str}

■ 介入・薬剤
    {interventions_str}

■ 日本での実施: {'あり' if has_japan else 'なし'}
  実施国数: {len(all_countries)} / 施設数: {total_sites}
  実施国: {', '.join(all_countries[:20])}"""

    if japan_sites:
        output += "\n  【日本国内施設】"
        for site in japan_sites:
            output += f"\n    - {site['facility']} ({site['city']}{site['state']}) [{site['status']}]"

    if primary_str:
        output += f"\n\n■ 主要評価項目{primary_str}"

    output += f"""

■ 適格基準
  年齢: {min_age} ～ {max_age}
  性別: {sex}

{eligibility_criteria}

■ 試験概要
{brief_summary}"""

    if result_refs:
        output += "\n\n■ 関連論文（結果）"
        for ref in result_refs[:5]:
            pmid = ref.get("pmid", "")
            citation = ref.get("citation", "")[:150]
            if pmid:
                output += f"\n  - PMID:{pmid} {citation}"
            else:
                output += f"\n  - {citation}"

    if bg_refs:
        output += "\n\n■ 関連論文（背景）"
        for ref in bg_refs[:3]:
            pmid = ref.get("pmid", "")
            citation = ref.get("citation", "")[:150]
            if pmid:
                output += f"\n  - PMID:{pmid} {citation}"

    output += f"\n\nリンク: https://clinicaltrials.gov/study/{nct_id}"

    return output


@mcp.tool()
async def get_study(nct_id: str) -> str:
    """
    NCT番号で臨床試験の詳細情報を取得します。
    jRCTで取得する情報（対象疾患、薬剤、フェーズ、適格基準、募集状況）に加え、
    実施国・日本国内施設の有無、スポンサー、主要評価項目、関連論文も取得します。

    Args:
        nct_id: NCT番号（例: "NCT07166601"）
    """
    url = f"{API_BASE}/studies/{nct_id}"
    data = await _get_json(url)
    if isinstance(data, str):
        return data

    return _format_study_summary(data)


@mcp.tool()
async def get_studies_batch(nct_ids: str) -> str:
    """
    複数のNCT番号の臨床試験情報を一括取得します。
    カンマ区切りでNCT番号を指定してください。

    Args:
        nct_ids: カンマ区切りのNCT番号（例: "NCT07166601,NCT06543655,NCT06704724"）
    """
    ids_list = [x.strip() for x in nct_ids.split(",") if x.strip()]
    if not ids_list:
        return "NCT番号が指定されていません。"
    if len(ids_list) > 20:
        return "一度に取得できるのは最大20件です。"

    url = f"{API_BASE}/studies"
    params = {
        "filter.ids": "|".join(ids_list),
        "pageSize": len(ids_list),
    }
    data = await _get_json(url, params)
    if isinstance(data, str):
        return data

    studies = data.get("studies", [])
    if not studies:
        return f"指定されたNCT番号の試験が見つかりませんでした: {', '.join(ids_list)}"

    results = []
    for study in studies:
        results.append(_format_study_summary(study))

    return f"取得結果: {len(results)}件 / 要求{len(ids_list)}件\n\n" + "\n\n".join(results)


@mcp.tool()
async def search_studies(
    condition: str = "",
    intervention: str = "",
    term: str = "",
    status: str = "RECRUITING",
    phase: str = "",
    country: str = "",
    max_results: int = 10,
) -> str:
    """
    ClinicalTrials.govで臨床試験を条件検索します。
    疾患名、薬剤名、遺伝子名などで検索できます。

    Args:
        condition: 疾患名（例: "colorectal cancer", "NSCLC"）
        intervention: 薬剤名・介入名（例: "sotorasib", "pembrolizumab"）
        term: その他の検索語（例: "KRAS G12D", "HER2"）
        status: 募集状況フィルタ（RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, NOT_YET_RECRUITING）カンマ区切りで複数指定可。空文字で全件
        phase: フェーズフィルタ（PHASE1, PHASE2, PHASE3）カンマ区切りで複数指定可
        country: 実施国フィルタ（例: "Japan"）
        max_results: 取得する最大件数（デフォルト10, 最大50）
    """
    if not condition and not intervention and not term:
        return "condition, intervention, term のいずれかを指定してください。"

    if max_results > 50:
        max_results = 50

    params = {"pageSize": max_results}

    if condition:
        params["query.cond"] = condition
    if intervention:
        params["query.intr"] = intervention
    if term:
        params["query.term"] = term
    if status:
        params["filter.overallStatus"] = status
    if country:
        params["query.locn"] = country

    # フェーズフィルタはadvancedフィルタで指定
    if phase:
        phase_filters = [f"AREA[Phase]{p.strip()}" for p in phase.split(",")]
        params["filter.advanced"] = " OR ".join(phase_filters)

    url = f"{API_BASE}/studies"
    data = await _get_json(url, params)
    if isinstance(data, str):
        return data

    total_count = data.get("totalCount", "?")
    studies = data.get("studies", [])

    if not studies:
        return "条件に一致する試験が見つかりませんでした。"

    # 検索結果はコンパクトな一覧形式
    results = []
    for study in studies:
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        nct = ident.get("nctId", "N/A")
        title = ident.get("briefTitle", "N/A")
        acronym = ident.get("acronym", "")

        status_mod = proto.get("statusModule", {})
        st = _format_status(status_mod.get("overallStatus", ""))

        design = proto.get("designModule", {})
        ph = _format_phase(design.get("phases", []))

        conditions_mod = proto.get("conditionsModule", {})
        conds = ", ".join(conditions_mod.get("conditions", [])[:3])

        arms_mod = proto.get("armsInterventionsModule", {})
        intv_names = [i.get("name", "") for i in arms_mod.get("interventions", [])]
        intv_str = ", ".join(intv_names[:3])

        sponsor = proto.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "")

        # 日本施設の有無
        locs = proto.get("contactsLocationsModule", {}).get("locations", [])
        has_japan = any(loc.get("country") in ("Japan", "日本") for loc in locs)
        japan_mark = " [日本あり]" if has_japan else ""

        entry = (
            f"【{nct}】{title}\n"
            f"  略称: {acronym}  フェーズ: {ph}  状況: {st}{japan_mark}\n"
            f"  疾患: {conds}\n"
            f"  薬剤: {intv_str}\n"
            f"  スポンサー: {sponsor}"
        )
        results.append(entry)

    header = f"検索結果: {len(results)}件表示 / 全{total_count}件\n"
    header += f"検索条件: "
    if condition:
        header += f"疾患={condition} "
    if intervention:
        header += f"薬剤={intervention} "
    if term:
        header += f"語句={term} "
    if status:
        header += f"状況={status} "
    if country:
        header += f"国={country}"
    header += "\n" + "=" * 60 + "\n\n"

    return header + "\n\n".join(results)


@mcp.tool()
async def check_japan_sites(nct_id: str) -> str:
    """
    指定した臨床試験に日本国内の実施施設があるかを確認します。
    NCTのみ（jRCT未登録）の試験で日本参加の有無を判定するのに使用します。

    Args:
        nct_id: NCT番号（例: "NCT07166601"）
    """
    url = f"{API_BASE}/studies/{nct_id}"
    params = {
        "fields": "protocolSection.identificationModule.nctId,"
                  "protocolSection.identificationModule.briefTitle,"
                  "protocolSection.statusModule.overallStatus,"
                  "protocolSection.contactsLocationsModule.locations"
    }
    data = await _get_json(url, params)
    if isinstance(data, str):
        return data

    proto = data.get("protocolSection", {})
    nct = proto.get("identificationModule", {}).get("nctId", nct_id)
    title = proto.get("identificationModule", {}).get("briefTitle", "N/A")
    status = _format_status(proto.get("statusModule", {}).get("overallStatus", ""))

    locations = proto.get("contactsLocationsModule", {}).get("locations", [])
    japan_sites = _extract_japan_locations(locations)

    all_countries = sorted(set(loc.get("country", "") for loc in locations if loc.get("country")))
    total_sites = len(locations)

    output = f"【{nct}】{title}\n"
    output += f"募集状況: {status}\n"
    output += f"実施国数: {len(all_countries)} / 施設数: {total_sites}\n"
    output += f"実施国: {', '.join(all_countries)}\n\n"

    if japan_sites:
        output += f"✓ 日本国内施設あり（{len(japan_sites)}施設）\n"
        for site in japan_sites:
            output += f"  - {site['facility']} ({site['city']}{site['state']}) [{site['status']}]\n"
    else:
        output += "✗ 日本国内施設なし\n"
        if locations:
            output += "  → 現時点で日本での参加は困難と考えられます。\n"
            output += "  → ただし、今後日本パートが追加される可能性は排除できません。\n"
        else:
            output += "  → 施設情報が未登録です。\n"

    return output


@mcp.tool()
async def get_eligibility(nct_id: str) -> str:
    """
    臨床試験の適格基準（選択基準・除外基準）を取得します。
    Step 3-cの適格性判定に使用します。

    Args:
        nct_id: NCT番号（例: "NCT07166601"）
    """
    url = f"{API_BASE}/studies/{nct_id}"
    params = {
        "fields": "protocolSection.identificationModule.nctId,"
                  "protocolSection.identificationModule.briefTitle,"
                  "protocolSection.eligibilityModule,"
                  "protocolSection.conditionsModule.conditions,"
                  "protocolSection.designModule.phases"
    }
    data = await _get_json(url, params)
    if isinstance(data, str):
        return data

    proto = data.get("protocolSection", {})
    nct = proto.get("identificationModule", {}).get("nctId", nct_id)
    title = proto.get("identificationModule", {}).get("briefTitle", "N/A")

    conditions = proto.get("conditionsModule", {}).get("conditions", [])
    phases = _format_phase(proto.get("designModule", {}).get("phases", []))

    elig = proto.get("eligibilityModule", {})
    criteria = elig.get("eligibilityCriteria", "適格基準情報なし")
    min_age = elig.get("minimumAge", "N/A")
    max_age = elig.get("maximumAge", "N/A")
    sex = elig.get("sex", "ALL")
    healthy = elig.get("healthyVolunteers", False)

    output = f"【{nct}】{title}\n"
    output += f"フェーズ: {phases}\n"
    output += f"対象疾患: {', '.join(conditions)}\n"
    output += f"年齢: {min_age} ～ {max_age}\n"
    output += f"性別: {sex}\n"
    output += f"健康ボランティア: {'受入あり' if healthy else '対象外'}\n"
    output += f"\n{'='*60}\n"
    output += f"{criteria}\n"

    return output


if __name__ == "__main__":
    mcp.run(transport="stdio")
