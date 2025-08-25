# app.py — KEPCO 신·재생e 접속진행 현황 (실시간)
# - 탭1: 접수번호 조회 (/ew/status/pwtr/initInfo, gubun=A)
# - 탭2: 고객번호 조회 (/ew/status/pwtr/initInfo, gubun=B)
# - 탭3: 접속예정 순서 조회 팝업 (/ew/status/pwtr/search)
# 업데이트:
#  - 코드값 → 한글명 자동 변환(진행단계, 공용망 보강, 팝업 코드 등)
#  - 요약 테이블 + "모든 응답 필드" (원문 + 휴먼라이즈 필드) 테이블 제공
#  - 팝업 A/B/C 단계 모두 표 출력, CSV 다운로드 (고유 key 부여)

import json
import requests
import pandas as pd
import streamlit as st
from typing import Dict, Optional, Tuple, List

API_HOST = "https://online.kepco.co.kr"

# ----------------------------- 코드 → 한글 매핑 -----------------------------
PROGRESS_MAP = {
    "01": "접수",
    "02": "연계용량 검토",
    "03": "공용망 보강",
    "04": "기술검토",
    "05": "공사설계",
    "06": "접속공사 착공",
    "07": "접속공사 준공",
}

PBLCREINFORCE_MAP = {
    "1": "변전소 보강",
    "2": "주변압기 보강",
    "3": "배전선로 신설",
}

# 팝업(dlt_stepA/B/C)에서 나올 수 있는 주요 코드
GENSOURCECD_MAP = {
    "01": "태양광", "02": "풍력", "03": "수력", "04": "연료전지", "05": "기타"
}
ACPTSTATCD_MAP = {
    "1": "정상", "2": "취소/보류"  # (공개화면 기준 추정; 필요 시 현장값에 맞게 보정)
}
PROCTPCD_MAP = {
    "1": "연계용량 검토", "2": "기술검토", "3": "공사용 설계", "4": "배전공사 시공 중",
    "5": "완료", "6": "기타"
}

# ----------------------------- 공통 유틸 -----------------------------
def _default_headers() -> Dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": API_HOST,
        "Referer": f"{API_HOST}/EWM079D00",
        "User-Agent": "Mozilla/5.0",
    }

def _post_json(path: str, body: dict, timeout: int = 12) -> dict:
    url = f"{API_HOST}{path}"
    r = requests.post(url, json=body, headers=_default_headers(), timeout=timeout)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        st.error(f"HTTP Error {r.status_code} @ {path}")
        st.code(r.text[:2000], language="json")
        raise e

    # json or HTML/XML-with-JSON
    try:
        return r.json()
    except Exception:
        text = r.text
        start = text.find("{")
        if start == -1:
            st.error("JSON 본문을 찾을 수 없습니다.")
            st.code(text[:2000])
            raise
        depth = 0
        end_idx = None
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break
        if end_idx is None:
            st.error("JSON 블록 종료를 찾을 수 없습니다.")
            st.code(text[:2000])
            raise
        return json.loads(text[start:end_idx])

def _req_initinfo_by_accept_no(acpt_no: str, timeout: int = 12) -> dict:
    payload = {"dma_initInfo": {"gubun": "A", "keynum": acpt_no.replace("-", "")}}
    return _post_json("/ew/status/pwtr/initInfo", payload, timeout)

def _req_initinfo_by_customer_no(cust_no: str, timeout: int = 12) -> dict:
    payload = {"dma_initInfo": {"gubun": "B", "keynum": cust_no}}
    return _post_json("/ew/status/pwtr/initInfo", payload, timeout)

def _req_order_popup(juris_officecd: str, acpt_no: str, timeout: int = 12) -> dict:
    payload = {"dma_param": {"jurisOfficecd": juris_officecd, "acptNo": acpt_no}}
    return _post_json("/ew/status/pwtr/search", payload, timeout)

def _extract_office_and_applcd(res: dict) -> Tuple[Optional[str], Optional[str]]:
    data = (res or {}).get("dma_initData", {}) or {}
    return data.get("JURISOFFICECD"), data.get("APPLCD")

def _mask_name(name: Optional[str]) -> str:
    if not name:
        return "-"
    if len(name) == 1:
        return name + "*"
    return name[0] + "*" + (name[2:] if len(name) > 2 else "")

