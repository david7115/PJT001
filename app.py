# app.py  (KEPCO 신·재생e 접속진행 현황 통합 뷰어 · 수정 통합본)
# - 탭1: 접수번호 조회 (EWM080D00 흐름)
# - 탭2: 고객번호 조회 (EWM079D00의 '고객번호' 탭과 동일 구조)
# - 탭3: 접속예정 순서 조회 (팝업 EWM082D00 + /ew/status/pwtr/search)
# 기능 보강
#   * initInfo 응답에서 JURISOFFICECD/APPLCD 자동 추출
#   * 탭1/2에서 원클릭으로 탭3 API 호출
#   * 탭3 입력값 자동 프리필
#   * 시뮬레이션 파일 미업로드시 샘플 파일 자동 사용(옵션)

import os
import json
import pandas as pd
import requests
import streamlit as st
from typing import Dict, Tuple, Optional

# ====== 설정 ======
API_HOST = "https://online.kepco.co.kr"

# (선택) 샘플 파일 기본 경로 (있으면 자동 사용)
SAMPLE_EWM080 = "sample/EWM080D00_sample.txt"   # 접수번호 조회(initInfo) 샘플
SAMPLE_EWM079 = "sample/EWM079D00_sample.txt"   # 고객번호 조회(initInfo) 샘플
SAMPLE_ORDER  = "sample/접속순서_자료.txt"        # 접속예정 순서 팝업 응답 샘플

# ====== 공통 유틸 ======
def _default_headers() -> Dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": API_HOST,
        "Referer": f"{API_HOST}/EWM079D00",
        "User-Agent": "Mozilla/5.0",
    }

