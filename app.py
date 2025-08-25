
import os, json, requests, pandas as pd, streamlit as st

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