# ----------------------------- 휴먼라이즈 유틸 -----------------------------
def _humanize_initinfo(d: dict) -> dict:
    """initInfo(dma_initData) dict에 (한글명) 필드 추가"""
    out = dict(d or {})
    # 진행단계
    code = (out.get("PROGRESSSTATE") or "").zfill(2) if out.get("PROGRESSSTATE") else None
    out["PROGRESSSTATE_NM"] = PROGRESS_MAP.get(code, out.get("PROGRESSSTATE") or "-")
    # 공용망 보강
    out["PBLCREINFORCE_NM"] = PBLCREINFORCE_MAP.get(out.get("PBLCREINFORCE", ""), out.get("PBLCREINFORCE") or "-")
    # 고객명 마스킹 보기용
    out["APPLNM_MASKED"] = _mask_name(out.get("APPLNM"))
    # 날짜 보기용 (YYYY.MM.DD)
    def fmt(ymd: Optional[str]) -> str:
        if not ymd or len(ymd) != 8:
            return ymd or ""
        return f"{ymd[0:4]}.{ymd[4:6]}.{ymd[6:8]}"
    for k in ("YMD01","YMD02","YMD03","YMD04","YMD05","YMD06","YMD07"):
        if k in out:
            out[f"{k}_FMT"] = fmt(out.get(k))
    return out

def _humanize_popup_row(row: dict) -> dict:
    """팝업 dlt_step* 한 행에 (한글명) 필드 추가"""
    r = dict(row or {})
    if "GENSOURCECD" in r:
        r["GENSOURCECD_NM"] = GENSOURCECD_MAP.get(str(r.get("GENSOURCECD")), r.get("GENSOURCECD"))
    if "ACPTSTATCD" in r:
        r["ACPTSTATCD_NM"] = ACPTSTATCD_MAP.get(str(r.get("ACPTSTATCD")), r.get("ACPTSTATCD"))
    if "PROCTPCD" in r:
        r["PROCTPCD_NM"] = PROCTPCD_MAP.get(str(r.get("PROCTPCD")), r.get("PROCTPCD"))
    # 고객명 마스킹 추가
    if "APPLNM" in r:
        r["APPLNM_MASKED"] = _mask_name(r.get("APPLNM"))
    # 날짜 포맷
    def fmt(ymd: Optional[str]) -> str:
        if not ymd or len(str(ymd)) not in (6,8):  # 6=YYMMDD, 8=YYYYMMDD
            return str(ymd) if ymd is not None else ""
        s = str(ymd)
        if len(s) == 8:
            return f"{s[0:4]}.{s[4:6]}.{s[6:8]}"
        return f"20{s[0:2]}.{s[2:4]}.{s[4:6]}"
    for k in ("ACPTYMD","ACPT_YMD","ENDYM","END_YM"):
        if k in r:
            r[f"{k}_FMT"] = fmt(r.get(k))
    return r

# ----------------------------- initInfo → 요약표 -----------------------------
def _table_from_initinfo(data: dict) -> pd.DataFrame:
    d = _humanize_initinfo(data)
    row = {
        "순번": 1,
        "접수번호": d.get("APPLCD") or d.get("ACPTSEQNO"),
        "발전원": d.get("GENSOURCENM"),
        "용량(kW)": d.get("EQUIPCAPA"),
        "고객명": d.get("APPLNM_MASKED"),
        "접속지사": d.get("JURISOFFICENM"),
        "상태": d.get("PROGRESSSTATE_NM"),
        "변전소": d.get("SUBSTNM"),
        "주변압기": d.get("MTRNO"),
        "배전선로": d.get("DLNM"),
        "접수구분": (d.get("GENINSTCLNM") or "").replace("고객", ""),
        "공용망보강": d.get("PBLCREINFORCE_NM"),
    }
    return pd.DataFrame([row])

def _all_fields_table_from_dict(d: dict, title: str = "모든 응답 필드") -> pd.DataFrame:
    """dict 전체를 '필드 | 값' 목록 테이블로 변환 (가독성 좋음)"""
    if not d:
        return pd.DataFrame(columns=["필드","값"])
    series = pd.Series(d, dtype="object").rename("값")
    df = series.reset_index().rename(columns={"index":"필드"})
    return df

