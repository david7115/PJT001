# app.py
import json
from io import StringIO
from datetime import datetime
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="통합 앱", layout="wide")

# =========================
# 공통 유틸
# =========================
def to_df(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    # 날짜컬럼 정리
    if "ACPTYMD" in df.columns:
        df["ACPTYMD"] = pd.to_datetime(df["ACPTYMD"], format="%Y%m%d", errors="coerce")
    # 보기좋게 컬럼 정렬
    prefer = [
        "ACPTYMD","ACPT_SEQNO","ACPTSEQNO","JURISOFFICENM","SUBSTCD","PROCTPNM",
        "DLCD","DLNM","GENSOURCENM","EQUIPCAPA","CUSTCLCD","CUSTNO","APPLNM",
        "END_YM","ENDYM","ACPTSTATCD","PROCTPCD","MTRNO","UPPOOFFICENM"
    ]
    cols = [c for c in prefer if c in df.columns] + [c for c in df.columns if c not in prefer]
    return df[cols]

def add_korean_headers(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {
        "ACPTYMD": "접수일",
        "ACPT_SEQNO": "접수일련(전체)",
        "ACPTSEQNO": "접수번호(당일)",
        "JURISOFFICENM": "관할지사",
        "SUBSTCD": "변전소코드",
        "PROCTPNM": "공용망보강 공정",
        "DLCD": "전압구분코드",
        "DLNM": "전압구분",
        "GENSOURCENM": "발전원",
        "EQUIPCAPA": "설비용량(kW)",
        "CUSTCLCD": "계약유형",
        "CUSTNO": "접수번호",
        "APPLNM": "신청인",
        "END_YM": "진행메모1",
        "ENDYM": "진행메모",
        "ACPTSTATCD": "상태코드",
        "PROCTPCD": "공정코드",
        "MTRNO": "단계구분",
        "UPPOOFFICENM": "본부",
    }
    return df.rename(columns={k:v for k,v in mapping.items() if k in df.columns})

def sort_for_rank(df: pd.DataFrame) -> pd.DataFrame:
    # 접수일 → 접수일련(전체) 기준 정렬 가정
    cols = [c for c in ["접수일","접수일련(전체)","ACPTYMD","ACPT_SEQNO"] if c in df.columns]
    if not cols:
        return df
    if "접수일" in df.columns and "접수일련(전체)" in df.columns:
        return df.sort_values(["접수일","접수일련(전체)"])
    elif "ACPTYMD" in df.columns and "ACPT_SEQNO" in df.columns:
        return df.sort_values(["ACPTYMD","ACPT_SEQNO"])
    elif "접수일" in df.columns:
        return df.sort_values(["접수일"])
    else:
        return df.sort_values([cols[0]])

def download_button(df: pd.DataFrame, filename="schedule.csv", label="CSV 내려받기"):
    csv = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(label, csv, file_name=filename, mime="text/csv")

# =========================
# 새 화면: 접속예정 순서 조회
# =========================
def page_schedule_lookup():
    st.title("⚡ 접속예정 순서 조회")

    with st.expander("설명", expanded=False):
        st.markdown(
            "- 한국전력(KEPCO) ‘접속예정 순서’ API를 호출하여 관할지사/접수번호 기준으로 목록을 조회합니다.\n"
            "- 방화·접속 제한 등으로 API가 차단되는 환경을 대비해 **시뮬레이션 모드(샘플 파일 업로드)**도 지원해요.\n"
            "- 정렬 기준은 *접수일 → 접수일련* 가정이며, 실제 운영 기준과 상이할 수 있어 참고용입니다."
        )

    left, right = st.columns([1,1])
    with left:
        mode = st.radio("조회 모드", ["실사용(KEPCO API)", "시뮬레이션(샘플파일)"], horizontal=True)
    with right:
        st.info("※ 접수번호(예: 0931423032)와 관할지사 코드(예: 5782)를 알면 바로 조회할 수 있어요.", icon="ℹ️")

    st.divider()
    if mode == "실사용(KEPCO API)":
        with st.form("api_form", clear_on_submit=False):
            juris = st.text_input("관할지사 코드 (jurisOfficecd)", value="5782")
            acpt  = st.text_input("접수번호 (acptNo)", value="", placeholder="예: 0931423032")
            endpoint = st.text_input("API 엔드포인트", value="https://online.kepco.co.kr/ew/status/pwtr/search")
            submitted = st.form_submit_button("조회")

        if submitted:
            if not juris or not acpt:
                st.warning("관할지사 코드와 접수번호를 모두 입력하세요.")
                return
            payload = {"dma_param": {"jurisOfficecd": juris, "acptNo": acpt}}
            headers = {
                "Accept": "application/json",
                "Content-Type": 'application/json; charset="UTF-8"',
                "User-Agent": "Mozilla/5.0",
                # 서버사이드 호출이라 Origin/Referer/Cookie는 대부분 불필요.
                # 필요한 경우 아래에 추가.
            }
            try:
                with st.spinner("조회 중..."):
                    r = requests.post(endpoint, headers=headers, json=payload, timeout=20)
                    r.raise_for_status()
                    data = r.json()
                render_schedule_result(data, acpt)
            except requests.RequestException as e:
                st.error(f"API 호출 실패: {e}")
                st.stop()
            except ValueError:
                st.error("응답이 JSON 형식이 아닙니다. (로그인/CORS/보호장비 등 확인)")
                st.stop()

            with st.expander("cURL 예시", expanded=False):
                curl = f"""curl -X POST '{endpoint}' \\
  -H 'Accept: application/json' \\
  -H 'Content-Type: application/json; charset="UTF-8"' \\
  --data '{{"dma_param": {{"jurisOfficecd":"{juris}","acptNo":"{acpt}"}}}}'"""
                st.code(curl, language="bash")

    else:
        st.caption("샘플 파일은 txt/json 모두 가능. (예: 접속순서 자료.txt)")
        uploaded = st.file_uploader("샘플 업로드", type=["txt","json"], accept_multiple_files=False)
        acpt_sim = st.text_input("내 접수번호(CUSTNO) (선택)", value="")
        if st.button("샘플로 조회", disabled=uploaded is None):
            raw = uploaded.read().decode("utf-8", errors="ignore")
            try:
                data = json.loads(raw)
            except Exception:
                # txt에 JSON만 들어있다면 그대로 파싱되지만, 앞뒤 여분 문자가 있을 수 있어 보정
                try:
                    # 대괄호/중괄호 블록만 추출 시도
                    start = raw.find("{")
                    end   = raw.rfind("}")
                    data = json.loads(raw[start:end+1])
                except Exception as e:
                    st.error(f"샘플 파싱 실패: {e}")
                    st.stop()
            render_schedule_result(data, acpt_sim)

def render_schedule_result(data: dict, my_acptno: str = ""):
    # 데이터 구조 가정: cnt_stepB, cnt_stepC, dlt_stepA/B/C
    cnt_b = data.get("cnt_stepB")
    cnt_c = data.get("cnt_stepC")
    dlt_a = data.get("dlt_stepA", [])
    dlt_b = data.get("dlt_stepB", [])
    dlt_c = data.get("dlt_stepC", [])

    st.subheader("요약")
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("B단계 건수", str(cnt_b) if cnt_b is not None else "-")
    kpi2.metric("C단계 건수", str(cnt_c) if cnt_c is not None else "-")
    kpi3.metric("A단계 건수", str(len(dlt_a)) if isinstance(dlt_a, list) else "-")

    # 탭 구성
    tabs = st.tabs(["B단계 목록", "C단계 목록", "A단계 목록", "원본(JSON)"])
    for t_idx, (tab, label, recs) in enumerate(zip(
        tabs, ["B", "C", "A"], [dlt_b, dlt_c, dlt_a]
    )):
        with tab:
            df = to_df(recs)
            df = add_korean_headers(df)
            if df.empty:
                st.info(f"{label}단계 데이터가 없습니다.")
                continue

            # 필터 UI
            filt_col1, filt_col2, filt_col3 = st.columns(3)
            with filt_col1:
                proc = st.multiselect("공정(다중선택)", sorted(df["공용망보강 공정"].dropna().unique().tolist()) if "공용망보강 공정" in df else [])
            with filt_col2:
                dlcd = st.multiselect("전압구분코드", sorted(df["전압구분코드"].dropna().unique().tolist()) if "전압구분코드" in df else [])
            with filt_col3:
                date_range = st.date_input("접수일 기간", value=(),
                                           help="비워두면 전체")

            df_view = df.copy()
            if proc and "공용망보강 공정" in df_view:
                df_view = df_view[df_view["공용망보강 공정"].isin(proc)]
            if dlcd and "전압구분코드" in df_view:
                df_view = df_view[df_view["전압구분코드"].isin(dlcd)]
            if len(date_range) == 2 and "접수일" in df_view:
                start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
                df_view = df_view[(df_view["접수일"] >= start) & (df_view["접수일"] <= end)]

            df_view = sort_for_rank(df_view).reset_index(drop=True)
            st.dataframe(df_view, use_container_width=True, height=520)
            download_button(df_view, filename=f"schedule_{label}.csv", label=f"{label}단계 CSV 내려받기")

            # 내 순번 찾기
            if my_acptno:
                st.markdown("—")
                st.markdown(f"**내 접수번호 검색:** `{my_acptno}`")
                cand_col = "접수번호" if "접수번호" in df_view.columns else ("CUSTNO" if "CUSTNO" in df_view.columns else None)
                if cand_col:
                    tmp = sort_for_rank(df).reset_index(drop=True)
                    tmp.index = tmp.index + 1  # 1-based rank
                    hit = tmp[tmp[cand_col].astype(str) == str(my_acptno)]
                    if not hit.empty:
                        rank = int(hit.index[0])
                        st.success(f"현재 목록 내 예상 순번(가정): **{rank}**")
                        st.dataframe(hit, use_container_width=True)
                    else:
                        st.warning("해당 접수번호가 이 단계 목록에서 발견되지 않았습니다.")
                else:
                    st.info("접수번호 컬럼이 없어 순번 계산을 생략합니다.")

    with tabs[-1]:
        st.code(json.dumps(data, ensure_ascii=False, indent=2), language="json")

# =========================
# (예시) 기존 화면들 - 자리만 남겨둠
# =========================
def page_dashboard():
    st.title("📊 대시보드 (기존)")
    st.info("여기는 기존 기능 자리입니다. 필요한 위젯/차트/지표를 이어서 붙이세요.")

def page_settings():
    st.title("⚙️ 설정 (기존)")
    st.info("API 키, 프록시, 사용자 기본값 등을 저장/불러오기 자리를 마련하세요.")

# =========================
# 라우팅
# =========================
with st.sidebar:
    st.header("통합 메뉴")
    page = st.radio(
        "이동",
        ["📊 대시보드 (기존)", "⚡ 접속예정 순서 조회", "⚙️ 설정 (기존)"],
        index=1
    )
    st.caption("통합 버전 · Streamlit")

if page.startswith("⚡"):
    page_schedule_lookup()
elif page.startswith("📊"):
    page_dashboard()
else:
    page_settings()
