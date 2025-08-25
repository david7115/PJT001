# app.py — KEPCO 신·재생e 접속진행 현황 (실시간 전용, 단계 A/B/C 표 출력)
# 탭1: 접수번호 조회 (/ew/status/pwtr/initInfo, gubun=A)
# 탭2: 고객번호 조회 (/ew/status/pwtr/initInfo, gubun=B)
# 탭3: 접속예정 순서 조회 팝업 (/ew/status/pwtr/search)
# 포인트:
#  - initInfo 응답에서 JURISOFFICECD/APPLCD 추출하여 탭3 API를 원클릭 호출
#  - 팝업 응답의 dlt_stepA/B/C 모두 표로 출력(B 없고 C만 있는 경우도 OK)
#  - 목록 기본 컬럼: 순번 | 접수번호 | 발전원 | 용량(kW) | 고객명 | 접속지사 | 상태 | (변전소/주변압기/배전선로)
#  - 다운로드 버튼에 고유 key 부여(중복 ID 오류 해결)

import json
import requests
import pandas as pd
import streamlit as st
from typing import Dict, Optional, Tuple, List

API_HOST = "https://online.kepco.co.kr"


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


def _progress_label(code: Optional[str]) -> str:
    mapping = {
        "01": "접수",
        "02": "연계용량 검토",
        "03": "공용망 보강",
        "04": "기술검토",
        "05": "공사설계",
        "06": "접속공사 착공",
        "07": "접속공사 준공",
    }
    z = (code or "").zfill(2)
    return mapping.get(z, code or "-")


def _mask_name(name: Optional[str]) -> str:
    if not name:
        return "-"
    if len(name) == 1:
        return name + "*"
    return name[0] + "*" + (name[2:] if len(name) > 2 else "")


# ----------------------------- initInfo → 표 -----------------------------
def _table_from_initinfo(data: dict, seq: int = 1) -> pd.DataFrame:
    row = {
        "순번": seq,
        "접수번호": data.get("APPLCD") or data.get("ACPTSEQNO"),
        "발전원": data.get("GENSOURCENM"),
        "용량(kW)": data.get("EQUIPCAPA"),
        "고객명": _mask_name(data.get("APPLNM")),
        "접속지사": data.get("JURISOFFICENM"),
        "상태": _progress_label(data.get("PROGRESSSTATE")),
        "변전소": data.get("SUBSTNM"),
        "주변압기": data.get("MTRNO"),
        "배전선로": data.get("DLNM"),
        "접수구분": (data.get("GENINSTCLNM") or "").replace("고객", ""),
        "본부": data.get("UPPOOFFICENM"),
        "본부코드": data.get("UPPOOFFICECD"),
        "지사코드": data.get("JURISOFFICECD"),
        "지사연락처": data.get("JURISOFFICETEL"),
        "공용망보강": data.get("PBLCREINFORCE"),
        "YMD01(접수)": data.get("YMD01"),
        "YMD02(연계용량검토)": data.get("YMD02"),
        "YMD03(공용망보강)": data.get("YMD03"),
        "YMD04(기술검토)": data.get("YMD04"),
        "YMD05(공사설계)": data.get("YMD05"),
        "YMD06(착공)": data.get("YMD06"),
        "YMD07(준공)": data.get("YMD07"),
    }
    cols = ["순번", "접수번호", "발전원", "용량(kW)", "고객명", "접속지사", "상태", "변전소", "주변압기", "배전선로"]
    df = pd.DataFrame([row])
    return df[[c for c in cols if c in df.columns]]


