# app.py  — KEPCO 신·재생e 접속진행 현황 뷰어 (실시간 호출 전용)
# 탭1: 접수번호 조회 (EWM080D00 흐름 → /ew/status/pwtr/initInfo)
# 탭2: 고객번호 조회 (EWM079D00과 동일 흐름)
# 탭3: 접속예정 순서 조회 (팝업 EWM082D00 → /ew/status/pwtr/search)
#
# 변경점
#  - 시뮬레이션/업로드/토글 제거 → 항상 실시간 API 호출
#  - 각 탭 결과를 목록(테이블) 형태로 표시
#  - 탭1/2에서 initInfo 응답으로부터 JURISOFFICECD/APPLCD 자동 추출
#    → 버튼 1번으로 ‘접속예정 순서’ API를 바로 호출 가능

import json
import requests
import pandas as pd
import streamlit as st
from typing import Dict, Optional, Tuple

API_HOST = "https://online.kepco.co.kr"


# ----------------------------- 공통 유틸 -----------------------------
def _default_headers() -> Dict[str, str]:
    # 서버사이드 호출이므로 CORS 영향은 없지만, 원 서비스와 유사한 헤더를 사용
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
    # 실패 시 상세 확인을 돕기 위해 본문을 그대로 보여준다
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        st.error(f"HTTP Error {r.status_code} @ {path}")
        st.code(r.text[:2000], language="json")
        raise e
    # 일부 응답은 text/json 혼재 가능 → json() 시도 후 실패하면 수동 파싱
    try:
        return r.json()
    except Exception:
        # HTML/XML 안 JSON이 포함된 특이 포맷 대응(첫 { .. }만 파싱)
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
    # gubun=A : 접수번호, 하이픈 제거
    payload = {"dma_initInfo": {"gubun": "A", "keynum": acpt_no.replace("-", "")}}
    return _post_json("/ew/status/pwtr/initInfo", payload, timeout)


def _req_initinfo_by_customer_no(cust_no: str, timeout: int = 12) -> dict:
    # gubun=B : 고객번호
    payload = {"dma_initInfo": {"gubun": "B", "keynum": cust_no}}
    return _post_json("/ew/status/pwtr/initInfo", payload, timeout)


def _req_order_popup(juris_officecd: str, acpt_no: str, timeout: int = 12) -> dict:
    # 접속예정 순서 팝업 API
    payload = {"dma_param": {"jurisOfficecd": juris_officecd, "acptNo": acpt_no}}
    return _post_json("/ew/status/pwtr/search", payload, timeout)


def _extract_office_and_applcd(res: dict) -> Tuple[Optional[str], Optional[str]]:
    data = (res or {}).get("dma_initData", {}) or {}
    return data.get("JURISOFFICECD"), data.get("APPLCD")


def _progress_label(code: Optional[str]) -> str:
    # 한전 화면 단계와 매칭(대략)
    mapping = {
        "01": "접수",
        "02": "연계용량 검토",
        "03": "공용망 보강",
        "04": "기술검토",
        "05": "공사설계",
        "06": "접속공사 착공",
        "07": "접속공사 준공",
    }
    return mapping.get((code or "").zfill(2), code or "-")


def _mask_name(name: Optional[str]) -> str:
    if not name:
        return "-"
    if len(name) == 1:
        return name + "*"
    return name[0] + "*" + (name[2:] if len(name) > 2 else "")


# ----------------------------- 테이블 포맷 -----------------------------
def _table_from_initinfo(data: dict, seq: int = 1) -> pd.DataFrame:
    """initInfo(dma_initData) → 단일 행 테이블"""
    row = {
        "순번": seq,
        "접수번호": data.get("APPLCD") or data.get("ACPTSEQNO"),
        "발전원": data.get("GENSOURCENM"),
        "용량(kW)": data.get("EQUIPCAPA"),
        "고객명": data.get("APPLNM"),
        "접속지사": data.get("JURISOFFICENM"),
        "상태": _progress_label(data.get("PROGRESSSTATE")),
        "접수구분": (data.get("GENINSTCLNM") or "").replace("고객", ""),
        "변전소": data.get("SUBSTNM"),
        "주변압기": data.get("MTRNO"),
        "배전선로": data.get("DLNM"),
        "본부": data.get("UPPOOFFICENM"),
        "본부코드": data.get("UPPOOFFICECD"),
        "지사코드": data.get("JURISOFFICECD"),
        "지사연락처": data.get("JURISOFFICETEL"),
        "공용망보강": data.get("PBLCREINFORCE"),
        # 단계별 일자(있으면)
        "YMD01(접수)": data.get("YMD01"),
        "YMD02(연계용량검토)": data.get("YMD02"),
        "YMD03(공용망보강)": data.get("YMD03"),
        "YMD04(기술검토)": data.get("YMD04"),
        "YMD05(공사설계)": data.get("YMD05"),
        "YMD06(착공)": data.get("YMD06"),
        "YMD07(준공)": data.get("YMD07"),
    }
    # 마스킹
    row["고객명"] = _mask_name(row["고객명"])
    return pd.DataFrame([row])


def _table_from_popup(res: dict) -> pd.DataFrame:
    """팝업 응답의 단계 B(dlt_stepB)를 기본 목록으로 표시(가장 많이 보는 탭)"""
    df = pd.DataFrame(res.get("dlt_stepB", []))
    if df.empty:
        return df
    df = df.assign(순번=(df.index + 1))
    # 표시 컬럼 맵
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
    # 마스킹
    if "고객명" in df.columns:
        df["고객명"] = df["고객명"].map(_mask_name)
    # 최종 컬럼 순서
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
    return df[[c for c in cols if c in df.columns]]


