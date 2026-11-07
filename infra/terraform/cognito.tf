# Cognito user pool + Hosted UI for the React frontend's sign-in.
#
# Flow: browser -> Cognito Hosted UI (Authorization Code + PKCE) -> back to
# the SPA with a code -> SPA exchanges it for tokens -> SPA sends the ID
# token as `Authorization: Bearer` -> FastAPI (app/app/auth.py) validates it
# against this pool's JWKS. The pool ID and app client ID below are what
# the API checks the token's issuer and audience against.

variable "frontend_production_url" {
  description = "Public origin of the deployed frontend, e.g. https://claimpilot.example.com (no trailing slash). Leave empty until a domain exists - only localhost callbacks are registered then. Cognito rejects http:// callbacks for anything except localhost, so the HTTP-only ALB hostname can NOT be used here; this needs an HTTPS URL."
  type        = string
  default     = ""
}

variable "frontend_dev_port" {
  description = "Port of the local Vite dev server / kubectl port-forward used for testing. Must match vite.config.ts (strictPort) - Cognito callback URLs are exact-match."
  type        = number
  default     = 5173
}

locals {
  frontend_origins = compact([
    "http://localhost:${var.frontend_dev_port}",
    var.frontend_production_url,
  ])
}

resource "aws_cognito_user_pool" "main" {
  name = "${var.project_name}-users"

  # Email is the username: people sign in with their email address rather
  # than inventing a separate username, and it's the attribute Cognito
  # verifies.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Admin-created users only (no self sign-up). The ALB is public and every
  # triage call spends Bedrock tokens, so "anyone who finds the URL can
  # register and run the agent" is the wrong default for a demo.
  # When to change: set to false to show a "Sign up" link on the Hosted UI.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # Allowlist for federated (Google) sign-ins - see the Lambda below.
  lambda_config {
    pre_sign_up = aws_lambda_function.presignup.arn
  }

  mfa_configuration = "OFF"
  # OFF for a demo with synthetic data. Switch to "OPTIONAL"/"ON" (plus a
  # software_token_mfa_configuration block) before anything real sits here.

  deletion_protection = "INACTIVE"
  # INACTIVE so `terraform destroy` works for a disposable demo environment.

  tags = {
    Name = "${var.project_name}-user-pool"
  }
}

resource "aws_cognito_user_pool_domain" "main" {
  # Cognito-provided prefix domain -> https://<prefix>.auth.<region>.amazoncognito.com
  # (HTTPS, no custom domain or ACM cert needed). Prefixes are unique across
  # ALL AWS accounts, so the account ID is appended to avoid a collision
  # (same trick as the S3 bucket name in s3.tf). Cognito forbids the words
  # "aws", "amazon" and "cognito" in a prefix.
  domain       = "${var.project_name}-auth-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_pool_client" "frontend" {
  name         = "${var.project_name}-frontend"
  user_pool_id = aws_cognito_user_pool.main.id

  # Public SPA client: the browser can't keep a secret, so there isn't one.
  # PKCE (code_challenge/code_verifier, done in the frontend) is what
  # protects the authorization code instead.
  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = concat(["COGNITO"], local.google_enabled ? ["Google"] : [])

  # Exact-match URLs. Localhost works over plain http; anything else must be
  # https. Adding a real domain later: set var.frontend_production_url
  # (e.g. https://claimpilot.example.com) and re-apply - callback becomes
  # <url>/callback and logout lands on <url>/.
  callback_urls = [for o in local.frontend_origins : "${o}/callback"]
  logout_urls   = [for o in local.frontend_origins : "${o}/"]

  # Only refresh-token auth is enabled: sign-in itself goes through the
  # Hosted UI, so no direct password flows (USER_PASSWORD_AUTH etc.) are
  # exposed on this client.
  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]

  id_token_validity      = 60 # minutes; the frontend sends this token to the API
  access_token_validity  = 60
  refresh_token_validity = 30 # days
  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }

  enable_token_revocation       = true
  prevent_user_existence_errors = "ENABLED"

  # The client may only list "Google" once the provider exists.
  depends_on = [aws_cognito_identity_provider.google]
}

