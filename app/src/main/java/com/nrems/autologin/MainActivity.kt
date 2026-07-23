package com.nrems.autologin

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.button.MaterialButton
import com.google.android.material.floatingactionbutton.ExtendedFloatingActionButton
import com.google.android.material.textfield.TextInputEditText

class MainActivity : AppCompatActivity() {

    private lateinit var store: AccountStore
    private lateinit var accounts: MutableList<Account>
    private lateinit var adapter: AccountAdapter
    private lateinit var emptyView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        store = AccountStore(this)
        accounts = store.load()

        emptyView = findViewById(R.id.emptyView)
        val recycler = findViewById<RecyclerView>(R.id.recycler)
        recycler.layoutManager = LinearLayoutManager(this)
        adapter = AccountAdapter()
        recycler.adapter = adapter

        findViewById<ExtendedFloatingActionButton>(R.id.fabAdd).setOnClickListener {
            showEditDialog(null)
        }

        refreshEmptyState()
    }

    private fun refreshEmptyState() {
        emptyView.visibility = if (accounts.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun launchLogin(account: Account) {
        val intent = Intent(this, WebViewActivity::class.java).apply {
            putExtra(WebViewActivity.EXTRA_NAME, account.name)
            putExtra(WebViewActivity.EXTRA_LOGIN_ID, account.loginId)
            putExtra(WebViewActivity.EXTRA_PASSWORD, account.password)
            putExtra(WebViewActivity.EXTRA_AFTER_URL, account.afterLoginUrl)
        }
        startActivity(intent)
    }

    /** account == null 이면 신규 등록, 아니면 수정 */
    private fun showEditDialog(account: Account?) {
        val view = LayoutInflater.from(this).inflate(R.layout.dialog_account_edit, null)
        val nameInput = view.findViewById<TextInputEditText>(R.id.inputName)
        val idInput = view.findViewById<TextInputEditText>(R.id.inputLoginId)
        val pwInput = view.findViewById<TextInputEditText>(R.id.inputPassword)
        val urlInput = view.findViewById<TextInputEditText>(R.id.inputAfterUrl)

        account?.let {
            nameInput.setText(it.name)
            idInput.setText(it.loginId)
            pwInput.setText(it.password)
            urlInput.setText(it.afterLoginUrl)
        }

        AlertDialog.Builder(this)
            .setTitle(if (account == null) R.string.add_account else R.string.edit_account)
            .setView(view)
            .setPositiveButton(R.string.save) { _, _ ->
                val name = nameInput.text?.toString()?.trim().orEmpty()
                val loginId = idInput.text?.toString()?.trim().orEmpty()
                val password = pwInput.text?.toString().orEmpty()
                val afterUrl = urlInput.text?.toString()?.trim().orEmpty()
                if (loginId.isEmpty() || password.isEmpty()) return@setPositiveButton

                if (account == null) {
                    accounts.add(
                        Account(
                            name = name.ifEmpty { loginId },
                            loginId = loginId,
                            password = password,
                            afterLoginUrl = afterUrl
                        )
                    )
                } else {
                    account.name = name.ifEmpty { loginId }
                    account.loginId = loginId
                    account.password = password
                    account.afterLoginUrl = afterUrl
                }
                store.save(accounts)
                adapter.notifyDataSetChanged()
                refreshEmptyState()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun confirmDelete(account: Account) {
        AlertDialog.Builder(this)
            .setTitle(R.string.delete_account)
            .setMessage(getString(R.string.delete_confirm, account.name))
            .setPositiveButton(R.string.delete) { _, _ ->
                accounts.remove(account)
                store.save(accounts)
                adapter.notifyDataSetChanged()
                refreshEmptyState()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private inner class AccountAdapter : RecyclerView.Adapter<AccountAdapter.Holder>() {

        inner class Holder(view: View) : RecyclerView.ViewHolder(view) {
            val name: TextView = view.findViewById(R.id.textName)
            val loginId: TextView = view.findViewById(R.id.textLoginId)
            val btnLogin: MaterialButton = view.findViewById(R.id.btnLogin)
            val btnEdit: MaterialButton = view.findViewById(R.id.btnEdit)
            val btnDelete: MaterialButton = view.findViewById(R.id.btnDelete)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_account, parent, false)
            return Holder(view)
        }

        override fun getItemCount(): Int = accounts.size

        override fun onBindViewHolder(holder: Holder, position: Int) {
            val account = accounts[position]
            holder.name.text = account.name
            holder.loginId.text = getString(R.string.id_label, account.loginId)
            holder.btnLogin.setOnClickListener { launchLogin(account) }
            holder.btnEdit.setOnClickListener { showEditDialog(account) }
            holder.btnDelete.setOnClickListener { confirmDelete(account) }
            holder.itemView.setOnClickListener { launchLogin(account) }
        }
    }
}