def _req_json_post(path: str, payload: dict, timeout: int = 12) -> dict:
    url = f"{API_HOST}{path}"
    r = requests.post(url, headers=_default_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _req_websquare_initinfo(keynum: str, gubun: str = "A", timeout: int = 12) -> dict:
    """
    /ew/status/pwtr/initInfo : WebSquare submission ‘sbm_init’
    gubun = "A"(접수번호) | "B"(고객번호)
    """
    url = f"{API_HOST}/ew/status/pwtr/initInfo"
    if gubun == "A":
        payload = {"dma_initInfo": {"gubun": "A", "keynum": keynum.replace("-", "")}}
    else:
        payload = {"dma_initInfo": {"gubun": "B", "keynum": keynum}}
    r = requests.post(url, headers=_default_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _req_websquare_comp(acpt_no: str, timeout: int = 12) -> dict:
    """
    /ew/status/pwtr/comp : 공사예정일 조회
    """
    url = f"{API_HOST}/ew/status/pwtr/comp"
    payload = {"dma_comp": {"keynum": acpt_no}}
    r = requests.post(url, headers=_default_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _req_popup_order_search(juris_officecd: str, acpt_no: str, timeout: int = 12) -> dict:
    """
    /ew/status/pwtr/search : 접속예정 순서 조회 팝업 호출
    body: {"dma_param":{"jurisOfficecd":"5782","acptNo":"0931423032"}}
    """
    return _req_json_post(
        "/ew/status/pwtr/search",
        {"dma_param": {"jurisOfficecd": juris_officecd, "acptNo": acpt_no}},
        timeout=timeout,
    )

def _try_parse_concat_json(text: str) -> dict:
    """
    HTML/XML 안에 JSON이 통째로 들어있는 형태 대비:
    첫 '{'부터 균형 맞는 '}'까지 추출하여 로드
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("JSON 시작 기호 '{' 를 찾지 못했습니다.")
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
        raise ValueError("JSON 종료 '}' 를 찾지 못했습니다.")
    return json.loads(text[start:end_idx])

def _read_sim_text(uploaded_file, fallback_path: str) -> str:
    """
    업로드 파일이 있으면 사용, 없으면 fallback 경로의 샘플 사용.
    둘 다 없으면 에러를 올려 상단 경고로 안내.
    """
    if uploaded_file is not None:
        return uploaded_file.read().decode("utf-8", errors="ignore")
    if fallback_path and os.path.exists(fallback_path):
        return open(fallback_path, "r", encoding="utf-8").read()
    raise FileNotFoundError("시뮬레이션 파일이 필요합니다. 업로드하거나 ‘실시간 호출’을 켜주세요.")

def _extract_office_and_acpt_from_init(res: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    initInfo 응답에서 팝업 검색에 필요한 값 추출
    - JURISOFFICECD : 관할지사코드
    - APPLCD        : 팝업 /ew/status/pwtr/search 의 acptNo 로 사용
    """
    data = (res or {}).get("dma_initData", {}) or {}
    return data.get("JURISOFFICECD"), data.get("APPLCD")

def _mask_name(name: Optional[str]) -> str:
    if not name:
        return "-"
    if len(name) == 1:
        return name + "*"
    return name[0] + "*" + (name[2:] if len(name) > 2 else "")

def _info_box():
    st.info(
        "본 앱은 KEPCO 공개 웹 화면(WebSquare) 기반 **비공식 데모**입니다. "
        "실서비스 변경 시 응답 스키마가 달라질 수 있습니다."
    )

# ====== 탭1: 접수번호 조회 ======
def page_by_accept_no():
    st.subheader("접수번호 조회 (EWM080D00)")

    c1, c2 = st.columns([2,1])
    with c1:
        acpt_no = st.text_input("접수번호 (예: 5782-20240708-010074)", value="5782-20240708-010074")
    with c2:
        run_live = st.toggle("실시간 호출", value=False)

    sim_file = st.file_uploader("시뮬레이션 파일(JSON/txt - initInfo 응답 원문)", type=["json","txt"], key="sim080")

    if st.button("조회", key="btn080"):
        try:
            if run_live:
                res = _req_websquare_initinfo(acpt_no, gubun="A")
            else:
                text = _read_sim_text(sim_file, SAMPLE_EWM080)
                res = _try_parse_concat_json(text)

            st.session_state["_last_initinfo_cache"] = res  # 탭3 프리필용 캐시
            rs = res.get("rsMsg", {})
            st.write("상태:", rs.get("statusCode", "-"))

            data = res.get("dma_initData", {})
            if not data:
                st.warning("조회된 데이터가 없습니다.")
                return

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("고객명", data.get("APPLNM","-"))
            k2.metric("발전용량", f"{data.get('EQUIPCAPA','-')} kW")
            k3.metric("접수구분", (data.get("GENINSTCLNM","") or "").replace("고객",""))
            k4.metric("담당부서", f"{data.get('UPPOOFFICENM','')}/{data.get('JURISOFFICENM','')}")

            st.caption("원본 응답(JSON)")
            with st.expander("펼쳐보기", expanded=False):
                st.json(res)

            # 자동 추출 → 원클릭 ‘접속예정 순서 조회’
            juris_cd, pop_acpt = _extract_office_and_acpt_from_init(res)
            if juris_cd and pop_acpt:
                st.success(f"관할지사코드: {juris_cd}  |  팝업 acptNo: {pop_acpt}")
                if st.button("이 값으로 ‘접속예정 순서’ 바로 조회", key="jump_from_tab1"):
                    pop = _req_popup_order_search(juris_cd, pop_acpt)
                    st.session_state["_last_popup_result"] = pop
                    st.info("아래에 팝업 결과가 표시됩니다. (탭③에서도 확인 가능)")
                    _render_popup_table(pop)
            else:
                st.warning("응답에 JURISOFFICECD/APPLCD가 없어 팝업 호출에 필요한 값이 부족합니다.")

        except requests.HTTPError as e:
            st.error(f"HTTP 오류: {e.response.status_code}")
            st.code(e.response.text[:800])
        except Exception as e:
            st.exception(e)

# ====== 탭2: 고객번호 조회 ======
def page_by_customer_no():
    st.subheader("고객번호 조회 (EWM079D00)")

    c1, c2 = st.columns([2,1])
    with c1:
        cust_no = st.text_input("고객번호 (숫자만)", value="0931423032")
    with c2:
        run_live = st.toggle("실시간 호출", value=False, key="toggle079")

    sim_file = st.file_uploader("시뮬레이션 파일(JSON/txt - initInfo 응답 원문)", type=["json","txt"], key="sim079")

    if st.button("조회", key="btn079"):
        try:
            if run_live:
                res = _req_websquare_initinfo(cust_no, gubun="B")
            else:
                text = _read_sim_text(sim_file, SAMPLE_EWM079)
                res = _try_parse_concat_json(text)

            st.session_state["_last_initinfo_cache"] = res  # 탭3 프리필용
            rs = res.get("rsMsg", {})
            st.write("상태:", rs.get("statusCode", "-"))

            data = res.get("dma_initData", {})
            if not data:
                st.warning("데이터가 없습니다.")
                return

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("고객명", data.get("APPLNM","-"))
            k2.metric("발전용량", f"{data.get('EQUIPCAPA','-')} kW")
            k3.metric("접수구분", (data.get("GENINSTCLNM","") or "").replace("고객",""))
            k4.metric("담당부서", f"{data.get('UPPOOFFICENM','')}/{data.get('JURISOFFICENM','')}")

            st.caption("원본 응답(JSON)")
            with st.expander("펼쳐보기", expanded=False):
                st.json(res)

            juris_cd, pop_acpt = _extract_office_and_acpt_from_init(res)
            if juris_cd and pop_acpt:
                st.success(f"관할지사코드: {juris_cd}  |  팝업 acptNo: {pop_acpt}")
                if st.button("이 값으로 ‘접속예정 순서’ 바로 조회", key="jump_from_tab2"):
                    pop = _req_popup_order_search(juris_cd, pop_acpt)
                    st.session_state["_last_popup_result"] = pop
                    st.info("아래에 팝업 결과가 표시됩니다. (탭③에서도 확인 가능)")
                    _render_popup_table(pop)
            else:
                st.warning("응답에 JURISOFFICECD/APPLCD가 없어 팝업 호출에 필요한 값이 부족합니다.")

        except Exception as e:
            st.exception(e)

# ====== 팝업 결과 테이블 공통 렌더러 ======
def _render_popup_table(res: dict):
    # 요약
    c1, c2, c3 = st.columns(3)
    c1.metric("접수단계 A", res.get("cnt_stepA", 0))
    c2.metric("공용망보강 B", res.get("cnt_stepB", 0))
    c3.metric("접속공사 C", res.get("cnt_stepC", 0))

    dfB = pd.DataFrame(res.get("dlt_stepB", []))
    if dfB.empty:
        st.warning("검색 결과(단계 B)가 없습니다.")
        return

    # 가공
    dfB["접수일"] = pd.to_datetime(dfB["ACPTYMD"], format="%Y%m%d", errors="coerce")
    dfB["접속예정순서"] = (dfB.index + 1).astype(int)
    dfB["신청자"] = dfB["APPLNM"].apply(_mask_name)
    dfB.rename(
        columns={
            "UPPOOFFICENM": "본부",
            "JURISOFFICENM": "지사",
            "ACPTSEQNO": "접수번호끝4",
            "GENSOURCENM": "발전원",
            "EQUIPCAPA": "용량(kW)",
            "PROCTPNM": "진행상태",
            "DLNM": "배전선로",
            "MTRNO": "주변압기",
            "SUBSTNM": "변전소",
        },
        inplace=True,
    )

    with st.expander("필터", expanded=False):
        f1, f2, f3 = st.columns(3)
        with f1:
            step = st.multiselect("진행상태", sorted(dfB["진행상태"].dropna().unique().tolist()))
        with f2:
            gen = st.multiselect("발전원", sorted(dfB["발전원"].dropna().unique().tolist()))
        with f3:
            if not dfB["용량(kW)"].empty:
                kmin = float(dfB["용량(kW)"].min())
                kmax = float(dfB["용량(kW)"].max())
            else:
                kmin, kmax = 0.0, 0.0
            rng = st.slider("용량(kW) 범위", kmin, kmax, (kmin, kmax))
            kw_min, kw_max = rng

    f = dfB.copy()
    if 'step' in locals() and step:
        f = f[f["진행상태"].isin(step)]
    if 'gen' in locals() and gen:
        f = f[f["발전원"].isin(gen)]
    if 'kw_min' in locals():
        f = f[(f["용량(kW)"] >= kw_min) & (f["용량(kW)"] <= kw_max)]

    st.dataframe(
        f[
            [
                "본부",
                "지사",
                "접수번호끝4",
                "신청자",
                "접수일",
                "접속예정순서",
                "발전원",
                "용량(kW)",
                "변전소",
                "주변압기",
                "배전선로",
                "진행상태",
            ]
        ].sort_values("접속예정순서"),
        use_container_width=True,
    )

    csv = f.to_csv(index=False).encode("utf-8-sig")
    st.download_button("CSV 다운로드", data=csv, file_name="접속예정순서_조회.csv", mime="text/csv")

# ====== 탭3: 접속예정 순서 조회 ======
def page_order_sequence():
    st.subheader("접속예정 순서 조회 (EWM082D00 팝업)")

    # 최근 initInfo에서 값 자동 채움
    prefill = st.toggle("최근 조회 결과로 자동 채움", value=True)
    juris_auto, acpt_auto = None, None
    if prefill and "_last_initinfo_cache" in st.session_state:
        juris_auto, acpt_auto = _extract_office_and_acpt_from_init(st.session_state["_last_initinfo_cache"])

    c1, c2, c3 = st.columns([1,1,1])
    with c1:
        juris = st.text_input("관할지사코드 (JURISOFFICECD)", value=juris_auto or "5782")
    with c2:
        acpt_no = st.text_input("고객번호(CUSTNO/APPLCD)", value=acpt_auto or "0931423032",
                                help="initInfo의 APPLCD가 팝업 검색 acptNo로 사용됩니다.")
    with c3:
        run_live = st.toggle("실시간 호출", value=False, key="toggle082")

    sim_file = st.file_uploader("시뮬레이션 파일(JSON/txt - 팝업 응답)", type=["json","txt"], key="sim082")

    if st.button("조회", key="btn082"):
        try:
            if run_live:
                res = _req_popup_order_search(juris, acpt_no)
            else:
                text = _read_sim_text(sim_file, SAMPLE_ORDER)
                res = _try_parse_concat_json(text)

            st.session_state["_last_popup_result"] = res
            _render_popup_table(res)

        except requests.HTTPError as e:
            st.error(f"HTTP 오류: {e.response.status_code}")
            st.code(e.response.text[:800])
        except Exception as e:
            st.exception(e)

    # (선택) 최근 결과에서 지사코드 빠르게 선택
    with st.expander("지사코드 빠른 선택(최근 팝업 결과에서 추출)", expanded=False):
        options = []
        pop = st.session_state.get("_last_popup_result")
        if pop:
            for lst_key in ("dlt_stepA", "dlt_stepB", "dlt_stepC"):
                for row in pop.get(lst_key, []):
                    cd = row.get("JURISOFFICECD")
                    nm = row.get("JURISOFFICENM")
                    if cd and nm:
                        options.append((nm, cd))
        options = sorted(set(options))
        if options:
            labels = [f"{nm} ({cd})" for nm, cd in options]
            sel = st.selectbox("지사 선택", labels, index=0)
            pick_cd = options[labels.index(sel)][1]
            if st.button("선택한 지사코드 적용"):
                st.session_state["__picked_juris_cd"] = pick_cd
                st.success(f"적용됨: {pick_cd}")

# ====== 메인 ======
def main():
    st.set_page_config(page_title="KEPCO 신·재생e 통합 조회", layout="wide")
    st.title("⚡ KEPCO 신·재생e 접속진행 현황 보안 강화")
    st.caption("KEPCO WebSquare API 기반 — 비공식 개인 프로젝트")

    _info_box()

    tab1, tab2, tab3 = st.tabs(["① 접수번호 조회", "② 고객번호 조회", "③ 접속예정 순서 조회"])
    with tab1:
        page_by_accept_no()
    with tab2:
        page_by_customer_no()
    with tab3:
        page_order_sequence()

if __name__ == "__main__":
    main()