# ---------------------------------------------------------------------------
# Google sign-in (federation). Cognito stays the OIDC provider the app talks
# to; Google just authenticates the person, so there is no password stored in
# Cognito for these users and no admin user-creation step. The API still
# validates the same Cognito ID token.
#
# Create the OAuth client in Google Cloud Console (APIs & Services ->
# Credentials -> OAuth client ID -> Web application) with:
#   Authorized redirect URI: <hosted UI domain>/oauth2/idpresponse
#     (terraform output cognito_google_redirect_uri)
# then pass the values WITHOUT putting the secret in a committed file:
#   export TF_VAR_google_client_id=...apps.googleusercontent.com
#   export TF_VAR_google_client_secret=...
# (The secret ends up in the local terraform state, which is gitignored.)
# ---------------------------------------------------------------------------

variable "google_client_id" {
  description = "Google OAuth client ID. Empty = Google sign-in is not created."
  type        = string
  default     = ""
}

variable "google_client_secret" {
  description = "Google OAuth client secret. Pass via TF_VAR_google_client_secret, never in a committed file."
  type        = string
  default     = ""
  sensitive   = true
}

variable "allowed_emails" {
  description = "Google accounts allowed to sign in (exact, case-insensitive). Anyone else is blocked by the pre-sign-up trigger."
  type        = list(string)
  default     = ["vaishnavih18@gmail.com"]
}

variable "allowed_email_domains" {
  description = "Optional: whole email domains allowed to sign in (e.g. a Google Workspace domain). Empty = emails list only."
  type        = list(string)
  default     = []
}

locals {
  # nonsensitive(): only the yes/no of "is a secret set", never the secret itself.
  google_enabled = var.google_client_id != "" && nonsensitive(var.google_client_secret != "")
}

resource "aws_cognito_identity_provider" "google" {
  count = local.google_enabled ? 1 : 0

  user_pool_id  = aws_cognito_user_pool.main.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id        = var.google_client_id
    client_secret    = var.google_client_secret
    authorize_scopes = "openid email profile"
  }

  # email_verified MUST be mapped: Cognito only passes mapped attributes to
  # the pre-sign-up trigger, and the allowlist requires a verified email.
  attribute_mapping = {
    email          = "email"
    email_verified = "email_verified"
    name           = "name"
    username       = "sub"
  }
}

# --- Allowlist (Pre sign-up Lambda) ---------------------------------------

data "archive_file" "presignup" {
  type        = "zip"
  source_file = "${path.module}/lambda/presignup.py"
  output_path = "${path.module}/.build/presignup.zip"
}

resource "aws_iam_role" "presignup" {
  name = "${var.project_name}-cognito-presignup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "presignup_logs" {
  role       = aws_iam_role.presignup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "presignup" {
  function_name    = "${var.project_name}-cognito-presignup"
  role             = aws_iam_role.presignup.arn
  runtime          = "python3.12"
  handler          = "presignup.handler"
  filename         = data.archive_file.presignup.output_path
  source_code_hash = data.archive_file.presignup.output_base64sha256
  timeout          = 5

  environment {
    variables = {
      ALLOWED_EMAILS  = join(",", var.allowed_emails)
      ALLOWED_DOMAINS = join(",", var.allowed_email_domains)
    }
  }

  tags = {
    Name = "${var.project_name}-cognito-presignup"
  }
}

resource "aws_lambda_permission" "cognito_presignup" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.presignup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.main.arn
}

output "cognito_google_redirect_uri" {
  description = "Paste this into the Google OAuth client's 'Authorized redirect URIs'."
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/idpresponse"
}

output "cognito_google_enabled" {
  value = local.google_enabled
}
