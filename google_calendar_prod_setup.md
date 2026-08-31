# Production Google Calendar Setup

This guide details the step-by-step process for configuring the Google Calendar OAuth integration for your production app running on Vercel at [https://hrms-cyan-nu.vercel.app/](https://hrms-cyan-nu.vercel.app/).

---

## 1. Configure Google Cloud Console (OAuth Credentials)

You need to update your Google Cloud Project to recognize and authorize your Vercel production domain.

1. **Go to Google Cloud Console:**
   Open the [Google Cloud Console Credentials Page](https://console.cloud.google.com/apis/credentials).

2. **Edit OAuth Client Credentials:**
   * Select your project.
   * Under **OAuth 2.0 Client IDs**, find your Web Client and click edit (pencil icon).

3. **Add Authorized Redirect URIs:**
   * Under **Authorized redirect URIs**, click **Add URI** and enter:
     ```text
     https://hrms-cyan-nu.vercel.app/calendar/oauth2callback
     ```
   * *Note: Keep `http://127.0.0.1:5000/calendar/oauth2callback` and `http://localhost:5000/calendar/oauth2callback` in the list so that local testing continues to work seamlessly.*
   * Click **Save**.

4. **OAuth Consent Screen Configuration:**
   * Navigate to the **OAuth consent screen** page.
   * **Internal Apps (Recommended):** If your Workspace users (e.g., `user@company.com`) are the only ones connecting, set the publishing status to **Internal**. This prevents the Google "unverified app" screen and does not require verification.
   * **Testing Mode:** If it is in testing mode, make sure to add any production HR/Admin email addresses under the **Test users** section, otherwise they will receive authorization errors when trying to connect.

---

## 2. Set Production Environment Variables on Vercel

Provide the following configurations in your Vercel Project Settings under **Environment Variables**:

| Variable Name | Value / Instruction |
| :--- | :--- |
| **`GOOGLE_CLIENT_SECRETS_JSON`** | Paste the entire raw JSON text content from your downloaded Google Client Secret file (`client_secrets.json`). This avoids storing secrets in your code repository. |
| **`SECRET_KEY`** | Use a strong, unique, and static random string. (The app uses this to encrypt Google access tokens. Do not change it post-launch, or users will have to reconnect their calendar). |
| **`TESTING`** | Set to `false` or leave unset on Vercel so the application runs against your production database schema (`public`). |
| **`OAUTHLIB_INSECURE_TRANSPORT`** | Do **not** set this on Vercel (or set to `0`) to force secure HTTPS connections. |

---

## 3. Verify Integration

1. Go to [https://hrms-cyan-nu.vercel.app/calendar/setup](https://hrms-cyan-nu.vercel.app/calendar/setup).
2. Click **Connect Google Calendar**.
3. Grant access using your target production Google Workspace account.
4. Verify you are redirected back to the Vercel app dashboard successfully.
