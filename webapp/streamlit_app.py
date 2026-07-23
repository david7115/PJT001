# streamlit_app.py — NREMS 발전소 자동 로그인 & 모니터링 조회 (웹앱 버전)
# - 발전소 계정(이름/ID/PW)을 여러 개 등록해 두고 버튼 한 번으로 자동 로그인
# - 서버(이 앱)가 대신 로그인 후 세션을 유지하며 모니터링 페이지를 가져와 표시
# - 로그인 폼 필드는 페이지를 분석해 자동 감지 (id/pw, mb_id/mb_password 등)

import io
from urllib.parse import urljoin

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

BASE_URL = "http://www.nrems.co.kr"
LOGIN_URL = f"{BASE_URL}/m/login.php"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
)
TIMEOUT = 20

st.set_page_config(page_title="NREMS 자동로그인", page_icon="⚡", layout="wide")


# ----------------------------- 세션/계정 상태 -----------------------------

def init_state():
    if "accounts" not in st.session_state:
        # Streamlit Cloud의 Secrets에 [[accounts]] 로 등록해 두면 자동으로 불러온다
        accounts = []
        try:
            for a in st.secrets.get("accounts", []):
                accounts.append({
                    "name": a.get("name", a.get("id", "")),
                    "id": a.get("id", ""),
                    "pw": a.get("pw", ""),
                    "after_url": a.get("after_url", ""),
                })
        except Exception:
            pass
        st.session_state.accounts = accounts
    st.session_state.setdefault("http", None)       # requests.Session
    st.session_state.setdefault("logged_in_as", "")  # 현재 로그인된 계정 이름
    st.session_state.setdefault("last_page", None)   # (url, html) 마지막으로 가져온 페이지


def new_http_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Referer": LOGIN_URL})
    return s


# ----------------------------- 로그인 로직 -----------------------------

def fetch(sess: requests.Session, url: str) -> requests.Response:
    r = sess.get(url, timeout=TIMEOUT)
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding  # EUC-KR 등 한글 인코딩 자동 감지
    return r


def analyze_login_form(html: str, page_url: str):
    """페이지에서 로그인 폼을 찾아 action/필드명/hidden 값을 알아낸다."""
    soup = BeautifulSoup(html, "html.parser")
    pw_input = soup.find("input", {"type": "password"})
    if pw_input is None:
        return None

    form = pw_input.find_parent("form")
    scope = form if form is not None else soup

    # 아이디 칸: 흔한 이름을 우선, 없으면 폼 안의 첫 텍스트 입력칸
    known_ids = ["id", "mb_id", "user_id", "userid", "login_id", "m_id", "uid"]
    id_input = None
    for name in known_ids:
        id_input = scope.find("input", {"name": name})
        if id_input is not None:
            break
    if id_input is None:
        for inp in scope.find_all("input"):
            t = (inp.get("type") or "text").lower()
            if t in ("text", "tel", "email") and inp is not pw_input:
                id_input = inp
                break
    if id_input is None or not id_input.get("name") or not pw_input.get("name"):
        return None

    hidden = {}
    for inp in scope.find_all("input", {"type": "hidden"}):
        if inp.get("name"):
            hidden[inp["name"]] = inp.get("value", "")

    action = page_url
    method = "post"
    if form is not None:
        action = urljoin(page_url, form.get("action") or page_url)
        method = (form.get("method") or "post").lower()

    return {
        "action": action,
        "method": method,
        "id_field": id_input["name"],
        "pw_field": pw_input["name"],
        "hidden": hidden,
    }


def do_login(user_id: str, password: str):
    """새 세션으로 로그인 시도. (성공여부, 메시지, 로그인 직후 응답) 반환."""
    sess = new_http_session()
    try:
        page = fetch(sess, LOGIN_URL)
    except Exception as e:
        return False, f"로그인 페이지 접속 실패: {e}", None, sess

    form = analyze_login_form(page.text, page.url)
    if form is None:
        return False, "로그인 폼을 찾지 못했습니다 (사이트 구조 변경 가능성)", None, sess

    data = dict(form["hidden"])
    data[form["id_field"]] = user_id
    data[form["pw_field"]] = password

    try:
        if form["method"] == "get":
            resp = sess.get(form["action"], params=data, timeout=TIMEOUT, allow_redirects=True)
        else:
            resp = sess.post(form["action"], data=data, timeout=TIMEOUT, allow_redirects=True)
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
    except Exception as e:
        return False, f"로그인 요청 실패: {e}", None, sess

    # 실패 판정: 응답이 여전히 로그인 폼이거나, alert 로 오류를 띄우는 경우
    still_login_form = analyze_login_form(resp.text, resp.url) is not None
    lowered = resp.text
    alert_fail = ("alert(" in lowered) and any(
        k in lowered for k in ["비밀번호", "아이디", "일치", "없습니다", "확인"]
    ) and "login" in resp.url

    if still_login_form or alert_fail:
        return False, "로그인 실패 — 아이디/비밀번호를 확인하세요", resp, sess

    return True, "로그인 성공", resp, sess