# ----------------------------- 탭 구현 -----------------------------
def tab_accept_no():
    st.subheader("① 접수번호 조회 (EWM080D00)")
    acpt_no = st.text_input("접수번호 (예: 5782-20240708-010074)", value="5782-20240708-010074")
    if st.button("조회", type="primary", use_container_width=False, key="btn_1"):
        try:
            res = _req_initinfo_by_accept_no(acpt_no)
            rs = res.get("rsMsg", {})
            st.caption(f"상태: {rs.get('statusCode','-')}")
            data = res.get("dma_initData", {}) or {}
            if not data:
                st.warning("조회된 데이터가 없습니다.")
                return

            # 목록 테이블 출력
            st.table(_table_from_initinfo(data))

            # JSON 전문(접기)
            with st.expander("원본 응답(JSON) 보기", expanded=False):
                st.json(res)

            # 바로 ‘접속예정 순서’ 조회
            juris_cd, applcd = _extract_office_and_applcd(res)
            if juris_cd and applcd:
                st.success(f"관할지사코드: {juris_cd}  |  팝업용 번호(APPLCD): {applcd}")
                if st.button("이 값으로 ‘③ 접속예정 순서’ 호출", key="jump_1"):
                    pop = _req_order_popup(juris_cd, applcd)
                    st.session_state["_last_popup_result"] = pop
                    st.info("아래에 팝업 결과 목록을 표시합니다.")
                    df = _table_from_popup(pop)
                    if df.empty:
                        st.warning("단계 B 결과가 없습니다.")
                    else:
                        st.dataframe(df, use_container_width=True)
            else:
                st.warning("응답에서 JURISOFFICECD/APPLCD를 찾지 못해 팝업 호출을 생략합니다.")

        except Exception as e:
            st.exception(e)


def tab_customer_no():
    st.subheader("② 고객번호 조회 (EWM079D00)")
    cust_no = st.text_input("고객번호 (숫자만)", value="0931423032")
    if st.button("조회", type="primary", key="btn_2"):
        try:
            res = _req_initinfo_by_customer_no(cust_no)
            rs = res.get("rsMsg", {})
            st.caption(f"상태: {rs.get('statusCode','-')}")
            data = res.get("dma_initData", {}) or {}
            if not data:
                st.warning("조회된 데이터가 없습니다.")
                return

            # 목록 테이블 출력
            st.table(_table_from_initinfo(data))

            # JSON 전문(접기)
            with st.expander("원본 응답(JSON) 보기", expanded=False):
                st.json(res)

            # 바로 ‘접속예정 순서’ 조회
            juris_cd, applcd = _extract_office_and_applcd(res)
            if juris_cd and applcd:
                st.success(f"관할지사코드: {juris_cd}  |  팝업용 번호(APPLCD): {applcd}")
                if st.button("이 값으로 ‘③ 접속예정 순서’ 호출", key="jump_2"):
                    pop = _req_order_popup(juris_cd, applcd)
                    st.session_state["_last_popup_result"] = pop
                    st.info("아래에 팝업 결과 목록을 표시합니다.")
                    df = _table_from_popup(pop)
                    if df.empty:
                        st.warning("단계 B 결과가 없습니다.")
                    else:
                        st.dataframe(df, use_container_width=True)
            else:
                st.warning("응답에서 JURISOFFICECD/APPLCD를 찾지 못해 팝업 호출을 생략합니다.")

        except Exception as e:
            st.exception(e)


def tab_order_popup():
    st.subheader("③ 접속예정 순서 조회 (EWM082D00 팝업)")
    c1, c2 = st.columns(2)
    with c1:
        juris = st.text_input("관할지사코드 (JURISOFFICECD)", value="5782")
    with c2:
        acpt = st.text_input("고객번호(CUSTNO) 또는 APPLCD", value="0931423032")

    if st.button("조회", type="primary", key="btn_3"):
        try:
            res = _req_order_popup(juris, acpt)
            # 요약
            col1, col2, col3 = st.columns(3)
            col1.metric("A단계", res.get("cnt_stepA", 0))
            col2.metric("B단계", res.get("cnt_stepB", 0))
            col3.metric("C단계", res.get("cnt_stepC", 0))

            df = _table_from_popup(res)
            if df.empty:
                st.warning("단계 B 결과가 없습니다.")
            else:
                st.dataframe(df, use_container_width=True)

            with st.expander("원본 응답(JSON) 보기", expanded=False):
                st.json(res)

        except Exception as e:
            st.exception(e)


# ----------------------------- 메인 -----------------------------
def main():
    st.set_page_config(page_title="KEPCO 신·재생e 통합 조회(실시간)", layout="wide")
    st.title("⚡ KEPCO 신·재생e 접속진행 현황 (실시간 호출 전용)")
    st.caption("KEPCO WebSquare API 기반 — 비공식 개인 프로젝트")

    with st.expander("안내", expanded=False):
        st.markdown(
            "- 본 앱은 **실시간으로 KEPCO 서버에 POST** 요청을 보냅니다.\n"
            "- 네트워크/방화벽/쿠키/접속 정책 변경 시 호출이 실패할 수 있습니다.\n"
            "- 개인 정보 보호를 위해 고객명은 화면에서 마스킹 처리합니다.\n"
        )

    tab1, tab2, tab3 = st.tabs(["접수번호 조회", "고객번호 조회", "접속예정 순서 조회"])
    with tab1:
        tab_accept_no()
    with tab2:
        tab_customer_no()
    with tab3:
        tab_order_popup()


if __name__ == "__main__":
    main()
