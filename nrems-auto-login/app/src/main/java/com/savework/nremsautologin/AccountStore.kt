package com.savework.nremsautologin

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray

/**
 * 계정 목록을 기기 내 암호화 저장소(EncryptedSharedPreferences)에 보관한다.
 * 일부 구형 기기에서 키스토어 초기화가 실패하면 일반 SharedPreferences로 대체된다.
 */
class AccountStore(context: Context) {

    private val prefs: SharedPreferences = try {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            "nrems_accounts_secure",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    } catch (e: Exception) {
        Log.w(TAG, "암호화 저장소 초기화 실패, 일반 저장소 사용", e)
        context.getSharedPreferences("nrems_accounts_plain", Context.MODE_PRIVATE)
    }

    fun load(): MutableList<Account> {
        val raw = prefs.getString(KEY_ACCOUNTS, "[]") ?: "[]"
        val list = mutableListOf<Account>()
        try {
            val arr = JSONArray(raw)
            for (i in 0 until arr.length()) {
                list.add(Account.fromJson(arr.getJSONObject(i)))
            }
        } catch (e: Exception) {
            Log.e(TAG, "계정 목록 파싱 실패", e)
        }
        return list
    }

    fun save(accounts: List<Account>) {
        val arr = JSONArray()
        accounts.forEach { arr.put(it.toJson()) }
        prefs.edit().putString(KEY_ACCOUNTS, arr.toString()).apply()
    }

    companion object {
        private const val TAG = "AccountStore"
        private const val KEY_ACCOUNTS = "accounts"
    }
}