# ----------------------------- 페이지 표시 -----------------------------

def show_page(url: str, html: str):
    st.caption(f"현재 페이지: {url}")

    # 표 형태 데이터 자동 추출 (모니터링 수치는 대부분 표에 있음)
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        tables = []
    if tables:
        st.subheader(f"추출된 표 {len(tables)}개")
        for i, df in enumerate(tables, 1):
            st.markdown(f"**표 {i}**")
            st.dataframe(df, use_container_width=True)
            st.download_button(
                f"표 {i} CSV 다운로드",
                df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"nrems_table_{i}.csv",
                mime="text/csv",
                key=f"dl_{url}_{i}",
            )
    else:
        st.info("이 페이지에서 표 형태의 데이터를 찾지 못했습니다. 아래 원본 화면을 확인하세요.")

    # 페이지 내 링크 목록 → 선택해서 이동
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        text = a.get_text(strip=True) or href
        links.append((text[:40], urljoin(url, href)))
    if links:
        with st.expander(f"페이지 내 링크 {len(links)}개 — 선택해서 이동"):
            labels = [f"{t}  ({u})" for t, u in links]
            picked = st.selectbox("이동할 링크", labels, key=f"lk_{url}")
            if st.button("이 링크 열기", key=f"go_{url}"):
                open_url(links[labels.index(picked)][1])
                st.rerun()

    with st.expander("원본 화면 보기 (HTML 렌더링)"):
        components.html(html, height=600, scrolling=True)


def open_url(url: str):
    sess = st.session_state.http
    if sess is None:
        st.error("먼저 로그인하세요.")
        return
    try:
        r = fetch(sess, url)
        st.session_state.last_page = (r.url, r.text)
    except Exception as e:
        st.error(f"페이지 가져오기 실패: {e}")


# ----------------------------- UI -----------------------------

init_state()
st.title("⚡ NREMS 발전소 자동 로그인")
st.caption(
    "발전소 계정을 등록해 두고 버튼 한 번으로 로그인해서 모니터링 자료를 확인합니다. "
    "계정 정보는 이 브라우저 세션 안에서만 사용됩니다."
)

with st.sidebar:
    st.header("발전소 계정")

    with st.form("add_account", clear_on_submit=True):
        st.subheader("계정 추가")
        name = st.text_input("발전소 이름 (예: 1호 태양광)")
        uid = st.text_input("아이디")
        upw = st.text_input("비밀번호", type="password")
        after = st.text_input("로그인 후 이동할 URL (선택)")
        if st.form_submit_button("추가") and uid and upw:
            st.session_state.accounts.append(
                {"name": name or uid, "id": uid, "pw": upw, "after_url": after}
            )

    if not st.session_state.accounts:
        st.info("등록된 계정이 없습니다. 위에서 추가하세요.")
    for i, acc in enumerate(st.session_state.accounts):
        col1, col2 = st.columns([3, 1])
        with col1:
            if st.button(f"🔐 {acc['name']} 로그인", key=f"login_{i}", use_container_width=True):
                with st.spinner(f"{acc['name']} 로그인 중..."):
                    ok, msg, resp, sess = do_login(acc["id"], acc["pw"])
                if ok:
                    st.session_state.http = sess
                    st.session_state.logged_in_as = acc["name"]
                    target = acc.get("after_url") or (resp.url if resp is not None else BASE_URL + "/m/")
                    open_url(target)
                    st.rerun()
                else:
                    st.error(f"{acc['name']}: {msg}")
        with col2:
            if st.button("삭제", key=f"del_{i}"):
                st.session_state.accounts.pop(i)
                st.rerun()

    st.divider()
    st.caption(
        "여러 기기에서 계정을 유지하려면 Streamlit Cloud의 Secrets에 "
        "`[[accounts]]` 항목으로 등록하세요 (README 참고)."
    )

if st.session_state.logged_in_as:
    st.success(f"✅ 현재 로그인: **{st.session_state.logged_in_as}**")

    col1, col2 = st.columns([4, 1])
    with col1:
        manual_url = st.text_input("직접 이동할 페이지 URL", value=BASE_URL + "/m/")
    with col2:
        st.write("")
        if st.button("페이지 열기", use_container_width=True):
            open_url(manual_url)

    if st.session_state.last_page:
        show_page(*st.session_state.last_page)
else:
    st.info("왼쪽 사이드바에서 발전소 계정을 추가한 뒤 로그인 버튼을 누르세요. (모바일에서는 좌측 상단 » 버튼)")