# ----------------------------- 팝업 A/B/C → 표 -----------------------------
def _normalize_popup_rows(rows: List[dict]) -> pd.DataFrame:
    # 원문 + 휴먼라이즈 필드 추가
    rows2 = [_humanize_popup_row(r) for r in (rows or [])]
    df_raw = pd.DataFrame(rows2)
    if df_raw.empty:
        return df_raw

    # 요약용 컬럼 세트
    rename = {
        "ACPTSEQNO": "접수번호",
        "GENSOURCENM": "발전원",
        "EQUIPCAPA": "용량(kW)",
        "APPLNM_MASKED": "고객명",
        "JURISOFFICENM": "접속지사",
        "PROCTPNM": "상태",
        "SUBSTNM": "변전소",
        "MTRNO": "주변압기",
        "DLNM": "배전선로",
    }
    df_view = df_raw.rename(columns=rename)
    # 순번 부여
    df_view.insert(0, "순번", range(1, len(df_view)+1))
    # 최종 컬럼 순서(있을 때만)
    cols = ["순번","접수번호","발전원","용량(kW)","고객명","접속지사","상태","변전소","주변압기","배전선로"]
    df_view = df_view[[c for c in cols if c in df_view.columns]]
    # 원문 전체도 함께 반환하기 위해 두 개를 리턴하는 대신,
    # 호출부에서 df_raw를 별도로 사용하도록 한다.
    df_view._df_raw_full = df_raw  # 속성에 원문(휴먼필드 포함) 보관
    return df_view

def _table_from_popup_all_steps(res: dict) -> Dict[str, pd.DataFrame]:
    out = {}
    for step_key, label in [("dlt_stepA", "A"), ("dlt_stepB", "B"), ("dlt_stepC", "C")]:
        df = _normalize_popup_rows(res.get(step_key, []))
        out[label] = df
    return out

def _prefer_step(df_map: Dict[str, pd.DataFrame]) -> Tuple[str, pd.DataFrame]:
    for k in ("B", "C", "A"):
        df = df_map.get(k)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return k, df
    return "B", pd.DataFrame()

# ----------------------------- 다운로드 버튼 (고유 key) -----------------------------
def _download_btn(df: pd.DataFrame, filename: str, key: str):
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("CSV 다운로드", data=csv, file_name=filename, mime="text/csv", key=key)

# ----------------------------- 탭 구현 -----------------------------
def tab_accept_no():
    st.subheader("① 접수번호 조회 (EWM080D00)")
    acpt_no = st.text_input("접수번호 (예: 5782-20240708-010074)", value="5782-20240708-010074")

    if st.button("조회", type="primary", key="btn_1"):
        try:
            res = _req_initinfo_by_accept_no(acpt_no)
            data = res.get("dma_initData", {}) or {}
            if not data:
                st.warning("조회된 데이터가 없습니다.")
                return

            # 요약 테이블 (휴먼라이즈 포함)
            df_info = _table_from_initinfo(data)
            st.table(df_info)
            _download_btn(df_info, "접수번호_조회_요약.csv", key="dl_initinfo_accept")

            # 모든 응답 필드 (원문 + 휴먼라이즈 필드)
            human = _humanize_initinfo(data)
            df_all = _all_fields_table_from_dict(human)
            with st.expander("모든 응답 필드 보기 (원문 + 한글명/포맷 필드 포함)", expanded=False):
                st.dataframe(df_all, use_container_width=True)
                _download_btn(df_all, "접수번호_모든필드.csv", key="dl_all_accept")

            # 팝업 원클릭
            juris_cd, applcd = _extract_office_and_applcd(res)
            if juris_cd and applcd:
                st.success(f"관할지사코드: {juris_cd}  |  팝업용 번호(APPLCD): {applcd}")
                if st.button("이 값으로 ‘③ 접속예정 순서’ 호출", key="jump_1"):
                    pop = _req_order_popup(juris_cd, applcd)
                    _render_popup_all(pop)
            else:
                st.info("응답에 JURISOFFICECD/APPLCD가 없어 팝업 호출을 생략합니다.")

            with st.expander("원본 응답(JSON) 보기", expanded=False):
                st.json(res)

        except Exception as e:
            st.exception(e)

