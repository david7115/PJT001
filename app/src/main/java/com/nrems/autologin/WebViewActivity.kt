package com.nrems.autologin

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Bundle
import android.util.Log
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ProgressBar
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject

/**
 * NREMS 모바일 로그인 페이지를 열고, 저장된 아이디/비밀번호를 주입해 자동으로 로그인한다.
 * 로그인 성공 후 afterLoginUrl 이 지정되어 있으면 해당 모니터링 페이지로 자동 이동한다.
 */
class WebViewActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var progressBar: ProgressBar

    private var loginId = ""
    private var password = ""
    private var afterLoginUrl = ""

    /** 자동 제출 시도 횟수 (무한 루프 방지) */
    private var loginAttempts = 0
    private var movedToAfterUrl = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_webview)

        loginId = intent.getStringExtra(EXTRA_LOGIN_ID).orEmpty()
        password = intent.getStringExtra(EXTRA_PASSWORD).orEmpty()
        afterLoginUrl = intent.getStringExtra(EXTRA_AFTER_URL).orEmpty()
        title = intent.getStringExtra(EXTRA_NAME).orEmpty().ifEmpty { getString(R.string.app_name) }

        progressBar = findViewById(R.id.progress)
        webView = findViewById(R.id.webview)

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = true
            displayZoomControls = false
        }

        // 계정 전환이 가능하도록 이전 로그인 세션 쿠키를 비운다
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            removeAllCookies(null)
            flush()
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.progress = newProgress
                progressBar.visibility = if (newProgress >= 100) View.GONE else View.VISIBLE
            }
        }

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                progressBar.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView, url: String) {
                progressBar.visibility = View.GONE
                if (url.contains("login.php")) {
                    when {
                        loginAttempts < MAX_LOGIN_ATTEMPTS -> {
                            loginAttempts++
                            injectAutoLogin(view)
                        }
                        loginAttempts == MAX_LOGIN_ATTEMPTS -> {
                            loginAttempts++
                            Toast.makeText(
                                this@WebViewActivity,
                                R.string.auto_login_failed,
                                Toast.LENGTH_LONG
                            ).show()
                        }
                    }
                } else if (loginAttempts > 0 && !movedToAfterUrl && afterLoginUrl.isNotBlank()
                    && !url.startsWith(afterLoginUrl)
                ) {
                    // 로그인 페이지를 벗어났다 = 로그인 성공으로 간주하고 모니터링 페이지로 이동
                    movedToAfterUrl = true
                    view.loadUrl(afterLoginUrl)
                }
            }
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) webView.goBack() else finish()
            }
        })

        webView.loadUrl(LOGIN_URL)
    }

    private fun injectAutoLogin(view: WebView) {
        val js = AUTO_LOGIN_JS
            .replace("%ID%", JSONObject.quote(loginId))
            .replace("%PW%", JSONObject.quote(password))
        view.evaluateJavascript(js) { result ->
            Log.d(TAG, "auto-login inject result: $result")
        }
    }

    override fun onDestroy() {
        webView.destroy()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "WebViewActivity"
        const val EXTRA_NAME = "extra_name"
        const val EXTRA_LOGIN_ID = "extra_login_id"
        const val EXTRA_PASSWORD = "extra_password"
        const val EXTRA_AFTER_URL = "extra_after_url"

        const val LOGIN_URL = "http://www.nrems.co.kr/m/login.php"
        private const val MAX_LOGIN_ATTEMPTS = 2

        /**
         * 로그인 폼 자동 감지 + 입력 + 제출 스크립트.
         * 1) 한국 PHP 사이트에서 흔한 필드명(id/pw, mb_id/mb_password 등)을 먼저 찾고
         * 2) 없으면 password 타입 입력칸을 기준으로 휴리스틱하게 찾는다.
         */
        private val AUTO_LOGIN_JS = """
            (function () {
              try {
                if (window.__nremsAutoLoginDone) return "already-done";
                var ID = %ID%;
                var PW = %PW%;

                function pick(selectors, root) {
                  root = root || document;
                  for (var i = 0; i < selectors.length; i++) {
                    var el = root.querySelector(selectors[i]);
                    if (el) return el;
                  }
                  return null;
                }

                var idSelectors = [
                  "input[name='id']", "input[name='mb_id']", "input[name='user_id']",
                  "input[name='userid']", "input[name='login_id']", "input[name='m_id']",
                  "input[name='uid']", "#id", "#user_id", "#login_id", "#userid"
                ];
                var pwSelectors = [
                  "input[name='pw']", "input[name='passwd']", "input[name='password']",
                  "input[name='mb_password']", "input[name='login_pw']", "input[name='m_pw']",
                  "input[name='upw']", "#pw", "#passwd", "#password"
                ];

                var pwEl = pick(pwSelectors) || document.querySelector("input[type='password']");
                if (!pwEl) return "no-password-field";

                var form = pwEl.form;
                var idEl = pick(idSelectors, form || document);
                if (!idEl) {
                  var candidates = (form || document).querySelectorAll(
                    "input[type='text'],input[type='tel'],input[type='email'],input:not([type])"
                  );
                  for (var i = 0; i < candidates.length; i++) {
                    if (candidates[i] !== pwEl) { idEl = candidates[i]; break; }
                  }
                }
                if (!idEl) return "no-id-field";

                function setValue(el, value) {
                  el.focus();
                  el.value = value;
                  try {
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                  } catch (e) {}
                }
                setValue(idEl, ID);
                setValue(pwEl, PW);
                window.__nremsAutoLoginDone = true;

                var btn = null;
                if (form) {
                  btn = form.querySelector(
                    "input[type='submit'],button[type='submit'],input[type='image']"
                  );
                }
                if (!btn) {
                  var clickables = document.querySelectorAll(
                    "a,button,input[type='button'],input[type='submit'],img"
                  );
                  for (var i = 0; i < clickables.length; i++) {
                    var text = (clickables[i].innerText || clickables[i].value || clickables[i].alt || "");
                    if (text.replace(/\s/g, "").indexOf("로그인") >= 0) { btn = clickables[i]; break; }
                  }
                }
                if (btn) { btn.click(); return "clicked"; }
                if (form) {
                  if (typeof form.onsubmit === "function") {
                    if (form.onsubmit() !== false) form.submit();
                  } else {
                    form.submit();
                  }
                  return "submitted";
                }
                return "no-submit-target";
              } catch (e) {
                return "error:" + e.message;
              }
            })();
        """.trimIndent()
    }
}
