package com.nrems.autologin

import org.json.JSONObject
import java.util.UUID

/** 발전소 하나의 로그인 계정 정보 */
data class Account(
    val key: String = UUID.randomUUID().toString(),
    var name: String = "",          // 발전소 이름 (표시용)
    var loginId: String = "",       // 사이트 아이디
    var password: String = "",      // 사이트 비밀번호
    var afterLoginUrl: String = ""  // 로그인 성공 후 자동 이동할 모니터링 페이지 (선택)
) {
    fun toJson(): JSONObject = JSONObject()
        .put("key", key)
        .put("name", name)
        .put("loginId", loginId)
        .put("password", password)
        .put("afterLoginUrl", afterLoginUrl)

    companion object {
        fun fromJson(o: JSONObject): Account = Account(
            key = o.optString("key", UUID.randomUUID().toString()),
            name = o.optString("name"),
            loginId = o.optString("loginId"),
            password = o.optString("password"),
            afterLoginUrl = o.optString("afterLoginUrl")
        )
    }
}