# ----------------------------- 팝업 A/B/C → 표 -----------------------------
def _normalize_popup_rows(rows: List[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    rename = {
        "ACPTSEQNO": "접수번호",
        "GENSOURCENM": "발전원",
        "EQUIPCAPA": "용량(kW)",
        "APPLNM": "고객명",
        "JURISOFFICENM": "접속지사",
        "PROCTPNM": "상태",
        "SUBSTNM": "변전소",
        "MTRNO": "주변압기",
        "DLNM": "배전선로",
    }
    df = df.rename(columns=rename)
    if "고객명" in df.columns:
        df["고객명"] = df["고객명"].map(_mask_name)
    return df


def _table_from_popup_all_steps(res: dict) -> Dict[str, pd.DataFrame]:
    out = {}
    for step_key, label in [("dlt_stepA", "A"), ("dlt_stepB", "B"), ("dlt_stepC", "C")]:
        df = _normalize_popup_rows(res.get(step_key, []))
        if not df.empty:
            df = df.assign(순번=(df.index + 1))
            cols = [
                "순번",
                "접수번호",
                "발전원",
                "용량(kW)",
                "고객명",
                "접속지사",
                "상태",
                "변전소",
                "주변압기",
                "배전선로",
            ]
            df = df[[c for c in cols if c in df.columns]]
        out[label] = df
    return out


def _prefer_step(df_map: Dict[str, pd.DataFrame]) -> Tuple[str, pd.DataFrame]:
    for k in ("B", "C", "A"):
        if k in df_map and not df_map[k].empty:
            return k, df_map[k]
    return "B", pd.DataFrame()


# ----------------------------- 다운로드 버튼 (고유 key 부여) -----------------------------
def _download_btn(df: pd.DataFrame, filename: str, key: str):
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "CSV 다운로드",
        data=csv,
        file_name=filename,
        mime="text/csv",
        key=key
    )


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

            df_info = _table_from_initinfo(data)
            st.table(df_info)
            _download_btn(df_info, "접수번호_조회_요약.csv", key="dl_initinfo_accept")

            with st.expander("원본 응답(JSON) 보기", expanded=False):
                st.json(res)

            juris_cd, applcd = _extract_office_and_applcd(res)
            if juris_cd and applcd:
                st.success(f"관할지사코드: {juris_cd}  |  팝업용 번호(APPLCD): {applcd}")
                if st.button("이 값으로 ‘③ 접속예정 순서’ 호출", key="jump_1"):
                    pop = _req_order_popup(juris_cd, applcd)
                    _render_popup_all(pop)
            else:
                st.info("응답에 JURISOFFICECD/APPLCD가 없어 팝업 호출을 생략합니다.")

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

            with st.expander("원본 응답(JSON) 보기", expanded=False):
                st.json(res)

            juris_cd, applcd = _extract_office_and_applcd(res)
            if juris_cd and applcd:
                st.success(f"관할지사코드: {juris_cd}  |  팝업용 번호(APPLCD): {applcd}")
                if st.button("이 값으로 ‘③ 접속예정 순서’ 호출", key="jump_2"):
                    pop = _req_order_popup(juris_cd, applcd)
                    _render_popup_all(pop)
            else:
                st.info("응답에 JURISOFFICECD/APPLCD가 없어 팝업 호출을 생략합니다.")

        except Exception as e:
            st.exception(e)


def _render_popup_all(pop: dict):
    # 상단 카운터
    col1, col2, col3 = st.columns(3)
    col1.metric("A단계", pop.get("cnt_stepA", 0))
    col2.metric("B단계", pop.get("cnt_stepB", 0))
    col3.metric("C단계", pop.get("cnt_stepC", 0))

    # 단계별 표
    tables = _table_from_popup_all_steps(pop)
    pref_key, pref_df = _prefer_step(tables)

    st.subheader(f"기본 목록 (단계 {pref_key})")
    if pref_df.empty:
        st.warning("표시할 데이터가 없습니다.")
    else:
        st.dataframe(pref_df, use_container_width=True)
        _download_btn(pref_df, f"접속예정순서_단계{pref_key}.csv", key=f"dl_{pref_key}_main")

    with st.expander("모든 단계 보기 (A/B/C)", expanded=False):
        for label in ("A", "B", "C"):
            df = tables.get(label, pd.DataFrame())
            st.markdown(f"**단계 {label}**")
            if df.empty:
                st.info("데이터 없음")
            else:
                st.dataframe(df, use_container_width=True)
                _download_btn(df, f"접속예정순서_단계{label}.csv", key=f"dl_{label}_expander")

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
