# Generates and stores the RDS master password. The `random` provider
# creates it; nothing else ever has to type it, see it, or remember to
# rotate it manually.

resource "random_password" "rds_master" {
  length = 24
  # Excludes characters RDS rejects in a Postgres master password: '/', '@',
  # '"', and space. Everything else (letters, digits, the rest of the
  # symbol set) is fair game.
  override_special = "!#$%^&*()-_=+[]{}<>:?"
  special          = true
}

# One secret holding the full connection shape as JSON - username, password,
# host placeholder is added after rds.tf creates the instance (see the
# secret_version below, which is updated once aws_db_instance.main exists).
resource "aws_secretsmanager_secret" "rds_credentials" {
  name                    = "${var.project_name}-rds-credentials"
  description             = "RDS Postgres master credentials for ClaimPilot. Read by the app at runtime (env var or init container) instead of hardcoding a password anywhere in code or Terraform state output."
  recovery_window_in_days = 0
  # 0 = deletable immediately, no 7-30 day recovery hold. Default AWS
  # behaviour is a recovery window so an accidental delete can be undone;
  # that protection matters for a real prod secret, not for a throwaway dev
  # secret you might destroy/recreate a few times while iterating this
  # project. Change to 7+ once this isn't disposable.
}

resource "aws_secretsmanager_secret_version" "rds_credentials" {
  secret_id = aws_secretsmanager_secret.rds_credentials.id
  secret_string = jsonencode({
    username = "claimpilot_admin"
    password = random_password.rds_master.result
    dbname   = "claimpilot"
    port     = 5432
    host     = aws_db_instance.main.address
  })
  # Depends implicitly on aws_db_instance.main existing (rds.tf) because its
  # .address attribute is referenced above - Terraform will create the RDS
  # instance before it can fill in this secret version.
}