def tab_customer_no():
    st.subheader("② 고객번호 조회 (EWM079D00)")
    cust_no = st.text_input("고객번호 (숫자만)", value="0931423032")

    if st.button("조회", type="primary", key="btn_2"):
        try:
            res = _req_initinfo_by_customer_no(cust_no)
            data = res.get("dma_initData", {}) or {}
            if not data:
                st.warning("조회된 데이터가 없습니다.")
                return

            df_info = _table_from_initinfo(data)
            st.table(df_info)
            _download_btn(df_info, "고객번호_조회_요약.csv", key="dl_initinfo_customer")

            human = _humanize_initinfo(data)
            df_all = _all_fields_table_from_dict(human)
            with st.expander("모든 응답 필드 보기 (원문 + 한글명/포맷 필드 포함)", expanded=False):
                st.dataframe(df_all, use_container_width=True)
                _download_btn(df_all, "고객번호_모든필드.csv", key="dl_all_customer")

            juris_cd, applcd = _extract_office_and_applcd(res)
            if juris_cd and applcd:
                st.success(f"관할지사코드: {juris_cd}  |  팝업용 번호(APPLCD): {applcd}")
                if st.button("이 값으로 ‘③ 접속예정 순서’ 호출", key="jump_2"):
                    pop = _req_order_popup(juris_cd, applcd)
                    _render_popup_all(pop)
            else:
                st.info("응답에 JURISOFFICECD/APPLCD가 없어 팝업 호출을 생략합니다.")

            with st.expander("원본 응답(JSON) 보기", expanded=False):
                st.json(res)

        except Exception as e:
            st.exception(e)

def _render_popup_all(pop: dict):
    # 카운터
    col1, col2, col3 = st.columns(3)
    col1.metric("A단계", pop.get("cnt_stepA", 0))
    col2.metric("B단계", pop.get("cnt_stepB", 0))
    col3.metric("C단계", pop.get("cnt_stepC", 0))

    # 단계별 표 (요약)
    tables = _table_from_popup_all_steps(pop)
    pref_key, pref_df = _prefer_step(tables)

    st.subheader(f"기본 목록 (단계 {pref_key})")
    if pref_df.empty:
        st.warning("표시할 데이터가 없습니다.")
    else:
        st.dataframe(pref_df, use_container_width=True)
        _download_btn(pref_df, f"접속예정순서_단계{pref_key}.csv", key=f"dl_{pref_key}_main")

    # 모든 단계 + 모든 필드(원문+휴먼)도 제공
    with st.expander("모든 단계 보기 (A/B/C) — 요약 목록", expanded=False):
        for label in ("A", "B", "C"):
            df = tables.get(label, pd.DataFrame())
            st.markdown(f"**단계 {label}**")
            if df.empty:
                st.info("데이터 없음")
            else:
                st.dataframe(df, use_container_width=True)
                _download_btn(df, f"접속예정순서_단계{label}.csv", key=f"dl_{label}_expander")

    with st.expander("모든 단계 — 모든 응답 필드(원문 + 한글명/포맷 필드 포함)", expanded=False):
        for label in ("A", "B", "C"):
            df = tables.get(label, pd.DataFrame())
            st.markdown(f"**단계 {label} (모든 필드)**")
            if df.empty:
                st.info("데이터 없음")
            else:
                # _normalize_popup_rows에서 보관해 둔 원문+휴먼 필드 전체 DataFrame 사용
                df_raw = getattr(df, "_df_raw_full", pd.DataFrame())
                if df_raw.empty:
                    st.info("원문 전체 필드가 없습니다.")
                else:
                    st.dataframe(df_raw, use_container_width=True)
                    _download_btn(df_raw, f"접속예정순서_단계{label}_모든필드.csv", key=f"dl_{label}_raw")

    with st.expander("원본 응답(JSON) 보기", expanded=False):
        st.json(pop)

def tab_order_popup():
    st.subheader("③ 접속예정 순서 조회 (EWM082D00 팝업)")
    c1, c2 = st.columns(2)
    with c1:
        juris = st.text_input("관할지사코드 (JURISOFFICECD)", value="4910")
    with c2:
        acpt = st.text_input("고객번호(CUSTNO) 또는 APPLCD", value="1229664010",
                              help="initInfo의 APPLCD를 그대로 넣어도 됩니다.")

    if st.button("조회", type="primary", key="btn_3"):
        try:
            pop = _req_order_popup(juris, acpt)
            _render_popup_all(pop)
        except Exception as e:
            st.exception(e)

# ----------------------------- 메인 -----------------------------
def main():
    st.set_page_config(page_title="KEPCO 신·재생e 통합 조회(실시간)", layout="wide")
    st.title("⚡ KEPCO 신·재생e 접속진행 현황 (실시간 호출 전용)")
    st.caption("WebSquare 공개 화면 연동 — 비공식 개인 프로젝트")

    tab1, tab2, tab3 = st.tabs(["접수번호 조회", "고객번호 조회", "접속예정 순서 조회"])
    with tab1:
        tab_accept_no()
    with tab2:
        tab_customer_no()
    with tab3:
        tab_order_popup()

if __name__ == "__main__":
    main()
