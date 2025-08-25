
import os, json, requests, pandas as pd, streamlit as st
import os
import io
import json
import time
import gzip
import base64
import textwrap
import datetime as dt
from typing import Dict, Any, Tuple, Optional
import pandas as pd
import requests
import streamlit as st

# ------------------------------
# 공통 유틸
# ------------------------------
APP_TITLE = "KEPCO 신·재생e 접속진행 현황 통합 뷰어"
API_HOST = "https://online.kepco.co.kr"

def _default_headers() -> Dict[str, str]:
    # 최소 헤더만 사용 (쿠키/세션은 사용자 환경에 따라 달라질 수 있으므로 고정하지 않습니다)
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
    gubun = "A" (접수번호 조회), "B" (고객번호 조회)로 추정
    """
    url = f"{API_HOST}/ew/status/pwtr/initInfo"
    # WebSquare는 JSON body 안에 dma_* 구조를 기대합니다.
    if gubun == "A":
        payload = {"dma_initInfo": {"gubun": "A", "keynum": keynum.replace("-", "")}}
    else:
        payload = {"dma_initInfo": {"gubun": "B", "keynum": keynum}}

    r = requests.post(url, headers=_default_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()   # { "dma_initData": {...}, "rsMsg": {"statusCode": "S" ...} }

def _req_websquare_comp(acpt_no: str, timeout: int = 12) -> dict:
    """
    /ew/status/pwtr/comp : 공사예정일 조회(‘공용망 보강’ 버튼 눌렀을 때)
    """
    url = f"{API_HOST}/ew/status/pwtr/comp"
    payload = {"dma_comp": {"keynum": acpt_no}}
    r = requests.post(url, headers=_default_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()   # { "dma_compData": {...}, "rsMsg": {...} }

def _req_popup_order_search(juris_officecd: str, acpt_no: str, timeout: int = 12) -> dict:
    """
    /ew/status/pwtr/search : 접속예정 순서 조회 팝업(‘EWM082D00.xml’) 실제 검색
    body: {"dma_param": {"jurisOfficecd":"5782","acptNo":"0931423032"}}
    """
    return _req_json_post(
        "/ew/status/pwtr/search",
        {"dma_param": {"jurisOfficecd": juris_officecd, "acptNo": acpt_no}},
        timeout=timeout,
    )

def _mask_name(name: Optional[str]) -> str:
    if not name:
        return "-"
    if len(name) == 1:
        return name + "*"
    return name[0] + "*" + (name[2:] if len(name) > 2 else "")

def _fmt_date8(s: Optional[str]) -> str:
    if not s or len(str(s)) != 8:
        return "-"
    s = str(s)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"

def _fmt_mmddyy6(s: Optional[str]) -> str:
    if not s or len(str(s)) < 6:
        return "-"
    s = str(s)
    tail = s[-6:]
    return f"{tail[:2]}.{tail[2:4]}.{tail[4:6]}"

def _try_parse_concat_json(text: str) -> dict:
    """업로드 txt가 큰 JSON + 부가 문자열이 붙어있는 형태일 수 있으므로,
    첫 번째 ‘{’부터 균형잡힌 ‘}’까지 파싱."""
    start = text.find("{")
    if start == -1:
        raise ValueError("JSON 시작 기호 '{' 를 찾을 수 없습니다.")
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
        raise ValueError("JSON 종료 위치를 찾지 못했습니다.")
    return json.loads(text[start:end_idx])

def _info_box():
    st.info(
        "이 앱은 **KEPCO 신·재생e 접속진행 현황** 공개 웹 화면을 참고하여, 동일한 API 스키마로 조회·시뮬레이션하는 데모입니다.\n"
        "실제 서비스는 KEPCO 측 변경에 따라 응답/필드가 달라질 수 있습니다."
    )

# ------------------------------
# 화면 1: 접수번호 조회 (EWM080D00 흐름)
# ------------------------------
def page_by_accept_no():
    st.subheader("접수번호 조회 (EWM080D00)")

    col1, col2 = st.columns([2,1])
    with col1:
        acpt_no = st.text_input(
            "접수번호 (예: 5782-20240708-010074)",
            value="5782-20240708-010074",
            help="하이픈은 자동 제거되어 전송됩니다."
        )
    with col2:
        run_live = st.toggle("실시간 호출", value=False)

    sim_file = st.file_uploader("시뮬레이션 파일(JSON/txt, EWM080D00 응답)", type=["json","txt"], accept_multiple_files=False)

    if st.button("조회"):
        try:
            if run_live:
                res = _req_websquare_initinfo(acpt_no, gubun="A")
            else:
                if sim_file is None:
                    st.warning("시뮬레이션 파일을 업로드하거나 ‘실시간 호출’을 켜주세요.")
                    return
                text = sim_file.read().decode("utf-8")
                res = _try_parse_concat_json(text)

            rs = res.get("rsMsg", {})
            st.write("상태:", rs.get("statusCode", "-"))

            data = res.get("dma_initData", {})  # 핵심 데이터맵
            if not data:
                st.warning("조회된 데이터가 없습니다.")
                return

            # 상단 요약 카드
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("고객명", data.get("APPLNM","-"))
            k2.metric("발전용량", f"{data.get('EQUIPCAPA','-')} kW")
            k3.metric("접수구분", (data.get("GENINSTCLNM","") or "").replace("고객",""))
            k4.metric("담당부서", f"{data.get('UPPOOFFICENM','')}/{data.get('JURISOFFICENM','')}")

            # 단계 일자
            dates = {
                "01 접수": _fmt_mmddyy6(data.get("YMD01")),
                "02 연계용량 검토": _fmt_mmddyy6(data.get("YMD02")),
                "03 공용망 보강": _fmt_mmddyy6(data.get("YMD03")),
                "04 기술검토": _fmt_mmddyy6(data.get("YMD04")),
                "05 공사 설계": _fmt_mmddyy6(data.get("YMD05")),
                "06 접속공사 착공": _fmt_mmddyy6(data.get("YMD06")),
                "07 접속공사 준공": _fmt_mmddyy6(data.get("YMD07")),
            }
            st.caption("단계별 처리일")
            st.dataframe(pd.DataFrame(dates, index=["일자"]))

            # 공용망 보강 상태 + 공사예정일(선택)
            pblc = data.get("PBLCREINFORCE")
            if pblc in ("1","2","3"):
                st.info("공용망 보강 대상입니다.")
                if st.button("공사예정일 조회 (comp)"):
                    comp = _req_websquare_comp(data.get("APPLCD",""))
                    d = comp.get("dma_compData", {})
                    status = "변전소건설중" if pblc == "1" else "계획수립중"
                    st.write("상태:", status)
                    # API 스펙 상 BRNCHNM/OFFICENM/DESN_NM/END_YM/PHONE_NO
                    row = {
                        "본부": d.get("BRNCHNM","-"),
                        "지사": d.get("OFFICENM","-"),
                        "공사명": d.get("DESN_NM","-"),
                        "완료예정": d.get("END_YM","-"),
                        "연락처": d.get("PHONE_NO","-")
                    }
                    st.table(pd.DataFrame([row]))

        except requests.HTTPError as e:
            st.error(f"HTTP 오류: {e.response.status_code}")
            st.code(e.response.text[:1000])
        except Exception as e:
            st.exception(e)

# ------------------------------
# 화면 2: 고객번호 조회 (EWM079D00의 '고객번호 탭'과 동일 구조)
# ------------------------------
def page_by_customer_no():
    st.subheader("고객번호 조회 (EWM079D00)")

    col1, col2 = st.columns([2,1])
    with col1:
        cust_no = st.text_input("고객번호 (숫자)", value="0931423032")
    with col2:
        run_live = st.toggle("실시간 호출", value=False)

    sim_file = st.file_uploader("시뮬레이션 파일(JSON/txt, EWM079D00 응답)", type=["json","txt"], accept_multiple_files=False)

    if st.button("조회"):
        try:
            if run_live:
                res = _req_websquare_initinfo(cust_no, gubun="B")
            else:
                if sim_file is None:
                    st.warning("시뮬레이션 파일을 업로드하거나 ‘실시간 호출’을 켜주세요.")
                    return
                text = sim_file.read().decode("utf-8")
                res = _try_parse_concat_json(text)

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

            st.caption("접수번호 / 변전소 / 주변압기 / 배전선로")
            st.table(pd.DataFrame([{
                "접수번호 끝4": data.get("ACPTSEQNO","-"),
                "변전소": data.get("SUBSTNM","-"),
                "주변압기": f"#{data.get('MTRNO','-')}",
                "배전선로": data.get("DLNM","-")
            }]))

        except Exception as e:
            st.exception(e)

# ------------------------------
# 화면 3: 접속예정 순서 조회 (팝업 EWM082D00 + /ew/status/pwtr/search)
# ------------------------------
def page_order_sequence():
    st.subheader("접속예정 순서 조회 (팝업)")

    c1, c2, c3 = st.columns([1,1,1])
    with c1:
        juris = st.text_input("관할지사코드 (예: 5782)", value="5782")
    with c2:
        acpt_no = st.text_input("접수번호(끝4자 아님) → 고객번호", value="0931423032",
                                help="팝업 스크립트상 CUSTNO 로 매칭됩니다.")
    with c3:
        run_live = st.toggle("실시간 호출", value=False)

    sim_file = st.file_uploader("시뮬레이션 파일(JSON/txt, ‘접속순서 자료.txt’ 업로드 가능)",
                                type=["json","txt"], accept_multiple_files=False)

    if st.button("조회"):
        try:
            if run_live:
                res = _req_popup_order_search(juris, acpt_no)
            else:
                if sim_file is None:
                    # 데모 편의: 이 레포에 있는 샘플 파일 경로도 시도
                    sample_path = "/mnt/data/접속순서 자료.txt"
                    if os.path.exists(sample_path):
                        with open(sample_path, "r", encoding="utf-8") as f:
                            text = f.read()
                    else:
                        st.warning("시뮬레이션 파일을 업로드하거나 ‘실시간 호출’을 켜주세요.")
                        return
                else:
                    text = sim_file.read().decode("utf-8")
                res = _try_parse_concat_json(text)

            # 응답 구조: cnt_stepA/B/C, dlt_stepA/B/C(list of map)
            cntA, cntB, cntC = res.get("cnt_stepA",0), res.get("cnt_stepB",0), res.get("cnt_stepC",0)
            m1, m2, m3 = st.columns(3)
            m1.metric("접수 단계(A)", cntA)
            m2.metric("공용망보강 단계(B)", cntB)
            m3.metric("접속공사 단계(C)", cntC)

            # 표시는 B단계를 메인으로(팝업 원화면 UX와 유사)
            dfB = pd.DataFrame(res.get("dlt_stepB", []))
            if dfB.empty:
                st.warning("검색 결과가 없습니다.")
                return

            # 가공
            dfB["접수일"] = pd.to_datetime(dfB["ACPTYMD"], format="%Y%m%d", errors="coerce")
            dfB["접속예정순서"] = (dfB.index + 1).astype(int)
            dfB["신청자"] = dfB["APPLNM"].apply(_mask_name)
            dfB.rename(columns={
                "UPPOOFFICENM":"본부", "JURISOFFICENM":"지사",
                "ACPTSEQNO":"접수번호끝4", "GENSOURCENM":"발전원",
                "EQUIPCAPA":"용량(kW)", "PROCTPNM":"진행상태",
                "DLNM":"배전선로", "MTRNO":"주변압기", "SUBSTNM":"변전소"
            }, inplace=True)

            with st.expander("필터"):
                colf1, colf2, colf3 = st.columns(3)
                with colf1:
                    step = st.multiselect("진행상태", sorted(dfB["진행상태"].dropna().unique().tolist()))
                with colf2:
                    gen = st.multiselect("발전원", sorted(dfB["발전원"].dropna().unique().tolist()))
                with colf3:
                    kw_min, kw_max = st.slider("용량(kW) 범위", 0.0, float(dfB["용량(kW)"].max()), (0.0, float(dfB["용량(kW)"].max())))

            f = dfB.copy()
            if step: f = f[f["진행상태"].isin(step)]
            if gen: f = f[f["발전원"].isin(gen)]
            f = f[(f["용량(kW)"] >= kw_min) & (f["용량(kW)"] <= kw_max)]

            st.dataframe(
                f[["본부","지사","접수번호끝4","신청자","접수일","접속예정순서","발전원","용량(kW)","변전소","주변압기","배전선로","진행상태"]]
                .sort_values("접속예정순서")
            )

            csv = f.to_csv(index=False).encode("utf-8-sig")
            st.download_button("CSV 다운로드", data=csv, file_name="접속예정순서_조회.csv", mime="text/csv")

        except requests.HTTPError as e:
            st.error(f"HTTP 오류: {e.response.status_code}")
            st.code(e.response.text[:1000])
        except Exception as e:
            st.exception(e)

# ------------------------------
# 메인
# ------------------------------
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    _info_box()

    tabs = st.tabs([
        "① 접수번호 조회",
        "② 고객번호 조회",
        "③ 접속예정 순서 조회"
    ])

    with tabs[0]:
        page_by_accept_no()
    with tabs[1]:
        page_by_customer_no()
    with tabs[2]:
        page_order_sequence()

if __name__ == "__main__":
    main()





API_HOST = "https://online.kepco.co.kr"

def _default_headers():
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": API_HOST,
        "Referer": f"{API_HOST}/EWM079D00",
        "User-Agent": "Mozilla/5.0",
    }

def _req_json_post(path, payload, timeout=12):
    url = f"{API_HOST}{path}"
    r = requests.post(url, headers=_default_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _req_websquare_initinfo(keynum, gubun="A", timeout=12):
    url = f"{API_HOST}/ew/status/pwtr/initInfo"
    if gubun == "A":
        payload = {"dma_initInfo": {"gubun": "A", "keynum": keynum.replace("-", "")}}
    else:
        payload = {"dma_initInfo": {"gubun": "B", "keynum": keynum}}
    r = requests.post(url, headers=_default_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _req_websquare_comp(acpt_no, timeout=12):
    url = f"{API_HOST}/ew/status/pwtr/comp"
    payload = {"dma_comp": {"keynum": acpt_no}}
    r = requests.post(url, headers=_default_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _req_popup_order_search(juris_officecd, acpt_no, timeout=12):
    return _req_json_post(
        "/ew/status/pwtr/search",
        {"dma_param": {"jurisOfficecd": juris_officecd, "acptNo": acpt_no}},
        timeout=timeout,
    )

def _try_parse_concat_json(text: str) -> dict:
    start = text.find("{")
    if start == -1: raise ValueError("No '{' in text")
    depth = 0; end_idx = None
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i + 1; break
    if end_idx is None: raise ValueError("No matching '}' found")
    return json.loads(text[start:end_idx])

def _mask_name(name):
    if not name: return "-"
    if len(name) == 1: return name + "*"
    return name[0] + "*" + (name[2:] if len(name) > 2 else "")

def main():
    st.set_page_config(page_title="KEPCO 신재생e 통합 조회", layout="wide")
    st.title("⚡ KEPCO 신·재생e 접속진행 현황 통합 뷰어")
    st.caption("KEPCO WebSquare API 기반 — 비공식 개인 프로젝트")

    tab1, tab2, tab3 = st.tabs(["① 접수번호 조회", "② 고객번호 조회", "③ 접속예정 순서 조회"])

    with tab1:
        st.subheader("접수번호 조회 (EWM080D00)")
        acpt_no = st.text_input("접수번호", "5782-20240708-010074")
        run_live = st.toggle("실시간 호출", value=False)
        sim_file = st.file_uploader("시뮬레이션 파일 업로드", type=["txt","json"], key="sim1")
        if st.button("조회", key="btn1"):
            if run_live:
                res = _req_websquare_initinfo(acpt_no, gubun="A")
            else:
                if not sim_file: st.warning("시뮬레이션 파일 필요"); st.stop()
                text = sim_file.read().decode("utf-8")
                res = _try_parse_concat_json(text)
            st.json(res)

    with tab2:
        st.subheader("고객번호 조회 (EWM079D00)")
        cust_no = st.text_input("고객번호", "0931423032")
        run_live2 = st.toggle("실시간 호출", value=False, key="toggle2")
        sim_file2 = st.file_uploader("시뮬레이션 파일 업로드", type=["txt","json"], key="sim2")
        if st.button("조회", key="btn2"):
            if run_live2:
                res = _req_websquare_initinfo(cust_no, gubun="B")
            else:
                if not sim_file2: st.warning("시뮬레이션 파일 필요"); st.stop()
                text = sim_file2.read().decode("utf-8")
                res = _try_parse_concat_json(text)
            st.json(res)

    with tab3:
        st.subheader("접속예정 순서 조회 (EWM082D00)")
        juris = st.text_input("관할지사코드", "5782")
        acpt = st.text_input("고객번호 (CUSTNO)", "0931423032")
        run_live3 = st.toggle("실시간 호출", value=False, key="toggle3")
        sim_file3 = st.file_uploader("시뮬레이션 파일 업로드", type=["txt","json"], key="sim3")
        if st.button("조회", key="btn3"):
            if run_live3:
                res = _req_popup_order_search(juris, acpt)
            else:
                if not sim_file3: st.warning("시뮬레이션 파일 필요"); st.stop()
                text = sim_file3.read().decode("utf-8")
                res = _try_parse_concat_json(text)
            st.write("요약:")
            st.metric("A단계", res.get("cnt_stepA",0))
            st.metric("B단계", res.get("cnt_stepB",0))
            st.metric("C단계", res.get("cnt_stepC",0))
            dfB = pd.DataFrame(res.get("dlt_stepB", []))
            if not dfB.empty:
                dfB["신청자"] = dfB["APPLNM"].apply(_mask_name)
                st.dataframe(dfB)

if __name__ == "__main__":
    main()
